"""Production adapter for the free/open-source TBDub Student lip-sync model.

This adapter prepares one audio file per on-camera segment and invokes one persistent
worker so the approximately 15 GB model is loaded only once per output variant.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

from common import OUT, ROOT, log


TBDUB_DIR = ROOT / "third_party" / "TBDub"
WORKER = ROOT / "scripts" / "tbdub_worker.py"


def _python():
    configured = os.environ.get("TBDUB_PYTHON")
    if configured:
        return Path(configured)
    candidates = [
        ROOT / ".venv-tbdub" / "bin" / "python",
        ROOT / ".venv-tbdub" / "Scripts" / "python.exe",
    ]
    return next((path for path in candidates if path.is_file()), candidates[0])


def checkpoint_dir():
    return Path(os.environ.get("TBDUB_CHECKPOINT_DIR") or ROOT / ".models" / "tbdub" / "checkpoints").expanduser()


def _run(cmd, **kwargs):
    log("$ " + " ".join(str(part) for part in cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def _source_duration(path):
    value = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)
    ], text=True).strip()
    return float(value)


def _source_frame_count(path):
    value = subprocess.check_output([
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames",
        "-of", "default=nw=1:nk=1", str(path)
    ], text=True).strip()
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Cannot determine decoded frame count for TBDub source {path}: {value!r}") from exc
    if count <= 0:
        raise RuntimeError(f"TBDub source has no decoded video frames: {path}")
    return count


def _runtime():
    python = _python()
    ckpt = checkpoint_dir()
    if not python.is_file():
        raise RuntimeError(
            f"TBDub Python runtime is missing: {python}. Run scripts/setup_tbdub.sh on a supported GPU runner."
        )
    if not (TBDUB_DIR / "inference.py").is_file():
        raise RuntimeError(
            f"TBDub source checkout is missing: {TBDUB_DIR}. Run scripts/setup_tbdub.sh."
        )
    if not WORKER.is_file():
        raise RuntimeError(f"TBDub worker is missing: {WORKER}")
    return python, ckpt


def preflight(cfg, looks):
    """Check GPU/model availability and run MediaPipe crop detection on each approved look."""
    python, ckpt = _runtime()
    command = [
        str(python), str(WORKER), "--check-only",
        "--tbdub-dir", str(TBDUB_DIR), "--checkpoint-dir", str(ckpt),
    ]
    result = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True)
    if result.stdout:
        for line in result.stdout.splitlines():
            log(line)
    if result.returncode:
        detail = (result.stderr or result.stdout or "unknown TBDub preflight error")[-1800:]
        raise RuntimeError("TBDub GPU/model preflight failed; publication is blocked. " + detail)

    for look in looks:
        clip = look.get("clip")
        if not clip or not Path(clip).is_file():
            raise RuntimeError(f"TBDub requires a real source video for look {look.get('id')}; still images are not accepted.")
        report = OUT / f"_tbdub_facecheck_{look['id']}.json"
        preview_dir = OUT / "_tbdub_preflight"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview = preview_dir / f"{look['id']}_crop.mp4"
        cmd = [
            str(python), str(TBDUB_DIR / "inference.py"),
            "--video", str(clip), "--preprocess-only",
            "--output-dir", str(preview_dir),
            "--sample-name", str(look["id"]),
            "--checkpoint-dir", str(ckpt),
            "--preprocess-report", str(report),
        ]
        result = subprocess.run(cmd, cwd=str(TBDUB_DIR), text=True, capture_output=True)
        if result.returncode or not preview.is_file() or preview.stat().st_size < 1000:
            detail = (result.stderr or result.stdout or "MediaPipe could not detect the face consistently")[-1200:]
            raise RuntimeError(f"TBDub face preflight failed for {look['id']}: {detail}")
        log(f"TBDub MediaPipe face crop verified: {look['id']}")
    return True


def generate_tbdub_batch(jobs, cfg):
    """Lip-sync each A-roll independently; return a dict keyed by job id."""
    if not jobs:
        return {}
    python, ckpt = _runtime()
    inf = cfg.get("influencer", {})
    model_cfg = inf.get("tbdub", {})
    manifest_path = OUT / "_tbdub_batch_manifest.json"
    results_path = manifest_path.with_suffix(".results.json")
    payload = {
        "jobs": [{
            "id": str(job["id"]),
            "video": str(Path(job["video"]).resolve()),
            "audio": str(Path(job["audio"]).resolve()),
            "output": str(Path(job["output"]).resolve()),
            "seed": int(job.get("seed", 42)),
            "start_frame": int(job.get("start_frame", 0)),
            "preprocess_cache": str(Path(job["preprocess_cache"]).resolve()) if job.get("preprocess_cache") else None,
            "preprocess_report": str(Path(job["preprocess_report"]).resolve()) if job.get("preprocess_report") else None,
            "save_comparison": bool(model_cfg.get("save_comparison", False)),
        } for job in jobs],
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    results_path.unlink(missing_ok=True)
    command = [
        str(python), str(WORKER),
        "--manifest", str(manifest_path),
        "--tbdub-dir", str(TBDUB_DIR),
        "--checkpoint-dir", str(ckpt),
    ]
    env = os.environ.copy()
    env["TBDUB_CHECKPOINT_DIR"] = str(ckpt)
    result = subprocess.run(command, cwd=str(ROOT), env=env, text=True, capture_output=True)
    for line in (result.stdout or "").splitlines()[-120:]:
        log(line)
    if result.returncode != 0 or not results_path.is_file():
        detail = (result.stderr or result.stdout or "worker returned no result manifest")[-2500:]
        raise RuntimeError("TBDub Student inference failed; refusing unsynchronized presenter footage. " + detail)
    result_data = json.loads(results_path.read_text(encoding="utf-8"))
    outputs = {}
    for item in result_data.get("jobs", []):
        output = Path(item["output"])
        if not output.is_file() or output.stat().st_size < 10_000:
            raise RuntimeError(f"TBDub output missing or too small for {item.get('id')}")
        outputs[item["id"]] = output
    expected = {str(job["id"]) for job in jobs}
    if set(outputs) != expected:
        raise RuntimeError(f"TBDub returned {len(outputs)} of {len(expected)} requested segments.")
    log(f"TBDub Student synchronized {len(outputs)} independent presenter segments.")
    return outputs


def build_jobs(plans, voices, cfg):
    """Extract one matching speech sample for every A-roll segment; never join disjoint audio."""
    jobs = []
    inf = cfg.get("influencer", {})
    for tag, segments in plans.items():
        for index, segment in enumerate(segments):
            if segment.get("kind") != "A":
                continue
            look = segment.get("look") or {}
            source = look.get("clip")
            if not source or not Path(source).is_file():
                raise RuntimeError(f"TBDub requires a video clip for look {look.get('id')}; no still-image/unsynced fallback is allowed.")
            duration = float(segment["t1"] - segment["t0"])
            source_duration = _source_duration(source)
            source_frames = _source_frame_count(source)
            job_id = f"{tag}_{index:02d}"
            # TBDub Student consumes overlapping 77-frame windows with a 72-frame
            # stride. Keep each audio excerpt below 72 frames and seek using the
            # ACTUAL decoded source-frame count (Kling clips may be 24 fps, not 25).
            # Requiring one complete 72-frame source window prevents upstream
            # make_pingpong_indices() from repeating/bouncing the input.
            audio_frames = max(1, int(duration * 25))
            required_source_frames = max(72, math.ceil(audio_frames / 72) * 72)
            max_start_frames = source_frames - required_source_frames
            if max_start_frames < 0:
                raise RuntimeError(
                    f"On-camera segment {tag}/{index} ({duration:.2f}s) needs "
                    f"{required_source_frames} source frames, but {look['id']} has "
                    f"only {source_frames} decoded frames ({source_duration:.2f}s). "
                    "Cannot proceed without source-frame looping. Keep each A-roll "
                    "below one 72-frame window."
                )
            seed = int(hashlib.sha256(job_id.encode()).hexdigest()[:8], 16) & 0x7FFFFFFF
            start_frame = seed % (max_start_frames + 1)
            audio = OUT / f"_tbdub_{job_id}.wav"
            output = OUT / f"_talk_{tag}_{index:02d}.mp4"
            _run([
                "ffmpeg", "-y", "-v", "error",
                "-ss", f"{float(segment['t0']):.3f}",
                "-t", f"{duration:.3f}",
                "-i", str(Path(voices[tag]).resolve()),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                audio.name,
            ], cwd=OUT)
            if not audio.is_file() or audio.stat().st_size < 1000:
                raise RuntimeError(f"Could not extract narration audio for TBDub segment {job_id}")
            cache = OUT / "_tbdub_cache" / f"{look['id']}.pkl"
            report = OUT / f"_tbdub_face_{look['id']}.json"
            jobs.append({
                "id": job_id, "tag": tag, "index": index,
                "video": source, "audio": audio,
                "output": output, "seed": seed, "start_frame": start_frame,
                "preprocess_cache": cache, "preprocess_report": report,
            })
    return jobs
