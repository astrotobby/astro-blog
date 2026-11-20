#!/usr/bin/env python3
"""Publish a released long-form YouTube master to the existing Astro-blog social accounts.

This is a separate bridge for AI-GEMS long-form videos. It deliberately reuses the
existing FB Page, Instagram Reels, and Rumble publishers in scripts/platforms.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from common import OUT, ROOT, load_config, log
import platforms


LEDGER_PATH = ROOT / "social-relay-ledger.json"
MAX_VIDEO_BYTES = 1_000_000_000
MAX_INSTAGRAM_SECONDS = 15 * 60


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-_")
    return cleaned[:100] or "longform"


def _load_ledger() -> dict:
    try:
        data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _persist_ledger(data: dict) -> None:
    LEDGER_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    subprocess.run(["git", "config", "user.name", "longform-social-relay[bot]"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "longform-social-relay@users.noreply.github.com"],
        check=True,
    )
    subprocess.run(["git", "add", str(LEDGER_PATH.relative_to(ROOT))], check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 0:
        return
    subprocess.run(
        ["git", "commit", "-m", "Record long-form social publishing results"],
        check=True,
        cwd=ROOT,
    )
    branch = subprocess.run(
        ["git", "branch", "--show-current"], check=True, capture_output=True, text=True, cwd=ROOT
    ).stdout.strip() or "main"
    subprocess.run(["git", "push", "origin", f"HEAD:{branch}"], check=True, cwd=ROOT)


def _download_video(url: str, job_id: str) -> Path:
    parsed = urlparse(url)
    allowed_prefix = "/astrotobby/AI-GEMS/releases/download/"
    if parsed.scheme != "https" or parsed.netloc.casefold() != "github.com":
        raise RuntimeError("Video URL must be an HTTPS GitHub release URL")
    if not parsed.path.startswith(allowed_prefix) or ".." in parsed.path:
        raise RuntimeError("Video URL is outside the approved AI-GEMS release path")

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"longform_{_slug(job_id)}.mp4"
    response = requests.get(url, stream=True, timeout=(20, 300), allow_redirects=True)
    response.raise_for_status()
    declared = int(response.headers.get("content-length") or 0)
    if declared and declared > MAX_VIDEO_BYTES:
        raise RuntimeError(f"Video is too large for the connected social publishers ({declared} bytes)")

    written = 0
    with target.open("wb") as output:
        for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
            if not chunk:
                continue
            written += len(chunk)
            if written > MAX_VIDEO_BYTES:
                target.unlink(missing_ok=True)
                raise RuntimeError("Downloaded video exceeded the 1 GB safety limit")
            output.write(chunk)
    if written < 1024 * 1024:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded video is unexpectedly small ({written} bytes)")
    log(f"Downloaded approved long-form release asset ({written} bytes)")
    return target


def _probe_video(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=45, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe could not validate the incoming MP4")
    data = json.loads(result.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float((data.get("format") or {}).get("duration") or 0)
    if not video or not audio:
        raise RuntimeError("The social relay requires a video stream and an audio stream")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if min(width, height) < 720 or max(width, height) < 1280:
        raise RuntimeError(f"Incoming video is below 720p in its native orientation ({width}x{height})")
    if duration < 60:
        raise RuntimeError(f"Incoming long-form video is unexpectedly short ({duration:.1f}s)")
    size = path.stat().st_size
    if size > MAX_VIDEO_BYTES:
        raise RuntimeError("Incoming video exceeds the 1 GB social publishing limit")
    return {
        "duration_seconds": round(duration, 2),
        "width": width,
        "height": height,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "bytes": size,
    }


def _make_instagram_vertical(source: Path, job_id: str) -> Path:
    """Create a full-frame 9:16 Reel without cropping the original 16:9 programme."""
    target = OUT / f"longform_{_slug(job_id)}_instagram_9x16.mp4"
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-filter_complex",
        (
            "[0:v]split=2[bgsrc][fgsrc];"
            "[bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=18:3,eq=brightness=-0.12[bg];"
            "[fgsrc]scale=1080:608:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
        ),
        "-map", "[v]", "-map", "0:a:0?",
        "-r", "24", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart", "-shortest", str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=3600, check=False)
    if result.returncode != 0 or not target.exists():
        target.unlink(missing_ok=True)
        raise RuntimeError(
            "Could not create Instagram 9:16 version: "
            + (result.stderr or result.stdout or "FFmpeg returned no output")[-450:]
        )
    media = _probe_video(target)
    if media["width"] != 1080 or media["height"] != 1920:
        raise RuntimeError(
            f"Instagram version has unexpected dimensions: {media['width']}x{media['height']}"
        )
    if media["duration_seconds"] > MAX_INSTAGRAM_SECONDS or media["bytes"] > MAX_VIDEO_BYTES:
        raise RuntimeError("Instagram version exceeds the 15-minute or 1 GB Reels API limit")
    return target


def _platform_call(name: str, fn, render: dict, cfg: dict) -> dict:
    try:
        result = fn(render, cfg, False)
        if not isinstance(result, dict):
            return {"ok": False, "error": "Publisher returned an unexpected result"}
        return result
    except Exception as exc:  # one destination must not block the others
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def publish(args) -> int:
    job_id = _slug(args.job_id)
    channel = args.channel.strip().lower()
    if channel not in {"astrotobby", "digital_nomad"}:
        raise RuntimeError("Channel must be astrotobby or digital_nomad")
    channel_name = "Astro Tobby" if channel == "astrotobby" else "DIJITOL NOMAD"

    title = " ".join(args.title.split()).strip()
    description = " ".join(args.description.split()).strip()
    youtube_url = args.youtube_url.strip()
    if not title or not description:
        raise RuntimeError("A title and concise description are required")
    if not re.fullmatch(r"https://youtu\.be/[A-Za-z0-9_-]{11}", youtube_url):
        raise RuntimeError("A verified YouTube video URL is required")

    ledger = _load_ledger()
    entry = ledger.get(job_id) or {}
    if entry.get("completed") and not args.force_retry:
        log(f"Social relay already completed for {job_id}; skipping duplicate event")
        return 0
    if entry.get("in_flight") and not args.force_retry:
        log(f"Social relay has an ambiguous previous attempt for {job_id}; refusing duplicate posts")
        return 2

    video = _download_video(args.video_url, job_id)
    media = _probe_video(video)
    tags = json.loads(args.tags_json or "[]")
    if not isinstance(tags, list):
        raise RuntimeError("tags_json must contain a JSON list")
    tags = [
        re.sub(r"[^A-Za-z0-9]", "", str(tag).replace(" ", ""))[:30]
        for tag in tags if str(tag).strip()
    ][:12]
    hashtag_text = " ".join("#" + tag for tag in tags if tag)
    caption = description
    if hashtag_text:
        caption += "\n\n" + hashtag_text
    caption += f"\n\nWatch the full video on YouTube: {youtube_url}"

    render = {
        "post": {
            "slug": f"longform-{channel}-{job_id}",
            "title": title,
            "description": description,
            "url": youtube_url,
        },
        "platform": {
            "caption": caption,
            "ig_caption": caption,
            "yt_desc": description,
            "hashtags": ["#" + tag for tag in tags],
            "short_url": youtube_url,
        },
        "videos": {"horizontal": str(video)},
    }
    cfg = load_config()
    cfg.setdefault("platforms", {}).setdefault("rumble", {})
    cfg["platforms"]["rumble"]["visibility"] = "public"
    cfg["platforms"]["rumble"]["primary_category"] = (
        "Entertainment" if channel == "astrotobby" else "Technology"
    )

    entry.update({
        "job_id": job_id,
        "channel": channel_name,
        "youtube_url": youtube_url,
        "title": title,
        "attempt_started_at": datetime.now(timezone.utc).isoformat(),
        "media": media,
        "in_flight": True,
        "completed": False,
    })
    ledger[job_id] = entry
    _persist_ledger(ledger)

    # Do not retry an uncertain/previously attempted destination automatically.
    results = entry.setdefault("results", {})
    # Rumble's uploader requires accepting a rights/terms declaration in its UI.
    # That declaration must be completed by the owner, not accepted automatically.
    destinations = [
        ("facebook", platforms.post_facebook),
        ("instagram", platforms.post_instagram),
    ]
    summary = {}
    for name, fn in destinations:
        previous = results.get(name) or {}
        previous_result = previous.get("result") or {}
        # Never repost a platform that already succeeded, even during a forced retry.
        if previous_result.get("ok") is True:
            summary[name] = previous_result
            continue
        if previous.get("attempted") and not args.force_retry:
            summary[name] = previous_result or {"ok": False, "skipped": "previous attempt recorded; manual retry required"}
            continue
        if name == "instagram" and (
            media["duration_seconds"] > MAX_INSTAGRAM_SECONDS
            or media["bytes"] > MAX_VIDEO_BYTES
        ):
            result = {
                "ok": False,
                "skipped": "Instagram Reels API supports up to 15 minutes and 1 GB per video",
            }
        elif name == "instagram" and not (
            os.environ.get("INSTAGRAM_USER_ID") and platforms.ig_token()
        ):
            # Let the existing adapter report missing credentials; avoid unnecessary transcoding.
            result = _platform_call(name, fn, render, cfg)
        elif name == "instagram":
            try:
                instagram_video = _make_instagram_vertical(video, job_id)
                instagram_render = {**render, "videos": {"vertical": str(instagram_video)}}
                result = _platform_call(name, fn, instagram_render, cfg)
            except Exception as exc:
                # A Reel formatting failure must not block Facebook or Rumble.
                result = {
                    "ok": False,
                    "error": f"Instagram vertical preparation failed: {type(exc).__name__}: {str(exc)[:240]}",
                }
        else:
            result = _platform_call(name, fn, render, cfg)
        results[name] = {
            "attempted": True,
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "result": result,
        }
        summary[name] = result
        entry["results"] = results
        ledger[job_id] = entry
        _persist_ledger(ledger)

    rumble_previous = results.get("rumble") or {}
    rumble_result = rumble_previous.get("result") or {}
    if rumble_result.get("ok") is not True:
        rumble_result = {
            "ok": False,
            "skipped": "Manual Rumble upload required: owner must personally confirm rights and terms.",
            "video_url": args.video_url,
        }
        results["rumble"] = {
            "attempted": False,
            "result": rumble_result,
        }
        entry["results"] = results
        ledger[job_id] = entry
        _persist_ledger(ledger)
    summary["rumble"] = rumble_result

    entry["in_flight"] = False
    entry["completed"] = True
    entry["completed_at"] = datetime.now(timezone.utc).isoformat()
    entry["results"] = results
    ledger[job_id] = entry
    _persist_ledger(ledger)

    print(json.dumps({
        "job_id": job_id,
        "channel": channel_name,
        "youtube_url": youtube_url,
        "media": media,
        "results": summary,
    }, ensure_ascii=False, indent=2))

    return 0 if all(r.get("ok") is True or r.get("skipped") for r in summary.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--channel", required=True, choices=["astrotobby", "digital_nomad"])
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--youtube-url", required=True)
    parser.add_argument("--video-url", required=True)
    parser.add_argument("--tags-json", default="[]")
    parser.add_argument("--force-retry", action="store_true")
    args = parser.parse_args()
    try:
        return publish(args)
    except Exception as exc:
        log(f"long-form social relay failed: {type(exc).__name__}: {str(exc)[:500]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
