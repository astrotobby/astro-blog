#!/usr/bin/env python3
"""Run MuseTalk 1.5 on Kaggle's free GPU for a private batch of presenter clips.

The input videos and narration are uploaded only to a private Kaggle Dataset.
The notebook is private, uses a free NvidiaTeslaT4 request, and loads MuseTalk
once for up to four presenter/audio pairs. No paid fallback is permitted.
"""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
import time
import uuid
from pathlib import Path

import requests
from typing import Any

from musetalk_output_relay import OutputRelay

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "musetalk_free_kaggle_test.ipynb"
MAX_TASKS = 4
KAGGLE_TIMEOUT = 120 * 60
STATUS_INTERVAL = 60
OUTPUT_COOLDOWN = 90
MUSE_TALK_INPUT_FPS = 25


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
    rate_text = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    try:
        frame_rate = Fraction(rate_text)
    except (ValueError, ZeroDivisionError):
        frame_rate = Fraction(0, 1)
    expected_rate = Fraction(MUSE_TALK_INPUT_FPS, 1)
    if frame_rate != expected_rate:
        raise RuntimeError(
            f"MuseTalk output {path.name} must preserve the preview cadence "
            f"of {MUSE_TALK_INPUT_FPS} fps; got {rate_text}."
        )
    return {
        "bytes": path.stat().st_size,
        "duration_seconds": duration,
        "resolution": f"{video.get('width')}x{video.get('height')}",
        "fps": float(frame_rate),
        "streams": sorted(types),
    }


def _wait_for_dataset(dataset_id: str, expected_names: set[str]) -> None:
    """Wait for Kaggle private dataset indexing after create and upload.

    Kaggle can report a dataset as still being created while its files endpoint
    temporarily responds with 403/404. Since create and the file uploads already
    succeeded, retry these visibility responses with a bounded wait. Preserve any
    final response to make persistent permission failures diagnosable.
    """
    last_response = ""
    for attempt in range(1, 31):
        result = _run(
            ["datasets", "files", dataset_id, "--page-size", "100"],
            timeout=90,
            check=False,
        )
        visible = (result.stdout or "") + "\n" + (result.stderr or "")
        last_response = visible.strip()[-1000:]
        if result.returncode == 0 and all(name in visible for name in expected_names):
            print(f"Private Kaggle input dataset is ready: {dataset_id}", flush=True)
            return
        transient_visibility = bool(re.search(
            r"429|too many requests|rate.?limit|403|forbidden|"
            r"you do not have access|you don't have access|404|not found|"
            r"still being created|being created",
            visible,
            re.I,
        ))
        if result.returncode and not transient_visibility:
            raise RuntimeError(
                "Kaggle could not list the private input dataset. "
                f"Response: {last_response[:500]}"
            )
        print(
            f"Private Kaggle dataset is not fully visible yet ({attempt}/30); retrying shortly.",
            flush=True,
        )
        time.sleep(10)
    raise TimeoutError(
        "Kaggle did not make all private input files visible within five minutes. "
        f"Last response: {last_response[:700]}"
    )


def _wait_for_kernel(kernel_id: str, *, relay_available: bool = False) -> bool:
    max_polls = max(1, KAGGLE_TIMEOUT // STATUS_INTERVAL)
    for attempt in range(1, max_polls + 1):
        result = _run(["kernels", "status", kernel_id], timeout=90, check=False)
        status = (result.stdout + "\n" + result.stderr).strip()
        if result.returncode:
            if re.search(r"429|too many requests|rate.?limit", status, re.I):
                print(f"Kaggle status is rate-limited; pausing {STATUS_INTERVAL}s.", flush=True)
                time.sleep(STATUS_INTERVAL)
                continue
            if re.search(
                r"kernels[.]get|permission.{0,40}(?:denied|forbidden)|"
                r"(?:403|forbidden).{0,40}kernels",
                status,
                re.I,
            ):
                if relay_available:
                    print(
                        "Kaggle accepted the private MuseTalk kernel push, but its private "
                        "status endpoint denied metadata access. Using the run-scoped, "
                        "bearer-protected output relay as the completion signal.",
                        flush=True,
                    )
                else:
                    print(
                        "Kaggle accepted the private MuseTalk kernel push, but its private "
                        "status endpoint denied metadata access. Polling the exact private "
                        "notebook session outputs through Kaggle MCP instead; this path "
                        "does not call kernels.get.",
                        flush=True,
                    )
                return False
            raise RuntimeError(f"Kaggle kernel status request failed: {status[:800]}")
        print(f"MuseTalk GPU kernel status ({attempt}/{max_polls}): {status}", flush=True)
        if re.search(r"\bcomplete\b", status, re.I):
            print(f"MuseTalk kernel completed: https://www.kaggle.com/code/{kernel_id}", flush=True)
            return True
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


def _wait_for_session_outputs(
    kernel_id: str,
    filenames: set[str],
    destination: Path,
    *,
    timeout: int = KAGGLE_TIMEOUT,
) -> None:
    """Poll MuseTalk outputs, falling back from unavailable MCP to Kaggle CLI.

    Kaggle can accept a private notebook push while its MCP HTTP endpoint is
    unavailable to a runner. A transport-level 404 is not a missing output
    file: switch to the official `kaggle kernels output` command and keep
    polling until the exact expected MP4s arrive or the bounded job timeout
    expires. Every downloaded file must pass ffprobe before it is accepted.
    """
    from kaggle_mcp_download_output import download_output

    destination.mkdir(parents=True, exist_ok=True)
    missing = set(filenames)
    deadline = time.monotonic() + timeout
    attempt = 0
    use_cli = False

    while missing and time.monotonic() < deadline:
        attempt += 1

        if not use_cli:
            for filename in sorted(tuple(missing)):
                target = destination / filename
                try:
                    download_output(kernel_id, filename, target, session_only=True)
                    _probe(target)
                    missing.discard(filename)
                    print(
                        f"Kaggle session output received and validated: {filename}",
                        flush=True,
                    )
                except FileNotFoundError:
                    target.unlink(missing_ok=True)
                except requests.HTTPError as exc:
                    response = getattr(exc, "response", None)
                    status_code = getattr(response, "status_code", None)
                    if status_code == 404 or (isinstance(status_code, int) and status_code >= 500):
                        use_cli = True
                        target.unlink(missing_ok=True)
                        print(
                            f"Kaggle MCP returned HTTP {status_code}; switching to the "
                            "official Kaggle CLI output downloader.",
                            file=sys.stderr,
                            flush=True,
                        )
                        break
                    raise RuntimeError(
                        "Kaggle MCP output access was rejected with "
                        f"HTTP {status_code or 'an HTTP error'} for {filename}."
                    ) from exc
                except requests.RequestException as exc:
                    use_cli = True
                    target.unlink(missing_ok=True)
                    print(
                        "Kaggle MCP transport is unavailable; switching to the "
                        f"official Kaggle CLI output downloader ({type(exc).__name__}).",
                        file=sys.stderr,
                        flush=True,
                    )
                    break
                except RuntimeError as exc:
                    if re.search(r"429|too many requests|rate.?limit", str(exc), re.I):
                        print(
                            "Kaggle MCP output listing is rate-limited; "
                            f"retrying after {STATUS_INTERVAL}s.",
                            flush=True,
                        )
                        continue
                    if re.search(r"HTTP 404|not found.*mcp|mcp.*not found", str(exc), re.I):
                        use_cli = True
                        target.unlink(missing_ok=True)
                        print(
                            "Kaggle MCP endpoint is unavailable; switching to the "
                            "official Kaggle CLI output downloader.",
                            file=sys.stderr,
                            flush=True,
                        )
                        break
                    raise RuntimeError(
                        "Kaggle could not retrieve the private MuseTalk session output "
                        f"{filename}: {str(exc)[:700]}"
                    ) from exc

        if missing and use_cli:
            result = _run(
                [
                    "kernels", "output", kernel_id,
                    "--path", str(destination),
                    "--file-pattern", r".*musetalk_preview_[0-9]+\.mp4$",
                    "--page-size", "200",
                ],
                timeout=300,
                check=False,
            )
            message = (result.stdout or "") + "\n" + (result.stderr or "")
            if result.returncode and re.search(
                r"permission.{0,50}(?:denied|forbidden)|"
                r"(?:403|forbidden).{0,80}kernels|get.{0,30}denied",
                message,
                re.I,
            ):
                raise RuntimeError(
                    "Kaggle accepted the MuseTalk notebook, but this API token cannot "
                    "read notebook outputs. Regenerate the Kaggle token with notebook "
                    "read access (kernels.get) and update KAGGLE_API_TOKEN in the "
                    "AI-GEMS GitHub Actions secrets. Do not paste the token into chat. "
                    f"Private notebook: https://www.kaggle.com/code/{kernel_id}"
                )
            if result.returncode and not re.search(
                r"429|too many requests|rate.?limit|404|not found|"
                r"no output|not available|still running",
                message,
                re.I,
            ):
                raise RuntimeError(
                    "The official Kaggle CLI could not retrieve MuseTalk outputs: "
                    f"{message[-1200:]}"
                )

            for filename in sorted(tuple(missing)):
                matches = [
                    candidate
                    for candidate in destination.rglob(filename)
                    if candidate.is_file() and candidate.stat().st_size >= 100_000
                ]
                if len(matches) > 1:
                    raise RuntimeError(
                        f"Expected one Kaggle output named {filename}, found {len(matches)}. "
                        "Refusing to choose an ambiguous video."
                    )
                if not matches:
                    continue
                target = destination / filename
                if matches[0].resolve() != target.resolve():
                    shutil.copy2(matches[0], target)
                _probe(target)
                missing.discard(filename)
                print(
                    f"Kaggle CLI output received and validated: {filename}",
                    flush=True,
                )

        if missing:
            print(
                f"Waiting for private Kaggle MuseTalk output ({attempt}): "
                f"{len(missing)} file(s) still pending via "
                f"{'Kaggle CLI' if use_cli else 'MCP session output'}.",
                flush=True,
            )
            time.sleep(STATUS_INTERVAL)

    if missing:
        raise TimeoutError(
            f"Kaggle did not expose the MuseTalk output file(s) within "
            f"{timeout // 60} minutes: {', '.join(sorted(missing))}. "
            f"Private notebook: https://www.kaggle.com/code/{kernel_id}"
        )


def _download_outputs(kernel_id: str, filenames: set[str], destination: Path) -> None:
    """Fetch only the result files that the private relay did not already return."""
    destination.mkdir(parents=True, exist_ok=True)
    missing = set()
    for filename in filenames:
        local = destination / filename
        if local.is_file():
            try:
                _probe(local)
                continue
            except Exception:
                local.unlink(missing_ok=True)
        missing.add(filename)
    if not missing:
        return

    # The direct per-file MCP route first tries Kaggle's session-output listing,
    # avoiding the older kernels.get metadata permission that failed on preview #53.
    # If that route is denied/unavailable, use the official CLI after a cooldown.
    try:
        from kaggle_mcp_download_output import download_output
    except ImportError as exc:
        print(f"Kaggle MCP downloader helper unavailable: {exc}", file=sys.stderr)
        download_output = None

    if download_output is not None:
        for filename in sorted(tuple(missing)):
            target = destination / filename
            try:
                download_output(kernel_id, filename, target)
                _probe(target)
                missing.discard(filename)
            except Exception as exc:  # noqa - CLI remains a supported fallback
                print(
                    f"Direct Kaggle MCP download unavailable for {filename}: "
                    f"{str(exc)[:300]}; will try the official CLI.",
                    file=sys.stderr,
                    flush=True,
                )
                target.unlink(missing_ok=True)

    if missing:
        # One targeted batch request after a cooldown is less likely to hit
        # Kaggle's session-output rate limit than polling/listing repeatedly.
        for attempt, delay in ((1, OUTPUT_COOLDOWN), (2, 240)):
            print(
                f"Waiting {delay}s before Kaggle CLI output retrieval "
                f"(attempt {attempt}/2).",
                flush=True,
            )
            time.sleep(delay)
            result = _run(
                [
                    "kernels", "output", kernel_id,
                    "--path", str(destination),
                    "--file-pattern", r".*musetalk_preview_[0-9]+\.mp4$",
                    "--page-size", "200",
                ],
                timeout=300,
                check=False,
            )
            message = (result.stdout or "") + "\n" + (result.stderr or "")
            if result.returncode == 0:
                break
            if not re.search(r"429|too many requests|rate.?limit", message, re.I):
                raise RuntimeError(
                    "MuseTalk inference completed, but Kaggle did not return the "
                    f"requested MP4 files. Recent response: {message[-1200:]}"
                )
            if attempt == 2:
                raise RuntimeError(
                    "MuseTalk GPU inference completed, but Kaggle rate-limited the "
                    "output download. The private notebook is preserved at "
                    f"https://www.kaggle.com/code/{kernel_id}."
                )

        for filename in sorted(missing):
            matches = [
                output_path for output_path in destination.rglob(filename)
                if output_path.is_file() and output_path.stat().st_size > 100_000
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    f"Expected one downloaded {filename}, found {len(matches)}. "
                    f"Private notebook: https://www.kaggle.com/code/{kernel_id}"
                )
            target = destination / filename
            if matches[0].resolve() != target.resolve():
                shutil.copy2(matches[0], target)
            _probe(target)
            missing.discard(filename)

    if missing:
        raise RuntimeError(
            "MuseTalk batch output collection is incomplete: "
            + ", ".join(sorted(missing))
        )


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

        expected_outputs = {item["result_name"] for item in manifest_tasks}
        relay = OutputRelay(expected_outputs, downloads)
        relay_config = None
        try:
            relay_config = relay.start_quick_tunnel(temp_root / "cloudflared")
            # The server and random bearer token are per-run only. The callback
            # is stored in the private Kaggle input dataset and is never logged.
            atexit.register(relay.close)
            print(
                "Temporary private output relay active for this one render; "
                "Kaggle CLI remains the fallback if transfer fails.",
                flush=True,
            )
        except Exception as exc:  # noqa - keep the supported CLI output fallback
            relay.close()
            relay = None
            print(
                f"Temporary output relay could not start ({str(exc)[:220]}); "
                "will use the Kaggle output API fallback.",
                file=sys.stderr,
                flush=True,
            )

        manifest_payload = {"tasks": manifest_tasks}
        if relay_config:
            manifest_payload["return"] = relay_config
        manifest_path = dataset_dir / "musetalk_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest_payload, indent=2),
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

        # Validate the exact metadata submitted locally. Kaggle's kernels.push
        # already confirms that version 1 was accepted; kernels.pull -m calls
        # GetKernel metadata and can return a spurious 403 for newly-created
        # private kernels even when the owner just pushed them successfully.
        submitted_metadata = json.loads(
            (kernel_dir / "kernel-metadata.json").read_text(encoding="utf-8")
        )
        if str(submitted_metadata.get("enable_gpu", "")).lower() != "true":
            raise RuntimeError("Submitted Kaggle metadata does not enable the free GPU.")
        if submitted_metadata.get("machine_shape") != "NvidiaTeslaT4":
            raise RuntimeError("Submitted Kaggle metadata is not the free NvidiaTeslaT4 request.")
        if dataset_id not in submitted_metadata.get("dataset_sources", []):
            raise RuntimeError("Submitted Kaggle metadata does not attach the private input dataset.")
        print(
            "Local Kaggle metadata validated; skipping private GetKernel pull "
            "that previously returned 403 after a successful push.",
            flush=True,
        )

        kernel_status_completed = _wait_for_kernel(kernel_id, relay_available=relay is not None)
        expected_outputs = {f"musetalk_preview_{index}.mp4" for index in range(len(clean_tasks))}

        relay_delivered = False
        if relay is not None:
            # MuseTalk setup and T4 inference can take several minutes. When
            # Kaggle hides private kernel status metadata, the signed relay is the
            # authoritative completion signal and must be allowed the full job window.
            relay_delivered = relay.wait_for_outputs(expected_outputs, timeout=KAGGLE_TIMEOUT)
            if relay_delivered:
                for filename in sorted(expected_outputs):
                    _probe(downloads / filename)
                print(
                    f"Private output relay received all {len(expected_outputs)} MP4 file(s).",
                    flush=True,
                )
            else:
                print(
                    "Private output relay did not receive every MP4; "
                    "trying the Kaggle exact-file/CLI download fallback.",
                    file=sys.stderr,
                    flush=True,
                )
        if not relay_delivered:
            if relay is None and not kernel_status_completed:
                _wait_for_session_outputs(kernel_id, expected_outputs, downloads)
            else:
                _download_outputs(kernel_id, expected_outputs, downloads)

        if relay is not None:
            relay.close()
            atexit.unregister(relay.close)

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
