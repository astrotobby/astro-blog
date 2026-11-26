#!/usr/bin/env python3
"""Run MuseTalk 1.5 on Kaggle's free GPU for a private batch of presenter clips.

The input videos and narration are uploaded only to a private Kaggle Dataset.
The notebook is private, uses a free NvidiaTeslaT4 request, and loads MuseTalk
once for up to four presenter/audio pairs. No paid fallback is permitted.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "musetalk_free_kaggle_test.ipynb"
MAX_TASKS = 4
KAGGLE_TIMEOUT = 120 * 60
STATUS_INTERVAL = 60
OUTPUT_COOLDOWN = 90


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 300,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["kaggle", *args]
    print("$ " + " ".join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.stdout:
        print(result.stdout[-6000:], flush=True)
    if result.returncode and result.stderr:
        print(result.stderr[-6000:], file=sys.stderr, flush=True)
    if check and result.returncode:
        raise RuntimeError(
            f"Kaggle command failed (exit {result.returncode}): "
            + " ".join(command[:3])
        )
    return result


def _username() -> str:
    configured = os.environ.get("KAGGLE_USERNAME", "").strip()
    if configured:
        username = configured.lower()
    else:
        # Do not route config-view output through the normal command logger:
        # some Kaggle CLI versions display credential fields in this response.
        result = subprocess.run(
            ["kaggle", "config", "view"],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError("Kaggle CLI could not read its authenticated account configuration.")
        match = re.search(
            r"(?im)^\s*-?\s*username\s*:\s*([^\s]+)",
            result.stdout,
        )
        if not match:
            raise RuntimeError(
                "Kaggle authenticated, but the CLI did not expose the account username. "
                "Set KAGGLE_USERNAME as a GitHub Actions variable for the Kaggle account."
            )
        username = match.group(1).strip("\"'").lower()
    if not re.fullmatch(r"[a-z0-9_-]+", username):
        raise RuntimeError("Kaggle returned an invalid account username.")
    return username


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(f"ffprobe could not read MuseTalk output {path.name}.")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    types = {stream.get("codec_type") for stream in streams}
    duration = float((data.get("format") or {}).get("duration") or 0)
    if not {"audio", "video"}.issubset(types):
        raise RuntimeError(
            f"MuseTalk output {path.name} must contain audio and video; got {sorted(types)}."
        )
    if duration < 1.0 or path.stat().st_size < 100_000:
        raise RuntimeError(
            f"MuseTalk output {path.name} is incomplete ({duration:.2f}s, {path.stat().st_size} bytes)."
        )
    video = next(stream for stream in streams if stream.get("codec_type") == "video")
    return {
        "bytes": path.stat().st_size,
        "duration_seconds": duration,
        "resolution": f"{video.get('width')}x{video.get('height')}",
        "streams": sorted(types),
    }


def _wait_for_dataset(dataset_id: str, expected_names: set[str]) -> None:
    for attempt in range(1, 31):
        result = _run(["datasets", "files", dataset_id, "--page-size", "100"],
                      timeout=90, check=False)
        visible = result.stdout + "\n" + result.stderr
        if result.returncode == 0 and all(name in visible for name in expected_names):
            print(f"Private Kaggle input dataset is ready: {dataset_id}", flush=True)
            return
        if result.returncode and not re.search(
            r"429|too many requests|rate.?limit", visible, re.I
        ):
            raise RuntimeError("Kaggle could not list the private input dataset.")
        print(f"Waiting for private Kaggle dataset publication ({attempt}/30).", flush=True)
        time.sleep(10)
    raise TimeoutError("Kaggle did not publish all private input files within five minutes.")


def _wait_for_kernel(kernel_id: str) -> None:
    max_polls = max(1, KAGGLE_TIMEOUT // STATUS_INTERVAL)
    for attempt in range(1, max_polls + 1):
        result = _run(["kernels", "status", kernel_id], timeout=90, check=False)
        status = (result.stdout + "\n" + result.stderr).strip()
        if result.returncode:
            if re.search(r"429|too many requests|rate.?limit", status, re.I):
                print(f"Kaggle status is rate-limited; pausing {STATUS_INTERVAL}s.", flush=True)
                time.sleep(STATUS_INTERVAL)
                continue
            raise RuntimeError(f"Kaggle kernel status request failed: {status[:800]}")
        print(f"MuseTalk GPU kernel status ({attempt}/{max_polls}): {status}", flush=True)
        if re.search(r"\bcomplete\b", status, re.I):
            print(f"MuseTalk kernel completed: https://www.kaggle.com/code/{kernel_id}", flush=True)
            return
        if re.search(r"\b(error|failed|cancelled)\b", status, re.I):
            logs = _run(["kernels", "logs", kernel_id], timeout=120, check=False)
            raise RuntimeError(
                "MuseTalk Kaggle kernel failed. Recent logs:\n"
                + (logs.stdout + "\n" + logs.stderr)[-12000:]
            )
        time.sleep(STATUS_INTERVAL)
    raise TimeoutError(
        f"MuseTalk GPU kernel did not complete within {KAGGLE_TIMEOUT // 60} minutes. "
        "No paid GPU or unsynchronized fallback was attempted."
    )


def _download_outputs(kernel_id: str, filenames: set[str], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    # One targeted output request after an indexing cooldown avoids aggressive
    # repeated polling of Kaggle's session-output endpoint.
    for attempt, delay in ((1, OUTPUT_COOLDOWN), (2, 240)):
        print(f"Waiting {delay}s before fetching the rendered MP4 batch (attempt {attempt}/2).",
              flush=True)
        time.sleep(delay)
        log_path = destination / f"kaggle-output-attempt-{attempt}.log"
        result = _run(
            [
                "kernels", "output", kernel_id,
                "--path", str(destination),
                "--file-pattern", r".*musetalk_preview_[0-9]+\.mp4$",
                "--page-size", "200",
            ],
            timeout=240,
            check=False,
        )
        log_path.write_text(
            (result.stdout or "") + "\n" + (result.stderr or ""),
            encoding="utf-8",
        )
        if result.returncode == 0:
            break
        message = result.stdout + "\n" + result.stderr
        if not re.search(r"429|too many requests|rate.?limit", message, re.I):
            raise RuntimeError("Kaggle completed inference but did not return the MP4 outputs.")
    else:
        raise RuntimeError(
            "MuseTalk GPU inference completed, but Kaggle rate-limited the output download. "
            f"The private notebook is preserved at https://www.kaggle.com/code/{kernel_id}."
        )

    for filename in filenames:
        matches = [p for p in destination.rglob(filename) if p.is_file() and p.stat().st_size > 100_000]
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one downloaded {filename}, found {len(matches)}. "
                f"Notebook: https://www.kaggle.com/code/{kernel_id}"
            )
        target = destination / filename
        if matches[0].resolve() != target.resolve():
            shutil.copy2(matches[0], target)
        _probe(target)


def generate_batch(tasks: list[dict[str, Any]], output_dir: Path | None = None) -> dict[str, Path]:
    """Run the supplied presenter/audio pairs as one private Kaggle GPU job.

    Each task must include id, video, audio, and output paths. The return value
    maps the id back to its validated, audio-bearing MuseTalk 1.5 MP4.
    """
    token = os.environ.get("KAGGLE_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "MuseTalk production lip-sync is selected, but KAGGLE_API_TOKEN is missing. "
            "Add the same Kaggle token as an Actions secret in astrotobby/AI-GEMS "
            "(Settings → Secrets and variables → Actions). Do not paste it into chat. "
            "The pipeline will not silently fall back to unsynchronized or Wav2Lip footage."
        )
    if not NOTEBOOK.is_file():
        raise RuntimeError(f"MuseTalk Kaggle notebook is missing: {NOTEBOOK}")
    if not tasks or len(tasks) > MAX_TASKS:
        raise ValueError(f"MuseTalk batch must contain 1–{MAX_TASKS} tasks.")

    clean_tasks: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        task_id = str(task.get("id") or f"look_{index}")
        video = Path(task["video"]).resolve()
        audio = Path(task["audio"]).resolve()
        output = Path(task["output"]).resolve()
        if not video.is_file() or not audio.is_file():
            raise FileNotFoundError(f"MuseTalk presenter/audio input is missing for {task_id}.")
        if output.suffix.lower() != ".mp4":
            raise ValueError(f"MuseTalk output for {task_id} must be an MP4.")
        clean_tasks.append({
            "id": task_id,
            "video": video,
            "audio": audio,
            "output": output,
        })

    run_slug = uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix="musetalk-batch-") as temporary:
        temp_root = Path(temporary)
        dataset_dir = temp_root / "dataset"
        kernel_dir = temp_root / "kernel"
        downloads = temp_root / "downloads"
        dataset_dir.mkdir()
        kernel_dir.mkdir()
        downloads.mkdir()

        owner = _username()
        dataset_slug = f"musetalk-input-{run_slug}"
        kernel_slug = f"musetalk-batch-{run_slug}"
        dataset_id = f"{owner}/{dataset_slug}"
        kernel_id = f"{owner}/{kernel_slug}"

        manifest_tasks = []
        expected_files: set[str] = {"musetalk_manifest.json"}
        output_map: dict[str, Path] = {}
        for index, task in enumerate(clean_tasks):
            video_name = f"presenter_{index}.mp4"
            audio_name = f"narration_{index}{task['audio'].suffix.lower()}"
            result_name = f"musetalk_preview_{index}.mp4"
            shutil.copy2(task["video"], dataset_dir / video_name)
            shutil.copy2(task["audio"], dataset_dir / audio_name)
            manifest_tasks.append({
                "video": video_name,
                "audio": audio_name,
                "result_name": result_name,
            })
            expected_files.update({video_name, audio_name})
            output_map[task["id"]] = task["output"]

        manifest_path = dataset_dir / "musetalk_manifest.json"
        manifest_path.write_text(
            json.dumps({"tasks": manifest_tasks}, indent=2),
            encoding="utf-8",
        )
        (dataset_dir / "dataset-metadata.json").write_text(
            json.dumps({
                "title": f"Private MuseTalk inputs {run_slug}",
                "id": dataset_id,
                "licenses": [{"name": "other"}],
                "description": "Private presenter/audio input pairs for owner-approved MuseTalk lip-sync. Not for redistribution.",
            }, indent=2),
            encoding="utf-8",
        )

        print(f"Creating private Kaggle input dataset {dataset_id}.", flush=True)
        _run(["datasets", "create", "-p", str(dataset_dir)], timeout=900)
        _wait_for_dataset(dataset_id, expected_files)

        shutil.copy2(NOTEBOOK, kernel_dir / "musetalk_free_kaggle_test.ipynb")
        (kernel_dir / "kernel-metadata.json").write_text(
            json.dumps({
                "id": kernel_id,
                "title": f"Private MuseTalk batch {run_slug}",
                "code_file": "musetalk_free_kaggle_test.ipynb",
                "language": "python",
                "kernel_type": "notebook",
                "is_private": "true",
                "enable_gpu": "true",
                "enable_internet": "true",
                "machine_shape": "NvidiaTeslaT4",
                "dataset_sources": [dataset_id],
            }, indent=2),
            encoding="utf-8",
        )

        print("Submitting private MuseTalk 1.5 notebook with free NvidiaTeslaT4 request.", flush=True)
        _run(["kernels", "push", "-p", str(kernel_dir), "--accelerator", "NvidiaTeslaT4"],
             timeout=900)

        metadata_dir = temp_root / "metadata"
        metadata_dir.mkdir()
        _run(["kernels", "pull", kernel_id, "-p", str(metadata_dir), "-m"], timeout=120)
        metadata = json.loads((metadata_dir / "kernel-metadata.json").read_text(encoding="utf-8"))
        if str(metadata.get("enable_gpu", "")).lower() != "true":
            raise RuntimeError("Kaggle did not persist enable_gpu=true.")
        if metadata.get("machine_shape") != "NvidiaTeslaT4":
            raise RuntimeError("Kaggle did not persist the free NvidiaTeslaT4 request.")
        if dataset_id not in metadata.get("dataset_sources", []):
            raise RuntimeError("Kaggle did not attach the private presenter/audio dataset.")

        _wait_for_kernel(kernel_id)
        expected_outputs = {f"musetalk_preview_{index}.mp4" for index in range(len(clean_tasks))}
        _download_outputs(kernel_id, expected_outputs, downloads)

        for index, task in enumerate(clean_tasks):
            filename = f"musetalk_preview_{index}.mp4"
            downloaded = downloads / filename
            destination = task["output"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(downloaded, destination)
            result = _probe(destination)
            print(json.dumps({
                "task_id": task["id"],
                "output": str(destination),
                "kernel": kernel_id,
                "media": result,
            }, indent=2), flush=True)

        print(f"MuseTalk batch complete: https://www.kaggle.com/code/{kernel_id}", flush=True)
        return {task["id"]: task["output"] for task in clean_tasks}
