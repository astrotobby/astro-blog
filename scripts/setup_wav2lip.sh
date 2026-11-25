#!/usr/bin/env bash
# Python 3.11 Wav2Lip runtime isolated from the main Python 3.12 pipeline.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
VENV="$ROOT/.venv-wav2lip"
PY="$VENV/bin/python"
WAV2LIP="$ROOT/Wav2Lip"
if [[ ! -x "$PY" ]]; then python3.11 -m venv "$VENV"; fi
"$PY" -m pip install --quiet --disable-pip-version-check --upgrade pip wheel
"$PY" -m pip install --quiet --disable-pip-version-check numpy==1.23.5 librosa==0.9.2 numba==0.58.1 scipy==1.10.1 opencv-python==4.9.0.80 huggingface_hub
"$PY" -m pip install --quiet --disable-pip-version-check torch==2.2.2 torchvision==0.17.2 --index-url https://download.pytorch.org/whl/cpu
if [[ ! -d "$WAV2LIP/.git" ]]; then git clone --depth 1 https://github.com/Rudrabha/Wav2Lip.git "$WAV2LIP"; fi
sed -i 's/librosa\.filters\.mel(hp\.sample_rate, hp\.n_fft/librosa.filters.mel(sr=hp.sample_rate, n_fft=hp.n_fft/' "$WAV2LIP/audio.py" || true
mkdir -p "$WAV2LIP/checkpoints" "$WAV2LIP/face_detection/detection/sfd"
TOKEN="$(printenv HF_TOKEN 2>/dev/null || true)" "$PY" - <<'PY'
import os, shutil
from huggingface_hub import hf_hub_download
repo="camenduru/Wav2Lip"
token=os.environ.get("TOKEN") or None
for name in ("checkpoints/wav2lip_gan.pth","face_detection/detection/sfd/s3fd.pth"):
    target=os.path.join("Wav2Lip",name)
    os.makedirs(os.path.dirname(target),exist_ok=True)
    if not os.path.isfile(target) or os.path.getsize(target)<1024:
        shutil.copy2(hf_hub_download(repo,name,token=token),target)
        print("[wav2lip] ready",name)
PY
test -s "$WAV2LIP/checkpoints/wav2lip_gan.pth"
test -s "$WAV2LIP/face_detection/detection/sfd/s3fd.pth"
"$PY" -c "import cv2,librosa,numpy,torch; print('WAV2LIP_RUNTIME_OK',torch.__version__)"