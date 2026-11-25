#!/usr/bin/env python3
"""Persistent TBDub Student worker: load the model once, sync each A-roll independently.

The worker is intentionally fail-closed. It requires a CUDA GPU and never substitutes
Wav2Lip, a still, or unsynchronized footage when TBDub cannot run.
"""
from __future__ import annotations

import argparse
import gc
import json
import pickle
import shutil
import subprocess
import sys
from pathlib import Path


GIB = 1024 ** 3
MIN_GPU_TOTAL = 16 * GIB
MIN_GPU_FREE = 15 * GIB
MIN_RAM_TOTAL = 24 * GIB
MIN_RAM_AVAILABLE = 21 * GIB


def _ram_bytes():
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(value.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return None, None
    return values.get("MemTotal"), values.get("MemAvailable")


def _required_model_files(checkpoint_dir: Path):
    return [
        checkpoint_dir / "config.json",
        checkpoint_dir / "tbdub_student.safetensors",
        checkpoint_dir / "Wan2.2_VAE.safetensors",
        checkpoint_dir / "null_prompt_emb.pt",
        checkpoint_dir / "hubert-large-ll60k" / "config.json",
        checkpoint_dir / "hubert-large-ll60k" / "preprocessor_config.json",
        checkpoint_dir / "hubert-large-ll60k" / "pytorch_model.bin",
        checkpoint_dir / "face_landmarker.task",
    ]


def _check_runtime(checkpoint_dir: Path):
    import torch

    missing = [str(path) for path in _required_model_files(checkpoint_dir)
               if not path.is_file() or path.stat().st_size < 1024]
    if missing:
        raise RuntimeError("TBDub Student model files are missing or incomplete:\n  - "
                           + "\n  - ".join(missing))
    if not torch.cuda.is_available():
        raise RuntimeError("TBDub requires an NVIDIA CUDA GPU. No CUDA device is visible; "
                           "refusing to fall back to CPU or unsynchronized video.")
    props = torch.cuda.get_device_properties(0)
    total_vram = int(props.total_memory)
    free_vram, _ = torch.cuda.mem_get_info(0)
    if total_vram < MIN_GPU_TOTAL or free_vram < MIN_GPU_FREE:
        raise RuntimeError(
            f"TBDub Student CPU-offload needs a GPU with at least 16 GiB total and "
            f"about 15 GiB free. Detected {props.name}: "
            f"{total_vram / GIB:.2f} GiB total, {free_vram / GIB:.2f} GiB free."
        )
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError(f"{props.name} does not report BF16 support required by TBDub.")
    ram_total, ram_available = _ram_bytes()
    if ram_total is None or ram_total < MIN_RAM_TOTAL or ram_available < MIN_RAM_AVAILABLE:
        total_text = "unknown" if ram_total is None else f"{ram_total / GIB:.1f} GiB"
        free_text = "unknown" if ram_available is None else f"{ram_available / GIB:.1f} GiB"
        raise RuntimeError(
            "TBDub Student CPU-offload needs at least 24 GiB host RAM and about "
            f"21 GiB available. Detected {total_text} total / {free_text} available."
        )
    print(f"[TBDub] CUDA ready: {props.name}; {total_vram / GIB:.1f} GiB VRAM; "
          f"{ram_total / GIB:.1f} GiB host RAM", flush=True)


def _load_sample(core, job, args):
    video = str(Path(job["video"]).expanduser().resolve())
    audio = str(Path(job["audio"]).expanduser().resolve())
    args.video = video
    args.audio = audio
    args.preprocess_report = job.get("preprocess_report")
    cache = Path(job["preprocess_cache"]).expanduser().resolve() if job.get("preprocess_cache") else None

    if cache and cache.is_file():
        with cache.open("rb") as file:
            data = pickle.load(file)
        if (not isinstance(data, dict)
                or data.get("preprocess_backend") != "mediapipe"
                or data.get("preprocess_backend_revision") != core.PREPROCESS_REVISION):
            raise RuntimeError(f"Stale or untrusted TBDub preprocessing cache: {cache}")
        sample = core.PreprocessedSample(
            raw_video=data["raw_video"],
            reference_video=data["reference_video"],
            bboxes=data["bboxes"],
            audio_path=audio,
        )
        core.validate_sample(sample)
        return sample

    sample = core.preprocess_inputs(video, audio, args)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        temp = cache.with_suffix(cache.suffix + ".tmp")
        with temp.open("wb") as file:
            pickle.dump({
                "preprocess_backend": "mediapipe",
                "preprocess_backend_revision": core.PREPROCESS_REVISION,
                "raw_video": sample.raw_video,
                "reference_video": sample.reference_video,
                "bboxes": sample.bboxes,
            }, file, protocol=pickle.HIGHEST_PROTOCOL)
        temp.replace(cache)
    return sample


def run_batch(manifest_path: Path, tbdub_dir: Path, checkpoint_dir: Path):
    requests = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs = requests.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("TBDub batch manifest must contain at least one job.")
    for item in jobs:
        for key in ("id", "video", "audio", "output"):
            if not item.get(key):
                raise ValueError(f"TBDub job is missing {key}: {item}")
        for key in ("video", "audio"):
            if not Path(item[key]).is_file():
                raise FileNotFoundError(item[key])

    sys.path.insert(0, str(tbdub_dir.resolve()))
    import inference as core

    first = jobs[0]
    argv = [
        "--video", str(Path(first["video"]).resolve()),
        "--audio", str(Path(first["audio"]).resolve()),
        "--output-dir", str(Path(first["output"]).resolve().parent),
        "--checkpoint-dir", str(checkpoint_dir.resolve()),
        "--inference-mode", "student",
        "--num-student-steps", "2",
        "--sigma-shift", "1.0",
        "--motion-from-latents",
        "--cpu-offload",
        "--device", "cuda:0",
        "--seed", str(int(first.get("seed", 42))),
    ]
    args = core.parse_args(argv)
    _check_runtime(checkpoint_dir)
    pipeline, prompt_embedding = core.build_pipeline(args)
    results = []

    import torch
    for index, job in enumerate(jobs, start=1):
        sample_name = str(job["id"])
        output = Path(job["output"]).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        args.video = str(Path(job["video"]).expanduser().resolve())
        args.audio = str(Path(job["audio"]).expanduser().resolve())
        args.output_dir = str(output.parent)
        args.sample_name = sample_name
        args.start_frame = 0
        args.seed = int(job.get("seed", 42))
        args.save_comparison = bool(job.get("save_comparison", False))

        print(f"[TBDub] job {index}/{len(jobs)}: {sample_name}", flush=True)
        sample = _load_sample(core, job, args)
        with torch.inference_mode():
            generated = core.run_inference(pipeline, prompt_embedding, sample, sample_name, args)
        if not generated.is_file() or generated.stat().st_size < 10_000:
            raise RuntimeError(f"TBDub did not create a usable output for {sample_name}")
        if generated.resolve() != output:
            shutil.copy2(generated, output)
        if not output.is_file() or output.stat().st_size < 10_000:
            raise RuntimeError(f"TBDub output verification failed for {sample_name}")
        output_duration = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(output)
        ], text=True).strip())
        target_duration = float(core.get_audio_length(str(job["audio"])))
        if abs(output_duration - target_duration) > 0.20:
            raise RuntimeError(
                f"TBDub output length {output_duration:.3f}s does not match "
                f"its {target_duration:.3f}s narration for {sample_name}."
            )
        results.append({
            "id": sample_name, "output": str(output),
            "bytes": output.stat().st_size, "duration": output_duration,
        })
        print(f"[TBDub] completed {sample_name}: {output}", flush=True)
        del sample
        gc.collect()
        torch.cuda.empty_cache()

    result_path = manifest_path.with_suffix(".results.json")
    result_path.write_text(json.dumps({"jobs": results}, indent=2), encoding="utf-8")
    print(f"[TBDub] batch complete: {len(results)} segments", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--tbdub-dir", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if args.check_only:
        _check_runtime(args.checkpoint_dir)
        return
    if not args.manifest:
        parser.error("--manifest is required unless --check-only is set")
    run_batch(args.manifest, args.tbdub_dir, args.checkpoint_dir)


if __name__ == "__main__":
    main()
