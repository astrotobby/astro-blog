#!/usr/bin/env bash
# Builds the isolated Kokoro-82M voice environment (.venv-kokoro) used as the free
# narration fallback when ElevenLabs is unavailable. Kept separate from the main
# Python because Kokoro needs newer numpy/torch than Wav2Lip's pinned stack.
# Runs as a continue-on-error workflow step: if it fails, the pipeline falls back to
# edge-tts.
set -euo pipefail

python -m venv .venv-kokoro
echo "[kokoro] installing torch (CPU build)..."
.venv-kokoro/bin/pip install --quiet torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
echo "[kokoro] installing kokoro..."
.venv-kokoro/bin/pip install --quiet "kokoro>=0.9.4" soundfile

# Warm-up: downloads the model weights and the English G2P data once per job.
echo "Kokoro voice is ready." > /tmp/kokoro_warmup.txt
.venv-kokoro/bin/python scripts/kokoro_cli.py /tmp/kokoro_warmup.txt /tmp/kokoro_warmup.wav am_michael 1.0
echo "[kokoro] setup complete"
