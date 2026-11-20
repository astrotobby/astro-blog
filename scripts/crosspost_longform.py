"""Publish verified AI-GEMS long-form videos to the existing Astro-blog social accounts.

The source workflow creates one public social-handoff release per successful YouTube
upload. This receiver posts only to Facebook, Instagram, and Rumble. It never uploads
to YouTube and keeps a per-platform success ledger so a retry does not repost success.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from common import OUT, STATE, content_hash, load_config, load_ledger, log, normalize_title, save_ledger
import platforms


REPO = "astrotobby/AI-GEMS"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=100"
RELEASE_PREFIX = "social-handoff-"
MAX_VIDEO_BYTES = 1_000_000_000
MAX_RETRIES_PER_DESTINATION = 8
POLL_RETRY_SECONDS = 20


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_datetime(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("publish_at must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _get_json(url: str, *, timeout=(15, 90)) -> dict:
    response = requests.get(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "astro-blog-longform-social"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _valid_asset_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.path.startswith(f"/{REPO}/releases/download/")
    )


def _find_handoff_releases() -> list[dict]:
    releases = _get_json(RELEASES_API)
    if not isinstance(releases, list):
        raise RuntimeError("GitHub releases endpoint returned an unexpected response")
    return sorted(
        [release for release in releases
         if str(release.get("tag_name", "")).startswith(RELEASE_PREFIX)
         and not release.get("draft")],
        key=lambda release: str(release.get("created_at") or ""),
    )


def _read_manifest(release: dict) -> tuple[dict, dict] | None:
    assets = {
        str(asset.get("name") or ""): asset
        for asset in (release.get("assets") or [])
    }
    manifest_asset = assets.get("manifest.json")
    video_asset = assets.get("video_16x9.mp4")
    if not manifest_asset or not video_asset:
        log(f"{release.get('tag_name')}: missing manifest.json or video_16x9.mp4; skipping")
        return None
    manifest_url = manifest_asset.get("browser_download_url") or ""
    video_url = video_asset.get("browser_download_url") or ""
    if not _valid_asset_url(manifest_url) or not _valid_asset_url(video_url):
        log(f"{release.get('tag_name')}: handoff asset URL failed repository validation")
        return None
    manifest = _get_json(manifest_url)
    if not isinstance(manifest, dict):
        raise RuntimeError(f"{release.get('tag_name')}: manifest is not a JSON object")
    required = ("job_id", "channel", "title", "description", "video_id", "youtube_url", "publish_at")
    missing = [key for key in required if not manifest.get(key)]
    if missing:
        log(f"{release.get('tag_name')}: manifest missing fields {missing}; skipping")
        return None
    if manifest["channel"] not in ("astrotobby", "digital_nomad"):
        log(f"{release.get('tag_name')}: unknown YouTube channel; skipping")
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,32}", str(manifest["video_id"])):
        log(f"{release.get('tag_name')}: invalid YouTube video ID; skipping")
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", str(manifest["job_id"])):
        log(f"{release.get('tag_name')}: invalid long-form job ID; skipping")
        return None
    return manifest, video_asset


def _youtube_is_public(url: str) -> bool:
    for attempt in range(3):
        try:
            response = requests.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
                headers={"User-Agent": "astro-blog-longform-social"},
                timeout=(10, 30),
            )
            if response.status_code == 200 and response.headers.get("content-type", "").startswith("application/json"):
                data = response.json()
                if data.get("title"):
                    return True
        except requests.RequestException:
            pass
        if attempt < 2:
            time.sleep(POLL_RETRY_SECONDS)
    return False


def _download_video(asset: dict, slug: str) -> Path:
    url = str(asset.get("browser_download_url") or "")
    if not _valid_asset_url(url):
        raise RuntimeError("Video handoff URL failed repository validation")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{slug}.mp4"
    path.unlink(missing_ok=True)
    with requests.get(url, stream=True, timeout=(20, 300),
                      headers={"User-Agent": "astro-blog-longform-social"}) as response:
        response.raise_for_status()
        declared = int(response.headers.get("Content-Length") or 0)
        if declared and declared > MAX_VIDEO_BYTES:
            raise RuntimeError(f"Long-form video is larger than Instagram's 1 GB upload limit ({declared} bytes)")
        written = 0
        with path.open("wb") as output:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                if not chunk:
                    continue
                written += len(chunk)
                if written > MAX_VIDEO_BYTES:
                    raise RuntimeError("Long-form handoff exceeded the 1 GB safety limit")
                output.write(chunk)
    if path.stat().st_size < 100_000:
        path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded long-form video is missing or too small")
    return path


def _probe_video(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate,sample_rate",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=60, check=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise RuntimeError("Social handoff must contain both video and audio")
    duration = float((data.get("format") or {}).get("duration") or 0)
    size = int((data.get("format") or {}).get("size") or path.stat().st_size)
    fps_text = str(video.get("avg_frame_rate") or "0/1")
    try:
        numerator, denominator = fps_text.split("/", 1)
        fps = float(numerator) / max(1.0, float(denominator))
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {
        "duration": duration,
        "size": size,
        "video_codec": video.get("codec_name"),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "audio_codec": audio.get("codec_name"),
        "audio_sample_rate": int(audio.get("sample_rate") or 0),
    }


def _instagram_compatibility(media: dict) -> tuple[bool, str]:
    problems = []
    if not 3 <= media["duration"] <= 900:
        problems.append("duration must be between 3 seconds and 15 minutes")
    if media["size"] > MAX_VIDEO_BYTES:
        problems.append("file exceeds 1 GB")
    if media["video_codec"] not in ("h264", "hevc"):
        problems.append("video codec must be H.264 or HEVC")
    if media["audio_codec"] != "aac" or media["audio_sample_rate"] != 48000:
        problems.append("audio must be AAC at 48 kHz")
    if not 23 <= media["fps"] <= 60:
        problems.append("frame rate must be 23–60 FPS")
    if media["width"] > 1920:
        problems.append("horizontal pixel dimension exceeds 1920")
    return (not problems, "; ".join(problems))


def _slug(job_id: str) -> str:
    return "longform-" + re.sub(r"[^a-zA-Z0-9_-]+", "-", job_id).strip("-")[:90]


def _has_credentials(destination: str) -> bool:
    if destination == "facebook":
        return bool(os.environ.get("FACEBOOK_PAGE_ID") and os.environ.get("FACEBOOK_PAGE_TOKEN"))
    if destination == "instagram":
        return bool(os.environ.get("INSTAGRAM_USER_ID") and platforms.ig_token())
    if destination == "rumble":
        return bool(
            os.environ.get("RUMBLE_STORAGE_STATE")
            or (os.environ.get("RUMBLE_EMAIL") and os.environ.get("RUMBLE_PASSWORD"))
        )
    return False


def _platform_render(manifest: dict, video_path: Path) -> dict:
    title = str(manifest["title"]).strip()[:95]
    description = str(manifest["description"]).strip()[:280]
    youtube_url = str(manifest["youtube_url"]).strip()
    tags = []
    for value in (manifest.get("tags") or []):
        tag = re.sub(r"[^A-Za-z0-9_]", "", str(value)).strip("_")
        if tag and tag.lower() not in {item.lower() for item in tags}:
            tags.append(tag[:30])
        if len(tags) >= 15:
            break
    caption = description + (f"\n\nWatch on YouTube: {youtube_url}" if youtube_url else "")
    post = {
        "slug": _slug(str(manifest["job_id"])),
        "title": title,
        "description": description,
        "url": youtube_url,
        "tags": tags,
    }
    platform_data = {
        "caption": caption,
        "ig_caption": description + "\n\nWatch the full video on YouTube — link in bio.",
        "yt_desc": description,
        "short_url": youtube_url,
        "hashtags": tags,
    }
    return {
        "post": post,
        "videos": {"horizontal": str(video_path), "vertical": None},
        "platform": platform_data,
    }


def _load_previous_results(ledger: dict, slug: str, digest: str) -> tuple[dict, dict]:
    record = ledger.get(slug) or {}
    if record.get("hash") != digest:
        record = {
            "hash": digest,
            "ts": _utc_now().isoformat(),
            "title_key": "",
            "results": {},
        }
    return record, dict(record.get("results") or {})


def _save_destination_result(ledger: dict, slug: str, record: dict,
                             results: dict, destination: str, result: dict) -> None:
    results[destination] = result
    record["results"] = results
    record["ts"] = _utc_now().isoformat()
    ledger[slug] = record
    save_ledger(ledger)


def _publish_one(manifest: dict, video_asset: dict, cfg: dict, ledger: dict,
                 dry_run: bool) -> dict:
    slug = _slug(str(manifest["job_id"]))
    title = str(manifest["title"]).strip()[:95]
    description = str(manifest["description"]).strip()[:280]
    digest = content_hash(slug, title, description)
    record, results = _load_previous_results(ledger, slug, digest)
    requested = [name for name in ("facebook", "instagram", "rumble")
                 if name in set(cfg.get("platforms", {}).get("direct", []))]
    pending = [
        name for name in requested
        if not ((results.get(name) or {}).get("ok") is True)
    ]
    if not pending:
        log(f"{slug}: all configured social destinations already succeeded")
        return {"slug": slug, "status": "already_complete", "results": results}

    creds = [name for name in pending if _has_credentials(name)]
    missing = [name for name in pending if name not in creds]
    for name in missing:
        log(f"{slug}: {name} remains pending because its account credentials are unavailable")

    if not creds:
        return {"slug": slug, "status": "waiting_for_credentials", "results": results}

    video_path = _download_video(video_asset, slug)
    media = _probe_video(video_path)
    log(f"{slug}: downloaded media {media}")
    render = _platform_render(manifest, video_path)
    if dry_run:
        ig_ok, ig_reason = _instagram_compatibility(media)
        return {
            "slug": slug,
            "status": "dry_run_ready",
            "title": title,
            "description": description,
            "youtube_url": manifest["youtube_url"],
            "media": media,
            "instagram_eligible": ig_ok,
            "instagram_note": ig_reason,
            "pending_destinations": creds,
        }

    publishers = {
        "facebook": platforms.post_facebook,
        "instagram": platforms.post_instagram,
        "rumble": platforms.post_rumble,
    }
    for destination in creds:
        if destination == "instagram":
            compatible, reason = _instagram_compatibility(media)
            if not compatible:
                result = {"ok": False, "error": "Instagram compatibility check failed: " + reason}
                _save_destination_result(ledger, slug, record, results, destination, result)
                log(f"{slug}: Instagram skipped by file compatibility guard: {reason}")
                continue
        try:
            result = publishers[destination](render, cfg, False)
            if not isinstance(result, dict):
                result = {"ok": False, "error": "Publisher returned an unexpected response"}
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        _save_destination_result(ledger, slug, record, results, destination, result)
        if result.get("ok"):
            log(f"{slug}: {destination} published -> {result.get('url', 'accepted')}")
        else:
            log(f"{slug}: {destination} not confirmed -> {result.get('error') or result.get('skipped') or 'unknown'}")

    return {"slug": slug, "status": "processed", "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-releases", type=int, default=1)
    args = parser.parse_args()
    if args.max_releases < 1 or args.max_releases > 20:
        raise SystemExit("--max-releases must be between 1 and 20")

    cfg = load_config()
    ledger = load_ledger()
    releases = _find_handoff_releases()
    if not releases:
        log("No AI-GEMS long-form social handoff releases found")
        return 0

    processed = 0
    for release in releases:
        handoff = _read_manifest(release)
        if not handoff:
            continue
        manifest, video_asset = handoff
        try:
            publish_at = _parse_datetime(manifest["publish_at"])
        except (TypeError, ValueError) as exc:
            log(f"{release.get('tag_name')}: invalid publish_at ({exc})")
            continue
        if _utc_now() < publish_at + dt.timedelta(minutes=1):
            continue
        youtube_url = str(manifest["youtube_url"])
        if not _youtube_is_public(youtube_url):
            log(f"{release.get('tag_name')}: YouTube video is not publicly resolvable yet; will retry later")
            continue

        slug = _slug(str(manifest["job_id"]))
        digest = content_hash(slug, str(manifest["title"]), str(manifest["description"]))
        record, results = _load_previous_results(ledger, slug, digest)
        destinations = [name for name in ("facebook", "instagram", "rumble")
                        if name in set(cfg.get("platforms", {}).get("direct", []))]
        if all((results.get(name) or {}).get("ok") is True for name in destinations):
            continue

        outcome = _publish_one(manifest, video_asset, cfg, ledger, args.dry_run)
        print(json.dumps({
            "release": release.get("tag_name"),
            "job_id": manifest["job_id"],
            "channel": manifest["channel"],
            "video_id": manifest["video_id"],
            **outcome,
        }, ensure_ascii=False, default=str))
        processed += 1
        if processed >= args.max_releases:
            break

    if not processed:
        log("No due long-form releases with pending social destinations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
