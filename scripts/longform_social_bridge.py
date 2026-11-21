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
                if any((results.get(destination) or {}).get("ok") is not True
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
                if not ((results.get(destination) or {}).get("ok") is True)
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
                        "vertical": str(video_path),
                        "public_url": str(video_asset.get("browser_download_url") or ""),
                    },
                }

            for destination in pending:
                try:
                    result = _post_one(destination, render, cfg, args.dry_run)
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
                if not result.get("ok"):
                    failed += 1

            processed += 1
            if not args.dry_run and all(
                (results.get(destination) or {}).get("ok") is True for destination in DESTINATIONS
            ):
                prior["status"] = "complete"
                prior["completed_at"] = datetime.now(timezone.utc).isoformat()
                _save_state(state_path, state)
                video_path.unlink(missing_ok=True)
                log(f"All social destinations completed for {job_id}; handoff retained until scheduled cleanup.")
        except Exception as exc:
            failed += 1
            log(f"social handoff {tag} failed: {type(exc).__name__}: {str(exc)[:350]}")

    log(f"Long-form social bridge finished: {processed} handoff(s) processed, {failed} destination/error(s), dry_run={args.dry_run}")
    return 0 if failed == 0 or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
