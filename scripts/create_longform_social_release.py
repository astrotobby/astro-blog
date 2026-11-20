"""Publish a temporary public handoff asset for the Astro-blog social publisher.

This bridges long-form YouTube uploads in AI-GEMS to the Facebook/Instagram/Rumble
publisher in astro-blog. The release contains the exact rendered MP4 and a short
manifest; no credentials are copied between repositories.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import longform_pipeline as lp
from common import OUT, log


def brief_description(raw: str) -> str:
    text = str(raw or "").replace("\r", "\n")
    lower = text.casefold()
    markers = (
        "\nsources and further reading:", "\nsources:", "\nreferences:",
        "\ncitations:", "\nfurther reading:",
    )
    positions = [lower.find(marker) for marker in markers if lower.find(marker) >= 0]
    if positions:
        text = text[:min(positions)]
    text = re.sub(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)", r"\1", text, flags=re.I)
    text = re.sub(r"https?://\S+|www\.\S+", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" \t\n-–—;:,.")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    text = " ".join(sentences[:2]).strip()
    if len(text) > 280:
        text = text[:280].rsplit(" ", 1)[0].rstrip(" ,;:-") + "."
    return text


def _run(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, env=env, check=False)


def main() -> int:
    channel = os.environ.get("CHANNEL", "")
    slot = os.environ.get("SLOT", "")
    target_date = os.environ.get("TARGET_DATE") or None
    if channel not in lp.CHANNELS or not slot:
        raise SystemExit("Missing or invalid CHANNEL/SLOT inputs")

    target = lp.publish_time(channel, slot, target_date)
    job_id = lp.make_job_id(channel, slot, target)
    ledger = lp.load_ledger()
    job = (ledger.get("jobs") or {}).get(job_id)
    if not job or job.get("status") not in ("scheduled", "published") or not job.get("video_id"):
        log(f"Social handoff skipped: long-form job {job_id} is not a verified YouTube upload")
        return 0

    tag = f"social-handoff-{job_id}"
    repo = os.environ.get("GITHUB_REPOSITORY", "astrotobby/AI-GEMS")
    env = dict(os.environ)
    env["GH_TOKEN"] = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    if not env["GH_TOKEN"]:
        raise SystemExit("GitHub token missing; cannot create social handoff release")

    existing = _run(["gh", "release", "view", tag, "--repo", repo, "--json", "tagName,assets"], env)
    video_path = Path(OUT) / "video_16x9.mp4"
    temporary_dir = None

    if not video_path.exists() or video_path.stat().st_size < 100_000:
        # When re-running a completed slot, restore its original artifact rather than
        # rendering or uploading another YouTube video.
        run_id = str(job.get("workflow_run_id") or "")
        artifact_name = str(job.get("artifact_name") or "")
        if run_id and artifact_name:
            temporary_dir = tempfile.TemporaryDirectory()
            download = _run([
                "gh", "run", "download", run_id, "--repo", repo,
                "--name", artifact_name, "--dir", temporary_dir.name,
            ], env)
            if download.returncode == 0:
                found = list(Path(temporary_dir.name).rglob("video_16x9.mp4"))
                if found:
                    video_path = found[0]
        if not video_path.exists() or video_path.stat().st_size < 100_000:
            if existing.returncode == 0:
                log(f"Social handoff already exists for {job_id}; no new release needed")
                if temporary_dir:
                    temporary_dir.cleanup()
                return 0
            log(f"Social handoff skipped: original render file is unavailable for {job_id}")
            if temporary_dir:
                temporary_dir.cleanup()
            return 0

    package = job.get("package") or {}
    manifest = {
        "job_id": job_id,
        "channel": channel,
        "channel_title": lp.CHANNELS[channel]["title"],
        "title": str(package.get("title") or job.get("title") or "")[:95],
        "description": brief_description(package.get("description", "")),
        "tags": list(package.get("tags") or [])[:15],
        "video_id": str(job["video_id"]),
        "youtube_url": str(job.get("url") or f"https://youtu.be/{job['video_id']}"),
        "publish_at": str(job.get("publish_at") or target.isoformat()),
        "workflow_run_id": str(job.get("workflow_run_id") or os.environ.get("GITHUB_RUN_ID", "")),
        "created_at": str(job.get("scheduled_at") or job.get("updated_at") or ""),
    }

    with tempfile.TemporaryDirectory() as work:
        manifest_path = Path(work) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if existing.returncode == 0:
            command = [
                "gh", "release", "upload", tag, str(video_path), str(manifest_path),
                "--repo", repo, "--clobber",
            ]
        else:
            command = [
                "gh", "release", "create", tag, str(video_path), str(manifest_path),
                "--repo", repo, "--title", tag,
                "--notes", "Temporary handoff for the connected Astro-blog social publisher. Retained for seven days.",
            ]
        result = _run(command, env)
        if result.returncode:
            raise SystemExit("Social handoff release failed: " + (result.stderr or result.stdout)[-600:])
    log(f"Social handoff release ready: {tag} ({video_path.stat().st_size} bytes)")
    if temporary_dir:
        temporary_dir.cleanup()
    print(json.dumps({"result": "SOCIAL_HANDOFF_READY", "job_id": job_id, "tag": tag,
                      "video_id": manifest["video_id"], "publish_at": manifest["publish_at"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
