"""Free in-runner voice cloning with OpenVoice v2 (MIT) + MeloTTS.

synthesize(text, out_path, cfg) -> out_path on success, else None (caller falls
back to edge-tts so the pipeline NEVER breaks over voice cloning).

Pipeline: MeloTTS speaks the text in a base voice, then OpenVoice's tone-color
converter recolours it to the target voice. The target voice "fingerprint" (speaker embedding) is extracted ONCE from the configured
reference video or audio source and cached in .pipeline/state under a reference-specific key.
The production config keeps cloning disabled until the owner confirms authorization.
"""
import glob
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common import env

# Imports of heavy libs happen INSIDE functions so importing this module is safe
# even when OpenVoice/MeloTTS aren't installed.

ROOT = Path(__file__).resolve().parents[1]
CKPT = str(ROOT / "checkpoints_v2")


def _log(m):
    print(f"[voice-clone] {m}", file=sys.stderr, flush=True)


def _state_dir():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(here, ".pipeline", "state")
    os.makedirs(d, exist_ok=True)
    return d


def _voice_cfg(cfg):
    return ((cfg or {}).get("voice") or {})


def _reference_key(cfg):
    voice = _voice_cfg(cfg)
    ref = env("VOICE_REFERENCE_URL") or voice.get("reference_url") or voice.get("reference_path")
    return hashlib.sha256(str(ref or "legacy").encode("utf-8")).hexdigest()[:16]


def _download_reference_video(destination, reference):
    """Download a single reference video/audio source without logging credentials."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 2048:
        return destination
    if not reference:
        return None
    try:
        if str(reference).startswith(("http://", "https://")) and ("youtube.com" in reference or "youtu.be" in reference):
            import yt_dlp
            template = str(destination.with_suffix(".%(ext)s"))
            opts = {
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": template,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav",
                                    "preferredquality": "192"}],
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([reference])
            generated = destination.with_suffix(".wav")
            return generated if generated.exists() else None
        if str(reference).startswith(("http://", "https://")):
            import requests
            response = requests.get(reference, timeout=120, stream=True)
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if chunk:
                        handle.write(chunk)
            return destination
        path = Path(reference).expanduser()
        if path.exists():
            shutil.copy2(path, destination)
            return destination
    except Exception as exc:  # noqa
        _log(f"reference download failed: {exc}")
    return None


def _download_samples(dest, cfg):
    """Materialize the configured reference source into a local sample directory."""
    os.makedirs(dest, exist_ok=True)
    voice = _voice_cfg(cfg)
    reference = env("VOICE_REFERENCE_URL") or voice.get("reference_url") or voice.get("reference_path")
    if reference:
        target = os.path.join(dest, "reference_source")
        downloaded = _download_reference_video(target, reference)
        if downloaded:
            return dest
        _log("configured voice reference could not be downloaded")
    # A Drive folder may still be used only when explicitly configured by the owner.
    folder_id = voice.get("reference_folder_id")
    if folder_id:
        try:
            import gdown
            gdown.download_folder(
                f"https://drive.google.com/drive/folders/{folder_id}",
                output=dest, quiet=False, use_cookies=False)
        except Exception as exc:  # noqa
            _log(f"sample folder download failed: {exc}")
    return dest


def _reference_wavs(sample_dir):
    """Transcode every reference clip to clean mono WAV files."""
    clips = sorted(glob.glob(os.path.join(sample_dir, "*")))
    clips = [c for c in clips if os.path.isfile(c)
             and not os.path.basename(c).startswith("_c")]
    wavs = []
    for i, c in enumerate(clips):
        w = os.path.join(sample_dir, f"_c{i}.wav")
        r = subprocess.run(["ffmpeg", "-y", "-i", c, "-ar", "22050", "-ac", "1", w],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(w) and os.path.getsize(w) > 2048:
            wavs.append(w)
    return wavs


def _enhance(src, dst):
    """Make the clone sharp, loud and active: high-pass the rumble, punchy
    compression, a presence/treble lift, then EBU loudness normalisation so it's
    consistently loud. Falls back to a plain copy if ffmpeg errors."""
    chain = ("highpass=f=85,"
             "acompressor=threshold=-20dB:ratio=4:attack=5:release=120,"
             "treble=g=4:f=3000,"
             "loudnorm=I=-13:TP=-1.0:LRA=11")
    r = subprocess.run(["ffmpeg", "-y", "-i", src, "-af", chain, "-ar", "44100", dst],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        import shutil
        shutil.copy(src, dst)


def _get_converter(device):
    from openvoice.api import ToneColorConverter
    conv = ToneColorConverter(f"{CKPT}/converter/config.json", device=device)
    conv.load_ckpt(f"{CKPT}/converter/checkpoint.pth")
    return conv


def _target_se(device, converter, cfg):
    """Load or build the target embedding for the configured reference source."""
    import torch
    se_path = os.path.join(_state_dir(), f"voice_se_{_reference_key(cfg)}.pth")
    if os.path.exists(se_path):
        try:
            return torch.load(se_path, map_location=device)
        except Exception:  # noqa
            pass
    samples = _download_samples(os.path.join(_state_dir(), "voice_samples"), cfg)
    wavs = _reference_wavs(samples)
    if not wavs:
        _log("no usable reference clips")
        return None
    _log(f"extracting voice embedding from {len(wavs)} clip(s)")
    se = converter.extract_se(wavs, se_save_path=None)
    try:
        torch.save(se, se_path)
    except Exception:  # noqa
        pass
    return se


def synthesize(text, out_path, cfg=None):
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        converter = _get_converter(device)
        tgt_se = _target_se(device, converter, cfg)
        if tgt_se is None:
            _log("no target speaker embedding -> fallback")
            return None
        # base TTS with MeloTTS (English)
        from melo.api import TTS
        speed = float(((cfg or {}).get("voice", {}) or {}).get("clone_speed", 1.0))
        tts = TTS(language="EN", device=device)
        spk2id = tts.hps.data.spk2id   # HParams: supports [] and 'in', not .get()
        spk_id = spk2id["EN-US"] if "EN-US" in spk2id else list(spk2id.values())[0]
        base_wav = os.path.join(_state_dir(), "_base.wav")
        tts.tts_to_file(text, spk_id, base_wav, speed=speed)
        # recolour to the target voice
        src_se = torch.load(f"{CKPT}/base_speakers/ses/en-us.pth", map_location=device)
        raw = os.path.join(_state_dir(), "_clone_raw.wav")
        converter.convert(audio_src_path=base_wav, src_se=src_se, tgt_se=tgt_se,
                          output_path=raw, message="@AstroTobby")
        if not (os.path.exists(raw) and os.path.getsize(raw) > 1024):
            return None
        _enhance(raw, out_path)   # sharp, loud, active
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
            _log(f"cloned voice -> {out_path}")
            return out_path
        return None
    except Exception as e:  # noqa
        _log(f"clone failed ({e}); caller will fall back to edge-tts")
        return None


if __name__ == "__main__":
    from common import load_config

    txt = sys.argv[1] if len(sys.argv) > 1 else \
        "Here's what nobody tells you about AI agents in 2026. This is my cloned voice."
    out = sys.argv[2] if len(sys.argv) > 2 else "cloned_sample.wav"
    r = synthesize(txt, out, load_config())
    print("RESULT:", r or "FAILED")
    sys.exit(0 if r else 1)
