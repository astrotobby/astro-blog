"""Cross-post AI-GEMS long-form videos using the social publishers already in astro-blog.

The source releases are public, short-lived handoff assets. Posts are idempotent per
(job, destination), so a failed Facebook upload does not repeat a successful Instagram
or Rumble post on the next scheduled poll.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

import platforms
from common import OUT, STATE, load_config, log
from longform_social_relay import _make_instagram_vertical

AI_GEMS_RELEASES = "https://api.github.com/repos/astrotobby/AI-GEMS/releases"
DESTINATIONS = ("facebook", "instagram", "rumble")
MAX_PER_RUN = 4
MIN_YOUTUBE_PUBLIC_GRACE = timedelta(minutes=2)
DOWNLOAD_TIMEOUT = (30, 240)
DOWNLOAD_ATTEMPTS = 5
DOWNLOAD_RETRY_SECONDS = 4


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("jobs"), dict):
            return data
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return {"schema": 1, "jobs": {}}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _github_session() -> requests.Session:
    """Create an authenticated GitHub API session for release polling and assets."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "AstroTobbyLongformSocialBridge/1.1",
        "Accept": "application/vnd.github+json",
    })
    token = (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def _releases(session: requests.Session) -> list[dict]:
    output = []
    page = 1
    while page <= 3:
        response = session.get(
            AI_GEMS_RELEASES,
            params={"per_page": 100, "page": page},
            headers={"Accept": "application/vnd.github+json"},
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list) or not batch:
            break
        output.extend(
            item for item in batch
            if str(item.get("tag_name") or "").startswith("social-handoff-")
            and not item.get("draft")
            and not item.get("prerelease")
        )
        if len(batch) < 100:
            break
        page += 1
    return sorted(output, key=lambda item: str(item.get("created_at") or ""))


def _asset(release: dict, name: str) -> dict | None:
    return next((item for item in release.get("assets", []) if item.get("name") == name), None)


def _download(session: requests.Session, asset: dict, destination: Path) -> Path:
    """Download a large release MP4 atomically, retrying incomplete streams."""
    url = str(asset.get("browser_download_url") or "")
    if urlparse(url).scheme != "https":
        raise RuntimeError(f"Refusing non-HTTPS release asset URL: {url!r}")
    expected = int(asset.get("size") or 0)
    if destination.exists() and destination.stat().st_size >= 100_000:
        if not expected or destination.stat().st_size == expected:
            return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    last_error = None

    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        tmp.unlink(missing_ok=True)
        written = 0
        try:
            with session.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as response:
                response.raise_for_status()
                declared = int(response.headers.get("Content-Length") or expected or 0)
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=2 * 1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        written += len(chunk)
                if declared and written != declared:
                    raise IOError(
                        f"incomplete stream ({written} bytes received; {declared} expected)"
                    )
            if written < 100_000:
                raise IOError(f"downloaded video is too small ({written} bytes)")
            if expected and written != expected:
                raise IOError(f"asset size mismatch ({written} bytes received; {expected} expected)")
            tmp.replace(destination)
            log(f"Downloaded {destination.name}: {written} bytes (attempt {attempt}/{DOWNLOAD_ATTEMPTS})")
            return destination
        except Exception as exc:
            last_error = exc
            tmp.unlink(missing_ok=True)
            if attempt < DOWNLOAD_ATTEMPTS:
                delay = DOWNLOAD_RETRY_SECONDS * attempt
                log(
                    f"video download attempt {attempt}/{DOWNLOAD_ATTEMPTS} failed "
                    f"({type(exc).__name__}: {str(exc)[:180]}); retrying in {delay}s"
                )
                time.sleep(delay)

    raise RuntimeError(
        f"Could not download {destination.name} after {DOWNLOAD_ATTEMPTS} attempts: "
        f"{type(last_error).__name__}: {str(last_error)[:300]}"
    )


def _manifest(session: requests.Session, release: dict) -> dict:
    asset = _asset(release, "manifest.json")
    if not asset:
        raise RuntimeError(f"Release {release.get('tag_name')} has no manifest.json")
    url = str(asset.get("browser_download_url") or "")
    response = session.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()
    required = ("job_id", "channel", "channel_title", "title", "description",
                "video_id", "youtube_url", "publish_at")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise RuntimeError(f"Release manifest is missing required fields: {', '.join(missing)}")
    if data["channel"] not in ("astrotobby", "digital_nomad"):
        raise RuntimeError(f"Unexpected channel in social handoff: {data['channel']!r}")
    return data


def _caption_data(manifest: dict) -> tuple[dict, dict]:
    description = " ".join(str(manifest.get("description") or "").split())
    description = re.sub(r"https?://\S+|www\.\S+", "", description).strip()
    description = description[:280].rstrip(" ,;:-")
    if not description:
        description = f"Watch the latest {manifest['channel_title']} video."
    tags = [re.sub(r"[^A-Za-z0-9]", "", str(tag).replace(" ", ""))[:30]
            for tag in (manifest.get("tags") or []) if str(tag).strip()][:12]
    hashtags = " ".join("#" + tag for tag in tags[:6])
    youtube_url = str(manifest["youtube_url"])
    channel_label = str(manifest["channel_title"])
    caption = f"{channel_label}: {description}\n\nWatch on YouTube: {youtube_url}"
    ig_caption = f"{channel_label}: {description}"
    if hashtags:
        ig_caption += "\n\n" + hashtags
    post = {
        "slug": "longform-" + re.sub(r"[^A-Za-z0-9_-]+", "-", str(manifest["job_id"])).strip("-"),
        "title": str(manifest["title"])[:100],
        "description": description,
        "url": youtube_url,
        "tags": tags,
        "channel": str(manifest["channel"]),
        "channel_title": channel_label,
    }
    platform_data = {
        "caption": caption,
        "ig_caption": ig_caption,
        "yt_desc": description,
        "hashtags": tags,
        "short_url": youtube_url,
        "rumble_link_label": "Watch the YouTube version:",
    }
    return post, platform_data


def _destination_done(result: dict | None) -> bool:
    """A manual Rumble handoff is complete for automation, not a published post."""
    return isinstance(result, dict) and (
        result.get("ok") is True or result.get("manual_handoff") is True
    )


def _instagram_render(render: dict, video_path: Path, job_id: str) -> dict:
    """Attach a dedicated 1080x1920 full-frame asset for Instagram Reels."""
    vertical_path = _make_instagram_vertical(video_path, job_id)
    videos = dict(render.get("videos") or {})
    videos["vertical"] = str(vertical_path)
    return {**render, "videos": videos}


def _write_rumble_handoff(
    render: dict,
    video_asset: dict,
    job_id: str,
    cfg: dict,
) -> tuple[Path, dict]:
    """Create an owner-ready Rumble upload packet without accepting legal terms."""
    post = render.get("post") or {}
    platform_data = render.get("platform") or {}
    channel = str(post.get("channel") or "")
    if channel not in ("astrotobby", "digital_nomad"):
        raise RuntimeError(f"Rumble handoff has an unsupported source channel: {channel!r}")

    video_url = str(video_asset.get("browser_download_url") or "")
    parsed = urlparse(video_url)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() != "github.com"
        or not parsed.path.startswith("/astrotobby/AI-GEMS/releases/download/")
        or ".." in parsed.path
    ):
        raise RuntimeError("Rumble handoff refused a video URL outside the approved AI-GEMS release path")

    title = str(post.get("title") or "Untitled")[:100]
    youtube_url = str(post.get("url") or "")
    description = str(platform_data.get("yt_desc") or post.get("description") or "").strip()
    hashtags = platform_data.get("hashtags") or post.get("tags") or []
    hashtag_text = " ".join(
        "#" + re.sub(r"[^A-Za-z0-9]", "", str(tag).lstrip("#"))[:30]
        for tag in hashtags
        if re.sub(r"[^A-Za-z0-9]", "", str(tag).lstrip("#"))
    )
    if youtube_url:
        description += f"\n\nWatch the YouTube version: {youtube_url}"
    if hashtag_text:
        description += f"\n\n{hashtag_text}"

    rumble_cfg = (cfg.get("platforms") or {}).get("rumble") or {}
    defaults = {"astrotobby": "Entertainment", "digital_nomad": "Technology"}
    by_channel = rumble_cfg.get("primary_category_by_channel") or {}
    category = str(by_channel.get(channel) or defaults[channel])
    visibility = str(rumble_cfg.get("visibility") or "public").lower()
    if visibility not in {"public", "unlisted", "private"}:
        raise RuntimeError(f"Unsupported Rumble visibility in config: {visibility!r}")

    packet = {
        "schema_version": 1,
        "job_id": job_id,
        "source_channel": channel,
        "source_channel_title": str(post.get("channel_title") or channel),
        "destination": "Rumble",
        "status": "awaiting_owner_upload_and_license_confirmation",
        "upload_page": "https://rumble.com/upload",
        "video_download_url": video_url,
        "youtube_url": youtube_url,
        "title": title,
        "description": description,
        "primary_category": category,
        "visibility": visibility,
        "owner_confirmation_required": True,
        "owner_action": (
            "Upload the video, choose the license that matches your rights and intended "
            "distribution, review Rumble's rights/terms declarations, personally confirm "
            "them, and submit. The pipeline does not tick those boxes or submit for you."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    safe_job = re.sub(r"[^A-Za-z0-9_-]+", "-", job_id).strip("-")[:80] or "video"
    path = OUT / f"rumble_handoff_{safe_job}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path, packet


def _publish_destination(
    destination: str,
    render: dict,
    cfg: dict,
    dry_run: bool,
    video_path: Path,
    job_id: str,
    video_asset: dict,
) -> dict:
    """Publish supported destinations while keeping Rumble license/rights confirmation with the owner."""
    if destination == "rumble" and not dry_run:
        handoff_path, packet = _write_rumble_handoff(render, video_asset, job_id, cfg)
        return {
            "ok": False,
            "manual_handoff": True,
            "status": packet["status"],
            "handoff_file": str(handoff_path),
            "upload_page": packet["upload_page"],
            "video_url": packet["video_download_url"],
            "youtube_url": packet["youtube_url"],
            "title": packet["title"],
            "primary_category": packet["primary_category"],
            "visibility": packet["visibility"],
            "owner_confirmation_required": True,
        }

    if destination == "instagram" and not dry_run:
        instagram_render = _instagram_render(render, video_path, job_id)
        instagram_video = Path(instagram_render["videos"]["vertical"])
        try:
            return _post_one(destination, instagram_render, cfg, False)
        finally:
            instagram_video.unlink(missing_ok=True)

    return _post_one(destination, render, cfg, dry_run)


def _post_one(destination: str, render: dict, cfg: dict, dry_run: bool) -> dict:
    if destination == "facebook":
        return platforms.post_facebook(render, cfg, dry_run)
    if destination == "instagram":
        return platforms.post_instagram(render, cfg, dry_run)
    if destination == "rumble":
        return platforms.post_rumble(render, cfg, dry_run)
    raise ValueError(f"Unsupported social destination: {destination}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-destinations", action="store_true",
                        help="check Facebook, Instagram and Rumble credentials without publishing")
    parser.add_argument("--has-pending", action="store_true",
                        help="print true if any public YouTube handoff is ready for social posting")
    parser.add_argument("--limit", type=int, default=MAX_PER_RUN)
    args = parser.parse_args()
    limit = max(1, min(int(args.limit), 20))

    cfg = load_config()
    if args.check_destinations:
        # Existing publishers return before upload in dry-run mode. Instagram may
        # refresh the token cache; no media is uploaded and no post is created.
        dummy = {
            "post": {"slug": "credential-preflight", "title": "Credential preflight",
                     "description": "", "url": ""},
            "platform": {"caption": "", "ig_caption": "", "yt_desc": "", "hashtags": []},
            "videos": {"horizontal": "", "vertical": "", "public_url": ""},
        }
        results = {}
        for destination in DESTINATIONS:
            if destination == "rumble":
                results[destination] = {
                    "ok": True,
                    "manual_handoff": True,
                    "note": "Rumble upload packet is prepared for owner upload and license/rights confirmation; no Rumble credentials are stored in this workflow.",
                }
                continue
            try:
                results[destination] = _post_one(destination, dummy, cfg, True)
            except Exception as exc:
                results[destination] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            print(json.dumps({
                "destination": destination,
                "preflight": True,
                "result": results[destination],
            }, ensure_ascii=False))
        missing = [name for name, result in results.items()
                   if not result.get("ok") and result.get("skipped") == "no creds"]
        errors = [name for name, result in results.items() if result.get("error")]
        log(f"Social credential preflight: {len(DESTINATIONS)-len(missing)-len(errors)}/{len(DESTINATIONS)} configured")
        return 1 if errors else 0

    state_path = STATE / "longform_social_ledger.json"
    state = _load_state(state_path)
    # The AI-GEMS release listing is called every 15 minutes. Authenticate it so
    # GitHub does not apply the low unauthenticated API rate limit to the poller.
    session = _github_session()
    releases = _releases(session)
    now = datetime.now(timezone.utc)
    if args.has_pending:
        ready = False
        for release in releases:
            try:
                manifest = _manifest(session, release)
                publish_at = _utc(str(manifest["publish_at"]))
                if now < publish_at + MIN_YOUTUBE_PUBLIC_GRACE:
                    continue
                prior = state["jobs"].get(str(manifest["job_id"])) or {}
                results = prior.get("results") or {}
                if any(not _destination_done(results.get(destination))
                       for destination in DESTINATIONS):
                    ready = True
                    break
            except Exception as exc:
                log(f"social handoff readiness check skipped: {type(exc).__name__}: {str(exc)[:180]}")
        print("true" if ready else "false")
        return 0

    processed = 0
    failed = 0

    for release in releases:
        tag = str(release.get("tag_name") or "")
        try:
            manifest = _manifest(session, release)
            job_id = str(manifest["job_id"])
            try:
                publish_at = _utc(str(manifest["publish_at"]))
            except Exception as exc:
                raise RuntimeError(f"Invalid publish_at in {tag}: {exc}") from exc
            if now < publish_at + MIN_YOUTUBE_PUBLIC_GRACE:
                log(f"social handoff waiting for scheduled YouTube release: {job_id} at {publish_at.isoformat()}")
                continue

            prior = state["jobs"].setdefault(job_id, {
                "release_tag": tag,
                "channel": manifest["channel"],
                "title": manifest["title"],
                "results": {},
            })
            prior["release_tag"] = tag
            prior["channel"] = manifest["channel"]
            prior["title"] = manifest["title"]
            results = prior.setdefault("results", {})
            pending = [
                destination for destination in DESTINATIONS
                if not _destination_done(results.get(destination))
            ]
            if not pending:
                continue
            if processed >= limit:
                break

            video_asset = _asset(release, "video_16x9.mp4")
            if not video_asset:
                raise RuntimeError(f"Release {tag} has no video_16x9.mp4 asset")
            local_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", job_id)[:80]
            video_path = OUT / f"longform-social-{local_slug}.mp4"

            if args.dry_run:
                # Credential-presence checks run in the destination functions; no file
                # is downloaded and no post is created in dry-run mode.
                render = {
                    "post": {"slug": "longform-" + local_slug, "title": manifest["title"],
                             "description": manifest["description"], "url": manifest["youtube_url"]},
                    "platform": {"caption": manifest["description"], "ig_caption": manifest["description"],
                                 "yt_desc": manifest["description"], "hashtags": manifest.get("tags") or [],
                                 "short_url": manifest["youtube_url"]},
                    "videos": {"horizontal": str(OUT / "_dry-run-placeholder.mp4"),
                               "vertical": str(OUT / "_dry-run-placeholder.mp4"),
                               "public_url": str(video_asset.get("browser_download_url") or "")},
                }
            else:
                _download(session, video_asset, video_path)
                post, platform_data = _caption_data(manifest)
                render = {
                    "post": post,
                    "platform": platform_data,
                    "videos": {
                        "horizontal": str(video_path),
                        "public_url": str(video_asset.get("browser_download_url") or ""),
                    },
                }

            for destination in pending:
                try:
                    result = _publish_destination(
                        destination,
                        render,
                        cfg,
                        args.dry_run,
                        video_path,
                        local_slug,
                        video_asset,
                    )
                except Exception as exc:
                    result = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
                print(json.dumps({
                    "job_id": job_id,
                    "channel": manifest["channel_title"],
                    "destination": destination,
                    "dry_run": args.dry_run,
                    "result": result,
                }, ensure_ascii=False))
                if not args.dry_run:
                    results[destination] = result
                    prior["updated_at"] = datetime.now(timezone.utc).isoformat()
                    _save_state(state_path, state)
                if not result.get("ok") and not result.get("manual_handoff"):
                    failed += 1

            processed += 1
            if not args.dry_run and all(
                _destination_done(results.get(destination)) for destination in DESTINATIONS
            ):
                has_manual_rumble = bool((results.get("rumble") or {}).get("manual_handoff"))
                prior["status"] = (
                    "awaiting_manual_rumble_confirmation" if has_manual_rumble else "complete"
                )
                prior["completed_at"] = datetime.now(timezone.utc).isoformat()
                _save_state(state_path, state)
                video_path.unlink(missing_ok=True)
                if has_manual_rumble:
                    log(
                        f"Facebook and Instagram handled for {job_id}; "
                        "Rumble awaits owner rights/terms confirmation."
                    )
                else:
                    log(f"All social destinations completed for {job_id}; handoff retained until scheduled cleanup.")
        except Exception as exc:
            failed += 1
            log(f"social handoff {tag} failed: {type(exc).__name__}: {str(exc)[:350]}")

    log(f"Long-form social bridge finished: {processed} handoff(s) processed, {failed} destination/error(s), dry_run={args.dry_run}")
    return 0 if failed == 0 or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
