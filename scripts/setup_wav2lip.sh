#!/usr/bin/env bash
# Sets up Wav2Lip for in-runner talking-avatar lip-sync.
# Runs as a continue-on-error workflow step: if anything here fails, the pipeline
# still renders (the avatar code sees no checkpoint and falls back to the montage).
set -uo pipefail

echo "[wav2lip] installing deps (pinned for Wav2Lip + Python 3.11)..."
pip install --quiet \
  numpy==1.23.5 \
  librosa==0.9.2 \
  numba==0.58.1 \
  scipy==1.10.1 \
  opencv-python==4.9.0.80

echo "[wav2lip] installing torch (CPU build)..."
pip install --quiet torch==2.2.2 torchvision==0.17.2 \
  --index-url https://download.pytorch.org/whl/cpu

if [ ! -d Wav2Lip ]; then
  echo "[wav2lip] cloning Wav2Lip..."
  git clone --depth 1 https://github.com/Rudrabha/Wav2Lip.git
fi

cd Wav2Lip
# Make audio.py work with modern librosa (keyword args for filters.mel)
sed -i 's/librosa\.filters\.mel(hp\.sample_rate, hp\.n_fft/librosa.filters.mel(sr=hp.sample_rate, n_fft=hp.n_fft/' audio.py || true
mkdir -p checkpoints face_detection/detection/sfd

echo "[wav2lip] downloading weights from Hugging Face (camenduru/Wav2Lip)..."
python - <<'PY'
import os, shutil
from huggingface_hub import hf_hub_download
tok = os.environ.get("HF_TOKEN") or None
repo = "camenduru/Wav2Lip"
shutil.copy(hf_hub_download(repo, "checkpoints/wav2lip_gan.pth", token=tok),
            "checkpoints/wav2lip_gan.pth")
shutil.copy(hf_hub_download(repo, "face_detection/detection/sfd/s3fd.pth", token=tok),
            "face_detection/detection/sfd/s3fd.pth")
print("[wav2lip] weights ready:",
      os.path.getsize("checkpoints/wav2lip_gan.pth"), "bytes")
PY

echo "[wav2lip] setup complete"
