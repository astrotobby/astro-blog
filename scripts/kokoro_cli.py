"""Kokoro-82M text-to-speech, run with the isolated .venv-kokoro interpreter.

  .venv-kokoro/bin/python scripts/kokoro_cli.py <text_file> <out.wav> <voice> <speed>

Kokoro needs newer numpy/torch than Wav2Lip's pinned stack, so it lives in its own
virtualenv (scripts/setup_kokoro.sh) and the pipeline calls this script as a
subprocess (scripts/tts_kokoro.py). Writes 24 kHz mono WAV.
"""
import sys

import numpy as np
import soundfile as sf
from kokoro import KPipeline


def main():
    text_file, out_path, voice, speed = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
    text = open(text_file, encoding="utf-8").read().strip()
    # voice ids start with the language: a* = American English, b* = British English
    pipeline = KPipeline(lang_code=voice[0], repo_id="hexgrad/Kokoro-82M")
    chunks = []
    for result in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+"):
        audio = result.audio if hasattr(result, "audio") else result[2]
        if audio is not None:
            chunks.append(audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio))
    if not chunks:
        sys.exit("kokoro produced no audio")
    sf.write(out_path, np.concatenate(chunks), 24000)


if __name__ == "__main__":
    main()
