#!/usr/bin/env bash
# Install the free/open-source TBDub Student runtime on a persistent Linux NVIDIA GPU runner.
# Model weights are downloaded to TBDUB_CHECKPOINT_DIR and are never committed to Git.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
TBDUB_DIR="$ROOT/third_party/TBDub"
PYTHON="$ROOT/.venv-tbdub/bin/python"
CHECKPOINT_DIR="${TBDUB_CHECKPOINT_DIR:-$ROOT/.models/tbdub/checkpoints}"
TBDUB_COMMIT="19e18e4ba8e2a19e6716cb38110ee2de1dae9bb3"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "TBDub requires Linux with an NVIDIA CUDA GPU." >&2
  exit 1
fi
command -v nvidia-smi >/dev/null 2>&1 || {
  echo "No nvidia-smi found. Configure a Linux NVIDIA GPU runner; no paid service is started." >&2
  exit 1
}
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
GPU_MB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1 | tr -d ' ')"
if [[ -z "$GPU_MB" || "$GPU_MB" -lt 16384 ]]; then
  echo "TBDub Student CPU-offload requires at least 16 GiB GPU memory." >&2
  exit 1
fi
if [[ ! -r /proc/meminfo ]]; then
  echo "Cannot verify Linux host RAM before downloading TBDub weights." >&2
  exit 1
fi
RAM_TOTAL_KB="$(awk '$1 == "MemTotal:" {print $2}' /proc/meminfo)"
RAM_AVAILABLE_KB="$(awk '$1 == "MemAvailable:" {print $2}' /proc/meminfo)"
if [[ -z "$RAM_TOTAL_KB" || "$RAM_TOTAL_KB" -lt 25165824 || -z "$RAM_AVAILABLE_KB" || "$RAM_AVAILABLE_KB" -lt 22020096 ]]; then
  echo "TBDub Student CPU-offload needs at least 24 GiB total RAM and 21 GiB available. Refusing to download 15.3 GB of weights on an undersized runner." >&2
  exit 1
fi
command -v python3.10 >/dev/null 2>&1 || {
  echo "Python 3.10 is required. Install it on the GPU runner first." >&2
  exit 1
}
command -v git >/dev/null 2>&1
command -v ffmpeg >/dev/null 2>&1
command -v curl >/dev/null 2>&1

mkdir -p "$CHECKPOINT_DIR" "$(dirname "$TBDUB_DIR")"
FREE_KB="$(df -Pk "$CHECKPOINT_DIR" | awk 'NR==2 {print $4}')"
if [[ -z "$FREE_KB" || "$FREE_KB" -lt 26000000 ]]; then
  echo "TBDub needs about 15.3 GB of model files plus working space; provide at least 26 GB free disk." >&2
  exit 1
fi

if [[ ! -d "$TBDUB_DIR/.git" ]]; then
  git clone https://github.com/TaoLiveAIGC/TBDub.git "$TBDUB_DIR"
fi
git -C "$TBDUB_DIR" fetch --depth 1 origin "$TBDUB_COMMIT"
git -C "$TBDUB_DIR" checkout --detach "$TBDUB_COMMIT"

if [[ ! -x "$PYTHON" ]]; then
  python3.10 -m venv "$ROOT/.venv-tbdub"
fi
"$PYTHON" -m pip install --disable-pip-version-check --upgrade pip wheel
"$PYTHON" -m pip install --disable-pip-version-check torch==2.9.0 torchvision==0.24.0 --index-url https://download.pytorch.org/whl/cu128
# Reject non-BF16 architectures (e.g. free T4/P100 notebook GPUs) before downloading
# the ~15.3 GB Student/VAE/Hubert checkpoints.
"$PYTHON" - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("TBDub requires CUDA; no NVIDIA GPU is visible.")
name = torch.cuda.get_device_name(0)
major, minor = torch.cuda.get_device_capability(0)
if (major, minor) < (8, 0):
    raise SystemExit(f"{name} has compute capability {major}.{minor}; native BF16 requires NVIDIA Ampere (8.0) or newer.")
if not torch.cuda.is_bf16_supported():
    raise SystemExit(f"{name} does not support BF16 required by TBDub.")
free_vram, total_vram = torch.cuda.mem_get_info(0)
if total_vram < 16 * 1024**3 or free_vram < 15 * 1024**3:
    raise SystemExit(f"TBDub needs >=16 GiB total and ~15 GiB free VRAM; detected {free_vram/1024**3:.1f}/{total_vram/1024**3:.1f} GiB free/total.")
print("TBDub compatible GPU:", name, f"({major}.{minor})")
PY
"$PYTHON" -m pip install --disable-pip-version-check -r "$TBDUB_DIR/requirements.txt"

# Public model weights; choose Student only. hf download is resumable and skips files
# already present in this persistent checkpoint directory.
if [[ ! -s "$CHECKPOINT_DIR/config.json" || ! -s "$CHECKPOINT_DIR/tbdub_student.safetensors" || ! -s "$CHECKPOINT_DIR/null_prompt_emb.pt" ]]; then
  "$PYTHON" -m pip install --disable-pip-version-check 'huggingface_hub==1.4.1'
  "$ROOT/.venv-tbdub/bin/hf" download TaoLiveAIGC/TBDub \
    config.json null_prompt_emb.pt tbdub_student.safetensors --local-dir "$CHECKPOINT_DIR"
fi
if [[ ! -s "$CHECKPOINT_DIR/Wan2.2_VAE.safetensors" ]]; then
  "$ROOT/.venv-tbdub/bin/hf" download KlingTeam/X-Dub Wan2.2_VAE.safetensors --local-dir "$CHECKPOINT_DIR"
fi
if [[ ! -s "$CHECKPOINT_DIR/hubert-large-ll60k/pytorch_model.bin" ]]; then
  "$ROOT/.venv-tbdub/bin/hf" download facebook/hubert-large-ll60k \
    config.json preprocessor_config.json pytorch_model.bin \
    --local-dir "$CHECKPOINT_DIR/hubert-large-ll60k"
fi
if [[ ! -s "$CHECKPOINT_DIR/face_landmarker.task" ]]; then
  curl -fL --retry 3 \
    https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task \
    -o "$CHECKPOINT_DIR/face_landmarker.task.tmp"
  echo '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff  '"$CHECKPOINT_DIR/face_landmarker.task.tmp" | sha256sum -c -
  mv "$CHECKPOINT_DIR/face_landmarker.task.tmp" "$CHECKPOINT_DIR/face_landmarker.task"
fi

export TBDUB_CHECKPOINT_DIR="$CHECKPOINT_DIR"
"$PYTHON" - <<'PY'
import os, torch
assert torch.cuda.is_available(), "CUDA is not available"
assert torch.cuda.is_bf16_supported(), "TBDub requires BF16 support"
print("TBDUB_RUNTIME_READY", torch.__version__, torch.cuda.get_device_name(0))
print("TBDUB_CHECKPOINT_DIR", os.environ["TBDUB_CHECKPOINT_DIR"])
PY
echo "TBDub Student is installed. No paid API is used."
