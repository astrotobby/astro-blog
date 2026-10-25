#!/usr/bin/env bash
# Builds the isolated Kokoro-82M voice environment (.venv-kokoro) used as the free
# narration fallback when ElevenLabs is unavailable. Kept separate from the main
# Python because Kokoro needs newer numpy/torch than Wav2Lip's pinned stack.
# Runs as a continue-on-error workflow step: if it fails, the pipeline falls back to
# edge-tts.
set -euo pipefail

python -m venv .venv-kokoro
echo "[kokoro] installing torch (CPU build)..."
.venv-kokoro/bin/pip install --quiet torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
echo "[kokoro] installing kokoro..."
# Pinned, known-good spaCy stack: a newer spaCy/preshed release fails to load the
# en_core_web_sm tokenizer ("OverflowError ... _flush_specials").
.venv-kokoro/bin/pip install --quiet "kokoro>=0.9.4" soundfile   spacy==3.8.4 thinc==8.3.4 numpy==1.26.4 preshed==3.0.9 cymem==2.0.11   "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
.venv-kokoro/bin/pip list 2>/dev/null | grep -iE "^(kokoro|misaki|spacy|thinc|numpy|preshed|cymem|torch|transformers) " || true

# Warm-up: downloads the model weights and the English G2P data once per job.
echo "Kokoro voice is ready." > /tmp/kokoro_warmup.txt
.venv-kokoro/bin/python scripts/kokoro_cli.py /tmp/kokoro_warmup.txt /tmp/kokoro_warmup.wav am_michael 1.0
echo "[kokoro] setup complete"
