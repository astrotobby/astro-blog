"""Kokoro narration: the free, no-quota voice used when ElevenLabs is unavailable.

synthesize(text, out_path, cfg) -> path of the WAV on success, else None.

Kokoro-82M (Apache-2.0) runs on the runner's CPU from an isolated virtualenv built by
scripts/setup_kokoro.sh, so it never touches the Wav2Lip dependency pins. No word
timings come back; the caller transcribes the audio for captions instead. Any failure
returns None so the pipeline falls through to edge-tts.
"""
import subprocess
from pathlib import Path

from common import OUT, ROOT, env, log

DEFAULTS = {"voice": "am_michael", "speed": 1.05, "timeout": 900}


def _python():
    custom = env("KOKORO_PYTHON")
    candidates = [Path(custom)] if custom else []
    candidates += [ROOT / ".venv-kokoro" / "bin" / "python",
                   ROOT / ".venv-kokoro" / "Scripts" / "python.exe"]
    return next((p for p in candidates if p.exists()), None)


def synthesize(text, out_path, cfg):
    settings = dict(DEFAULTS)
    settings.update(((cfg or {}).get("voice") or {}).get("kokoro") or {})
    python = _python()
    if python is None:
        log("Kokoro not set up (.venv-kokoro missing)")
        return None
    text_file = OUT / "_kokoro_text.txt"
    text_file.write_text(text, encoding="utf-8")
    wav = Path(out_path).with_suffix(".wav")
    wav.unlink(missing_ok=True)
    r = subprocess.run([str(python), str(ROOT / "scripts" / "kokoro_cli.py"), str(text_file),
                        str(wav), settings["voice"], str(settings["speed"])],
                       capture_output=True, text=True, timeout=int(settings["timeout"]))
    if r.returncode != 0 or not wav.exists() or wav.stat().st_size < 1024:
        log(f"Kokoro failed (rc={r.returncode}): {(r.stderr or '')[-400:]}")
        return None
    return wav
