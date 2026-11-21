"""Re-render already-published long-form videos with unique visuals.

The original public video is left untouched unless a replacement is fully rendered,
uploaded, and verified public on the same YouTube channel. The old video is then
made private. Existing job idempotency keys are preserved.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import longform_pipeline as lp
from common import OUT, log


def brief_description(raw: str) -> str:
    text = str(raw or "").replace("\r", "\n")
    lower = text.casefold()
    markers = (
        "\nsources and further reading:",
        "\nsources:",
        "\nreferences:",
        "\ncitations:",
        "\nfurther reading:",
    )
    positions = [lower.find(marker) for marker in markers if lower.find(marker) >= 0]
    if positions:
        text = text[:min(positions)]
    text = re.sub(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)", r"\1", text, flags=re.I)
    text = re.sub(r"https?://\S+|www\.\S+", "", text, flags=re.I)
    text = re.sub(r"\[\s*\d{1,3}\s*\]|\(\s*\d{1,3}\s*\)", "", text)
    text = re.sub(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+.*$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" \t\n-–—;:,.")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    text = " ".join(sentences[:2]).strip()
    if len(text) > 280:
        text = text[:280].rsplit(" ", 1)[0].rstrip(" ,;:-") + "."
    return text


def thumbnail_label(title: str) -> str:
    value = title.casefold()
    if "grammy" in value:
        return "GRAMMY RACE 2027"
    if "yamaha" in value:
        return "YAMAHA'S $280M DEAL"
    return " ".join(title.upper().split())[:38]


def build_custom_thumbnail(video: Path, title: str, job_id: str) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    OUT.mkdir(parents=True, exist_ok=True)
    frame = OUT / f"repair-{job_id}-frame.jpg"
    thumb = OUT / f"repair-{job_id}-thumbnail.jpg"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", "22", "-i", str(video), "-frames:v", "1",
            "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1",
            "-q:v", "2", str(frame),
        ],
        check=True, timeout=120,
    )
    image = Image.open(frame).convert("RGB")
    if image.size != (1280, 720):
        raise RuntimeError(f"Unexpected thumbnail frame dimensions: {image.size}")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((36, 550, 1244, 690), radius=22, fill=(0, 0, 0, 190))
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 62)
    label = thumbnail_label(title)
    while draw.textbbox((0, 0), label, font=font, stroke_width=1)[2] > 1120 and font.size > 38:
        font = ImageFont.truetype(font_path, font.size - 4)
    draw.text((68, 585), label, font=font, fill=(255, 255, 255, 255),
              stroke_width=1, stroke_fill=(0, 0, 0, 255))
    Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB").save(
        thumb, "JPEG", quality=90, optimize=True
    )
    if thumb.stat().st_size > 2_000_000:
        raise RuntimeError("Custom thumbnail exceeds YouTube's 2 MB limit")
    return thumb


def upload_replacement(yt, video: Path, package: dict, channel: str,
                      original_status: dict) -> dict:
    """Upload a replacement while preserving the original video's visibility/schedule."""
    from googleapiclient.http import MediaFileUpload

    original_privacy = str(original_status.get("privacyStatus") or "public")
    original_publish_at = original_status.get("publishAt")
    # Scheduled YouTube uploads are private until their exact publishAt timestamp.
    # Never make a future scheduled replacement public early.
    expected_privacy = (
        original_privacy
        if original_privacy in {"public", "private", "unlisted"}
        else "public"
    )

    new_status = {
        "privacyStatus": expected_privacy,
        "selfDeclaredMadeForKids": False,
    }
    if expected_privacy == "private" and original_publish_at:
        new_status["publishAt"] = original_publish_at

    body = {
        "snippet": {
            "title": str(package["title"])[:95],
            "description": brief_description(package.get("description", "")),
            "tags": list(package.get("tags") or [])[:15],
            "categoryId": lp.CHANNELS[channel]["category"],
        },
        "status": new_status,
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        progress, response = request.next_chunk(num_retries=5)
        if progress:
            log(f"replacement YouTube upload {progress.progress() * 100:.1f}%")
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube returned no video ID for replacement upload")
    items = yt.videos().list(part="snippet,status", id=video_id).execute().get("items") or []
    if not items:
        raise RuntimeError("Replacement upload could not be read back")
    item = items[0]
    status = item.get("status") or {}
    snippet = item.get("snippet") or {}
    expected_id = lp.CHANNELS[channel]["channel_id"]
    if snippet.get("channelId") != expected_id:
        raise RuntimeError("Replacement video resolved to the wrong YouTube channel")
    if status.get("privacyStatus") != expected_privacy:
        raise RuntimeError(
            f"YouTube replacement visibility mismatch: expected {expected_privacy!r}, "
            f"got {status.get('privacyStatus')!r}"
        )
    if expected_privacy == "private" and original_publish_at:
        if status.get("publishAt") != original_publish_at:
            raise RuntimeError(
                f"YouTube did not preserve the scheduled release time: "
                f"expected {original_publish_at!r}, got {status.get('publishAt')!r}"
            )
    return {"video_id": video_id, "url": f"https://youtu.be/{video_id}", "status": status}


def set_private_and_verify(yt, video_id: str, expected_channel_id: str) -> None:
    items = yt.videos().list(part="snippet,status", id=video_id).execute().get("items") or []
    if not items:
        raise RuntimeError(f"Original video {video_id} cannot be read; it was not changed")
    old = items[0]
    if (old.get("snippet") or {}).get("channelId") != expected_channel_id:
        raise RuntimeError(f"Safety stop: original video {video_id} belongs to another channel")
    old_status = old.get("status") or {}
    if old_status.get("privacyStatus") == "private" and not old_status.get("publishAt"):
        return
    # Omitting publishAt while setting privacyStatus=private cancels a pending
    # scheduled release as well as taking a public/unlisted duplicate offline.
    yt.videos().update(
        part="status",
        body={"id": video_id, "status": {"privacyStatus": "private"}},
    ).execute()
    after = yt.videos().list(part="status", id=video_id).execute().get("items") or []
    after_status = (after[0].get("status") or {}) if after else {}
    if after_status.get("privacyStatus") != "private" or after_status.get("publishAt"):
        raise RuntimeError(f"YouTube did not confirm video {video_id} is private with no scheduled release")


def create_social_handoff(video: Path, job: dict, replacement: dict, channel: str, job_id: str) -> dict:
    """Create a temporary public release asset for the existing Astro-blog social publisher."""
    import tempfile

    manifest = {
        "job_id": f"repair-{job_id}",
        "source_job_id": job_id,
        "channel": channel,
        "channel_title": lp.CHANNELS[channel]["title"],
        "title": job["package"]["title"],
        "description": brief_description(job["package"].get("description", "")),
        "tags": job["package"].get("tags") or [],
        "video_id": replacement["video_id"],
        "youtube_url": replacement["url"],
        "publish_at": str(job.get("publish_at") or replacement["status"].get("publishAt")
                           or datetime.now(timezone.utc).isoformat()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "privacy_status": str(replacement["status"].get("privacyStatus") or "public"),
    }
    tag = f"social-handoff-repair-{channel}-{job_id}-{replacement['video_id']}"
    with tempfile.TemporaryDirectory() as temporary_dir:
        manifest_path = Path(temporary_dir) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        repo = os.environ.get("GITHUB_REPOSITORY", "astrotobby/AI-GEMS")
        env = dict(os.environ)
        env["GH_TOKEN"] = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        if not env["GH_TOKEN"]:
            raise RuntimeError("No GitHub token available for social handoff release")
        check = subprocess.run(
            ["gh", "release", "view", tag, "--repo", repo],
            capture_output=True, text=True, env=env,
        )
        if check.returncode == 0:
            command = ["gh", "release", "upload", tag, str(video), str(manifest_path),
                       "--repo", repo, "--clobber"]
        else:
            command = ["gh", "release", "create", tag, str(video), str(manifest_path),
                       "--repo", repo, "--title", tag,
                       "--notes", "Temporary social handoff asset; removed by the scheduled retention cleanup."]
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        if result.returncode:
            raise RuntimeError("Could not create social handoff release: " + (result.stderr or result.stdout)[-500:])
    return {"tag": tag, "manifest": manifest}


def repair_one(job_id: str, replace_old: bool = True) -> dict:
    ledger = lp.load_ledger()
    jobs = ledger.get("jobs") or {}
    job = jobs.get(job_id)
    if not job:
        raise RuntimeError(f"Long-form job not found in ledger: {job_id}")
    if job.get("status") not in ("scheduled", "published"):
        raise RuntimeError(f"Refusing to repair job {job_id}: current status is {job.get('status')!r}")
    original_video_id = str(job.get("video_id") or "").strip()
    if not original_video_id:
        raise RuntimeError(f"Job {job_id} has no original video ID")
    channel = str(job.get("channel") or "").strip()
    if channel not in lp.CHANNELS:
        raise RuntimeError(f"Unknown channel in job {job_id}: {channel!r}")
    if not job.get("package") or not job.get("lead"):
        raise RuntimeError(f"Job {job_id} lacks saved narration/topic data; safe same-script repair is impossible")

    yt, _target, _creds, identity = lp.yt_service(channel)
    old_items = yt.videos().list(part="snippet,status", id=original_video_id).execute().get("items") or []
    if not old_items:
        raise RuntimeError(f"Original video {original_video_id} is not readable")
    old_item = old_items[0]
    if (old_item.get("snippet") or {}).get("channelId") != identity["id"]:
        raise RuntimeError("Original video is not on the expected authenticated channel")
    old_status = old_item.get("status") or {}
    if old_status.get("privacyStatus") not in ("public", "private", "unlisted"):
        raise RuntimeError(f"Unexpected original YouTube status: {old_status.get('privacyStatus')!r}")
    if replace_old:
        # Take the known-duplicate original offline before the potentially long
        # render. Preserve old_status in memory so the replacement can inherit
        # its intended public/private/scheduled state after all gates pass.
        set_private_and_verify(yt, original_video_id, identity["id"])
        log(f"Original video {original_video_id} is private during visual replacement")

    package = dict(job["package"])
    package["description"] = brief_description(package.get("description", ""))
    package["tags"] = list(package.get("tags") or [])[:15]
    lead = dict(job["lead"])
    sources = list(job.get("sources") or [])
    repair_slug = f"repair-{job_id}"
    cfg = lp.load_config()
    cfg["visuals"]["scenes"] = 28
    cfg["video"]["fps"] = 24
    cfg["video"]["shot_seconds"] = 6.5
    cfg["video"]["tail_seconds"] = 0.8
    cfg["video"]["music"] = False
    cfg["video"]["captions"] = True
    cfg["influencer"]["enabled"] = False
    cfg["motion_cards"]["enabled"] = False
    cfg.get("voice", {}).get("kokoro", {})["enabled"] = False
    if cfg.get("voice", {}).get("elevenlabs"):
        cfg["voice"]["elevenlabs"]["speed"] = 0.98

    script = lp.build_render_script(repair_slug, lead, sources, package, cfg)
    lp.write_json(f"out/longform_{repair_slug}.json", script)
    log(f"Rendering visual replacement for {job_id}: {package['title']}")
    assets, stock_sources = lp.renderer.fetch_scene_assets(script, cfg, "horizontal")
    video, _duration, _words, voice = lp.renderer.render_variant(
        "horizontal", package["narration"], script, cfg, assets, None
    )
    video_path = Path(video)
    media = lp.check_media(video_path)

    # Final gate: every source must be unique by provider ID and must include a
    # perceptual fingerprint. The renderer has already checked scene-to-scene and
    # cross-channel history before accepting each asset.
    visual_audit = lp.validate_visual_manifest(channel, job_id, len(script.get("scene_prompts") or []), stock_sources)
    thumb_path, thumb_record = lp.build_cinematic_thumbnail(video_path, package["title"], repair_slug, channel)
    stock_sources.append(thumb_record)

    # Refresh the original video status after the long render. Its scheduled
    # publishAt may have elapsed while scenes were being generated; in that case
    # the replacement must go public now instead of carrying a past publishAt.
    latest_originals = yt.videos().list(
        part="snippet,status", id=original_video_id
    ).execute().get("items") or []
    if not latest_originals:
        raise RuntimeError("Original video disappeared before replacement upload; refusing to publish")
    latest_original = latest_originals[0]
    if (latest_original.get("snippet") or {}).get("channelId") != identity["id"]:
        raise RuntimeError("Safety stop: original video channel changed before replacement upload")
    old_status = latest_original.get("status") or old_status
    current_publish_at = old_status.get("publishAt")
    if current_publish_at:
        scheduled_time = datetime.fromisoformat(str(current_publish_at).replace("Z", "+00:00"))
        if scheduled_time.tzinfo is None:
            raise RuntimeError("Original YouTube publishAt has no timezone")
        if scheduled_time <= datetime.now(timezone.utc) and old_status.get("privacyStatus") == "private":
            log("Original scheduled release time elapsed during rendering; making replacement public now")
            old_status = dict(old_status)
            old_status["privacyStatus"] = "public"
            old_status.pop("publishAt", None)

    replacement = upload_replacement(yt, video_path, package, channel, old_status)
    # Thumbnail upload is mandatory. If it cannot be verified, lp cancels the
    # scheduled publication and raises before the original video is made private.
    lp.set_and_verify_thumbnail(yt, replacement["video_id"], thumb_path)
    thumb_result = {"verified": True, "visual_audit": visual_audit}

    # The replacement is verified with the original visibility and scheduled release time
    # before the old version is made private.
    if replace_old:
        set_private_and_verify(yt, original_video_id, identity["id"])

    now = datetime.now(timezone.utc).isoformat()
    job["original_video_id"] = original_video_id
    job["original_url"] = f"https://youtu.be/{original_video_id}"
    job["original_stock_sources"] = job.get("stock_sources") or []
    job["previous_video_id"] = original_video_id
    job["previous_url"] = f"https://youtu.be/{original_video_id}"
    job["video_id"] = replacement["video_id"]
    job["url"] = replacement["url"]
    replacement_status = replacement.get("status") or {}
    if replacement_status.get("privacyStatus") == "private" and replacement_status.get("publishAt"):
        job["status"] = "scheduled"
    elif replacement_status.get("privacyStatus") == "public":
        job["status"] = "published"
    else:
        job["status"] = str(job.get("status") or "published")
    job["package"] = package
    job["stock_sources"] = stock_sources
    job["media"] = media
    job["voice_provider"] = voice
    job["replacement_at"] = now
    job["replacement_reason"] = "duplicate_visual_assets"
    job["replacement_original_privacy"] = old_status.get("privacyStatus")
    job["replacement_thumbnail"] = bool(thumb_result)
    job["visual_audit"] = visual_audit
    lp.save_ledger(ledger)

    try:
        handoff = create_social_handoff(video_path, job, replacement, channel, job_id)
        handoff_result = {"ok": True, "tag": handoff["tag"]}
    except Exception as exc:
        log(f"Social handoff release could not be created: {str(exc)[:250]}")
        handoff_result = {"ok": False, "error": str(exc)[:250]}
    return {
        "job_id": job_id,
        "channel": lp.CHANNELS[channel]["title"],
        "title": package["title"],
        "old_video_id": original_video_id,
        "old_privacy": "private" if replace_old else old_status.get("privacyStatus"),
        "new_video_id": replacement["video_id"],
        "new_url": replacement["url"],
        "new_privacy": (replacement.get("status") or {}).get("privacyStatus"),
        "new_publish_at": (replacement.get("status") or {}).get("publishAt"),
        "description": package["description"],
        "source_count": len(stock_sources),
        "media": media,
        "social_handoff": handoff_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-ids", required=True, help="Comma-separated ledger job IDs")
    parser.add_argument("--keep-original-public", action="store_true",
                        help="Do not make the old duplicate video private after replacement")
    args = parser.parse_args()
    job_ids = [value.strip() for value in args.job_ids.split(",") if value.strip()]
    if not job_ids or len(job_ids) != len(set(job_ids)):
        raise SystemExit("Provide unique comma-separated job IDs")
    results = []
    for job_id in job_ids:
        result = repair_one(job_id, replace_old=not args.keep_original_public)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    print(json.dumps({"result": "VISUAL_REPAIR_COMPLETE", "replacements": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
