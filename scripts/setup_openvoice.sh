#!/usr/bin/env bash
# Install OpenVoice v2 (MIT) + MeloTTS base + download v2 checkpoints, for free
# in-runner voice cloning. Non-fatal: if anything here fails, the pipeline keeps
# using edge-tts (voice_clone.py falls back). Heavy install — expect a few minutes.
set -o pipefail
echo "[openvoice-setup] installing deps..."

pip install --quiet gdown soundfile librosa "numpy<2" || true

# PyAV (av) is an OpenVoice dep that builds from source on py3.11 unless it has a
# wheel + FFmpeg dev headers. Install the headers and a prebuilt wheel first so the
# OpenVoice install doesn't choke on building 'av'.
echo "[openvoice-setup] FFmpeg dev headers for PyAV..."
sudo apt-get update -qq || true
sudo apt-get install -y -qq pkg-config libavformat-dev libavcodec-dev libavdevice-dev \
  libavutil-dev libavfilter-dev libswscale-dev libswresample-dev || true
pip install --quiet av || true

# OpenVoice (tone-color converter). Install with --no-deps: its requirements pin an
# ancient faster-whisper/av that won't build on py3.11 + FFmpeg 6. We install the few
# runtime deps it actually needs as modern (wheel-backed) versions instead.
if [ ! -d OpenVoice ]; then
  git clone --depth 1 https://github.com/myshell-ai/OpenVoice.git || true
fi
pip install --quiet -e ./OpenVoice --no-deps || true
pip install --quiet pydub wavmark whisper-timestamped inflect unidecode eng_to_ipa \
  pypinyin cn2an jieba langid faster-whisper || true

# MeloTTS (base TTS the converter recolors) + its data
pip install --quiet git+https://github.com/myshell-ai/MeloTTS.git || true
python -m unidic download || true
python - <<'PY' || true
import nltk
for p in ("averaged_perceptron_tagger_eng", "averaged_perceptron_tagger", "cmudict"):
    try:
        nltk.download(p)
    except Exception as e:
        print("nltk dl", p, "failed:", e)
PY

# OpenVoice v2 checkpoints (converter + base-speaker SEs)
echo "[openvoice-setup] downloading checkpoints_v2..."
python - <<'PY' || true
import os
from huggingface_hub import snapshot_download
tok = os.environ.get("HF_TOKEN") or None
try:
    snapshot_download("myshell-ai/OpenVoiceV2", local_dir="checkpoints_v2",
                      token=tok, local_dir_use_symlinks=False)
    print("checkpoints_v2 downloaded")
except Exception as e:
    print("checkpoint download failed:", e)
PY

echo "[openvoice-setup] done (errors above are non-fatal; edge-tts remains the fallback)"
ls -R checkpoints_v2 2>/dev/null | head -40 || true
