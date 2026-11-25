#!/usr/bin/env python3
"""Run one explicitly confirmed Sync-3 free-trial preview using an existing Kling look.

This is a private quality test, not a publishing step. It submits exactly one
generation and exits; it never uses the production budget variable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.sync.so"
DEFAULT_TEXT = "Welcome back. Here is the update you need to know today."
DEFAULT_VOICE = "en-US-AndrewNeural"
TERMINAL = {"COMPLETED", "NO_OP", "FAILED", "REJECTED"}
MAX_FILE = 20 * 1024 * 1024


def duration(path: Path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)], text=True
    ).strip())


def run(args):
    if not args.confirm_free_trial:
        raise RuntimeError(
            "Confirmation required: verify one free Sync-3 generation remains this month "
            "and that the account has no paid balance you could accidentally consume."
        )
    api_key = os.environ.get("SYNC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SYNC_API_KEY is missing from the AI-GEMS GitHub Actions secrets.")

    looks_path = ROOT / "assets/influencer/looks.yaml"
    data = yaml.safe_load(looks_path.read_text(encoding="utf-8")) or {}
    matches = [item for item in data.get("looks", []) if item.get("id") == args.look]
    if len(matches) != 1:
        raise RuntimeError(f"Approved Kling look not found: {args.look}")
    video = ROOT / matches[0]["clip"]
    if not video.is_file():
        raise FileNotFoundError(video)
    if video.stat().st_size > MAX_FILE:
        raise RuntimeError("Kling clip exceeds the 20 MB safe trial-upload limit.")
    video_duration = duration(video)
    if video_duration <= 0 or video_duration > 15:
        raise RuntimeError(f"Sync-3 free trial accepts at most 15 seconds; source is {video_duration:.2f}s.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    audio = args.output_dir / "sync3_smoke_audio.mp3"
    subprocess.run(
        [
            "edge-tts",
            "--voice", args.voice,
            "--text", args.text,
            "--write-media", str(audio),
        ],
        check=True,
    )
    if not audio.is_file() or audio.stat().st_size < 1000 or audio.stat().st_size > MAX_FILE:
        raise RuntimeError("Generated smoke-test audio is missing, empty or oversized.")
    audio_duration = duration(audio)
    if audio_duration <= 0 or audio_duration > 15:
        raise RuntimeError(f"Sync-3 free trial accepts at most 15 seconds; test audio is {audio_duration:.2f}s.")
    if audio_duration > video_duration + 0.05:
        raise RuntimeError(
            f"Speech ({audio_duration:.2f}s) is longer than the Kling source "
            f"({video_duration:.2f}s). Choose a shorter test line; the source will not be looped."
        )
    synced_input = args.output_dir / "sync3_smoke_source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(video),
            "-t", f"{audio_duration:.3f}", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", str(synced_input),
        ],
        check=True,
    )
    video = synced_input
    video_duration = duration(video)

    generation_key = hashlib.sha256(
        f"sync3-free-smoke|{args.look}|{args.text}|{uuid.uuid4()}".encode()
    ).hexdigest()
    headers = {
        "x-api-key": api_key,
        "Idempotency-Key": generation_key,
    }
    output = args.output_dir / "sync3_smoke_preview.mp4"
    print(
        f"Submitting ONE Sync-3 preview using {args.look}: "
        f"{video_duration:.2f}s video / {audio_duration:.2f}s audio",
        flush=True,
    )

    # One POST only. If the provider rejects the request, do not auto-retry creation.
    with video.open("rb") as video_file, audio.open("rb") as audio_file:
        response = requests.post(
            f"{API}/v2/generate",
            headers=headers,
            data={"model": "sync-3", "outputFileName": "sync3-free-smoke-preview"},
            files={
                "video": (video.name, video_file, "video/mp4"),
                "audio": (audio.name, audio_file, "audio/mpeg"),
            },
            timeout=(30, 180),
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Sync-3 preview request failed (HTTP {response.status_code}): {response.text[:1200]}"
        )
    created = response.json()
    generation_id = created.get("id")
    if not generation_id:
        raise RuntimeError("Sync-3 returned no generation ID: " + response.text[:1000])
    print(f"Sync-3 generation accepted: {generation_id}", flush=True)

    deadline = time.monotonic() + 900
    state = {}
    while time.monotonic() < deadline:
        poll = requests.get(
            f"{API}/v2/generate/{generation_id}",
            headers={"x-api-key": api_key},
            params={"wait": "true", "timeout": "10"},
            timeout=(20, 30),
        )
        poll.raise_for_status()
        state = poll.json()
        status = str(state.get("status", "")).upper()
        print(f"Sync-3 status: {status or 'PENDING'}", flush=True)
        if status in TERMINAL:
            break
    else:
        raise TimeoutError(f"Sync-3 generation {generation_id} did not finish within 15 minutes.")

    if str(state.get("status", "")).upper() != "COMPLETED":
        raise RuntimeError(
            f"Sync-3 generation ended as {state.get('status')}: "
            f"{state.get('error') or state.get('errorCode') or 'no details'}"
        )
    url = state.get("outputUrl")
    if not url or not str(url).startswith("https://"):
        raise RuntimeError("Sync-3 completed without a valid HTTPS outputUrl.")

    download = requests.get(url, stream=True, timeout=(30, 180))
    download.raise_for_status()
    with output.open("wb") as target:
        for block in download.iter_content(chunk_size=1024 * 1024):
            if block:
                target.write(block)
    if not output.is_file() or output.stat().st_size < 10_000:
        raise RuntimeError("Sync-3 returned an empty preview video.")

    result_duration = duration(output)
    if abs(result_duration - audio_duration) > 0.50:
        raise RuntimeError(
            f"Preview duration mismatch: output {result_duration:.2f}s vs "
            f"audio {audio_duration:.2f}s."
        )
    report = {
        "provider": "Sync Labs",
        "model": "sync-3",
        "look": args.look,
        "generation_id": generation_id,
        "video_duration_seconds": video_duration,
        "audio_duration_seconds": audio_duration,
        "output_duration_seconds": result_duration,
        "output_bytes": output.stat().st_size,
        "quality_review_required": True,
    }
    (args.output_dir / "sync3_smoke_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print("SYNC3_PREVIEW_READY", json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--look", required=True, choices=[
        "kling_studio_front", "kling_studio_monitor"
    ])
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--output-dir", type=Path, default=Path(".pipeline/out/sync3-smoke"))
    parser.add_argument("--confirm-free-trial", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
