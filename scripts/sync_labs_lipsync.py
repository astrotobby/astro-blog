"""Managed Sync Labs lip-sync adapter.

Inference runs on Sync Labs' hosted service; no local CUDA, model checkpoint or GPU
runner is required. Production calls are guarded by a user-set maximum spend.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import requests

from common import OUT, log

API_BASE = "https://api.sync.so"
MODEL = "sync-3"
MAX_UNIT_RATE_USD = 0.133  # upper end of the published Sync-3 per-second range
MAX_LOCAL_FILE_BYTES = 20 * 1024 * 1024
TERMINAL = {"COMPLETED", "NO_OP", "FAILED", "REJECTED"}
_RESERVED_USD = 0.0


def _api_key() -> str:
    value = os.environ.get("SYNC_API_KEY", "").strip()
    if not value:
        raise RuntimeError(
            "SYNC_API_KEY is missing. Create a free Sync Labs API key and add it "
            "as an Actions secret; the hosted API does not need a local GPU."
        )
    return value


def _max_spend() -> float:
    raw = os.environ.get("SYNC_LABS_MAX_SPEND_USD_PER_RUN", "0").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("SYNC_LABS_MAX_SPEND_USD_PER_RUN must be a number.") from exc
    if value < 0:
        raise RuntimeError("SYNC_LABS_MAX_SPEND_USD_PER_RUN cannot be negative.")
    return value


def _duration(path: Path) -> float:
    result = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        text=True,
    ).strip()
    return float(result)


def preflight(cfg: dict, looks: list[dict]) -> bool:
    """Validate API credentials, budget authorization and source clips without billing."""
    _api_key()
    budget = _max_spend()
    if budget <= 0:
        raise RuntimeError(
            "Paid Sync-3 production is disabled because "
            "SYNC_LABS_MAX_SPEND_USD_PER_RUN is 0 or unset. No API generation "
            "was submitted. Use the manual Sync-3 free-trial smoke-test workflow "
            "for one preview, or set an explicit per-run spending ceiling."
        )

    inf = cfg.get("influencer", {})
    model = str(inf.get("sync_labs", {}).get("model", MODEL))
    if model != MODEL:
        raise RuntimeError(f"Unsupported Sync Labs production model {model!r}; expected {MODEL!r}.")

    for look in looks:
        clip = look.get("clip")
        if not clip or not Path(clip).is_file():
            raise RuntimeError(f"Sync Labs requires an existing Kling video for look {look.get('id')}.")
        path = Path(clip)
        if path.stat().st_size > MAX_LOCAL_FILE_BYTES:
            raise RuntimeError(
                f"Sync Labs input {path.name} exceeds the safe 20 MB upload limit."
            )
        seconds = _duration(path)
        if seconds <= 0 or seconds > 15.0:
            raise RuntimeError(
                f"Sync-3 free-trial-compatible source shots must be 0-15 seconds; "
                f"{path.name} is {seconds:.2f}s."
            )
    log(
        f"Sync Labs preflight passed (hosted {MODEL}; no local GPU required; "
        f"per-run spend ceiling ${budget:.2f})."
    )
    return True


def _post_generation(video: Path, audio: Path, job_id: str, model: str) -> dict:
    api_key = _api_key()
    for path in (video, audio):
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size > MAX_LOCAL_FILE_BYTES:
            raise RuntimeError(
                f"Sync Labs input {path.name} exceeds the safe 20 MB upload limit."
            )

    key_material = hashlib.sha256(
        f"{model}|{job_id}|{video.stat().st_size}|{audio.stat().st_size}|"
        f"{video.name}|{audio.name}".encode()
    ).hexdigest()
    headers = {
        "x-api-key": api_key,
        "Idempotency-Key": key_material,
    }
    data = {
        "model": model,
        "outputFileName": f"presenter_{job_id}",
    }
    log(f"Sync Labs: submitting {job_id} to {model}")
    with video.open("rb") as video_file, audio.open("rb") as audio_file:
        files = {
            "video": (video.name, video_file, "video/mp4"),
            "audio": (audio.name, audio_file, "audio/wav"),
        }
        response = requests.post(
            f"{API_BASE}/v2/generate",
            headers=headers,
            data=data,
            files=files,
            timeout=(30, 180),
        )
    if response.status_code >= 400:
        detail = response.text[:1200]
        if response.status_code == 402:
            raise RuntimeError(
                "Sync Labs rejected the request for billing/plan reasons (HTTP 402). "
                "The budget guard did not authorize a fallback provider. " + detail
            )
        if response.status_code == 429:
            raise RuntimeError(
                "Sync Labs rate or concurrency limit reached (HTTP 429). "
                "No unsynchronized footage will be substituted. " + detail
            )
        raise RuntimeError(
            f"Sync Labs generation request failed (HTTP {response.status_code}): {detail}"
        )
    payload = response.json()
    if not payload.get("id"):
        raise RuntimeError("Sync Labs accepted no generation ID: " + response.text[:1000])
    return payload


def _wait_for_generation(generation_id: str, timeout_seconds: int = 900) -> dict:
    headers = {"x-api-key": _api_key()}
    deadline = time.monotonic() + timeout_seconds
    last = {}
    while time.monotonic() < deadline:
        response = requests.get(
            f"{API_BASE}/v2/generate/{generation_id}",
            headers=headers,
            params={"wait": "true", "timeout": "10"},
            timeout=(20, 30),
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Sync Labs status check failed (HTTP {response.status_code}): "
                f"{response.text[:1000]}"
            )
        last = response.json()
        status = str(last.get("status", "")).upper()
        if status in TERMINAL:
            if status != "COMPLETED":
                raise RuntimeError(
                    f"Sync Labs generation {generation_id} ended as {status}: "
                    f"{last.get('error') or last.get('errorCode') or 'no details'}"
                )
            return last
    raise TimeoutError(
        f"Sync Labs generation {generation_id} did not finish within "
        f"{timeout_seconds}s; latest state: {str(last)[:800]}"
    )


def _download_output(url: str, output: Path) -> Path:
    if not url.startswith("https://"):
        raise RuntimeError("Sync Labs returned a non-HTTPS output URL; refusing the download.")
    output.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, stream=True, timeout=(30, 180))
    response.raise_for_status()
    temporary = output.with_suffix(output.suffix + ".part")
    with temporary.open("wb") as target:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                target.write(chunk)
    if not temporary.is_file() or temporary.stat().st_size < 10_000:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Sync Labs returned an empty or unusable video file.")
    temporary.replace(output)
    return output


def generate_one(video: Path, audio: Path, output: Path, job_id: str, model: str = MODEL) -> Path:
    """Create, poll and download one hosted lip-sync generation."""
    created = _post_generation(video, audio, job_id, model)
    generation_id = str(created["id"])
    log(f"Sync Labs generation accepted: {generation_id}")
    finished = _wait_for_generation(generation_id)
    url = finished.get("outputUrl") or finished.get("output_url")
    if not url:
        raise RuntimeError(
            f"Sync Labs marked {generation_id} complete but returned no outputUrl."
        )
    _download_output(str(url), output)

    target_duration = _duration(audio)
    output_duration = _duration(output)
    if abs(output_duration - target_duration) > 0.50:
        output.unlink(missing_ok=True)
        raise RuntimeError(
            f"Sync Labs output duration {output_duration:.2f}s does not match "
            f"the {target_duration:.2f}s narration excerpt."
        )
    log(
        f"Sync Labs output verified: {output.name}, {output_duration:.2f}s, "
        f"{output.stat().st_size} bytes."
    )
    return output


def generate_batch(jobs: list[dict], cfg: dict) -> dict[str, Path]:
    """Process each presenter segment independently after reserving the complete run budget."""
    global _RESERVED_USD
    if not jobs:
        return {}

    budget = _max_spend()
    model_cfg = cfg.get("influencer", {}).get("sync_labs", {})
    model = str(model_cfg.get("model", MODEL))
    if model != MODEL:
        raise RuntimeError(f"Unsupported Sync Labs model {model!r}.")

    estimate = sum(_duration(Path(job["audio"])) for job in jobs) * MAX_UNIT_RATE_USD
    remaining = budget - _RESERVED_USD
    if budget <= 0 or estimate > remaining + 0.0001:
        raise RuntimeError(
            f"Sync Labs spend guard blocked this batch before any API request: "
            f"estimated upper-bound ${estimate:.2f}, remaining authorized "
            f"budget ${max(0.0, remaining):.2f}. Increase "
            "SYNC_LABS_MAX_SPEND_USD_PER_RUN only after approving the cost."
        )
    _RESERVED_USD += estimate
    log(
        f"Sync Labs budget reserved: ${estimate:.2f} upper bound; "
        f"${_RESERVED_USD:.2f}/${budget:.2f} reserved this workflow run."
    )

    outputs = {}
    for job in jobs:
        output = generate_one(
            Path(job["video"]),
            Path(job["audio"]),
            Path(job["output"]),
            str(job["id"]),
            model=model,
        )
        outputs[str(job["id"])] = output

    expected = {str(job["id"]) for job in jobs}
    if set(outputs) != expected:
        raise RuntimeError(
            f"Sync Labs returned {len(outputs)} of {len(expected)} expected presenter segments."
        )
    return outputs


def build_jobs(plans: dict, voices: dict) -> list[dict]:
    """Extract one narration excerpt per A-roll cut; never concatenate disjoint audio."""
    jobs = []
    for tag, segments in plans.items():
        for index, segment in enumerate(segments):
            if segment.get("kind") != "A":
                continue
            look = segment.get("look") or {}
            source = look.get("clip")
            if not source or not Path(source).is_file():
                raise RuntimeError(
                    f"Sync Labs requires an existing Kling video for look {look.get('id')}."
                )
            audio = OUT / f"_sync_labs_{tag}_{index:02d}.wav"
            output = OUT / f"_talk_{tag}_{index:02d}.mp4"
            duration = float(segment["t1"] - segment["t0"])
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-ss", f"{float(segment['t0']):.3f}",
                    "-t", f"{duration:.3f}",
                    "-i", str(Path(voices[tag]).resolve()),
                    "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                    str(audio),
                ],
                cwd=str(OUT),
                check=True,
            )
            if not audio.is_file() or audio.stat().st_size < 1000:
                raise RuntimeError(
                    f"Could not extract narration excerpt for Sync Labs segment {tag}/{index}."
                )
            audio_duration = _duration(audio)
            if audio_duration <= 0 or audio_duration > 15.0:
                raise RuntimeError(
                    f"Sync-3 free-trial input limit is 15 seconds; segment {tag}/{index} "
                    f"is {audio_duration:.2f}s."
                )
            jobs.append({
                "id": f"{tag}_{index:02d}",
                "tag": tag,
                "index": index,
                "video": Path(source),
                "audio": audio,
                "output": output,
            })
    return jobs


def reset_run_budget_for_tests() -> None:
    """Reset in-memory spend tracking for isolated tests only."""
    global _RESERVED_USD
    _RESERVED_USD = 0.0
