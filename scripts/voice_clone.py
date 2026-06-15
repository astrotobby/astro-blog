"""Free in-runner voice cloning with OpenVoice v2 (MIT) + MeloTTS.

synthesize(text, out_path, cfg) -> out_path on success, else None (caller falls
back to edge-tts so the pipeline NEVER breaks over voice cloning).

Pipeline: MeloTTS speaks the text in a base voice, then OpenVoice's tone-color
converter recolours it to the target voice. The target voice "fingerprint" (speaker
embedding) is extracted ONCE from the Drive samples and cached in .pipeline/state.
"""
import glob
import os
import subprocess
import sys

# Imports of heavy libs happen INSIDE functions so importing this module is safe
# even when OpenVoice/MeloTTS aren't installed.

CKPT = "checkpoints_v2"
FOLDER_ID = "1uxnpGUy38Mqc8snwsnzVC6uHMO9ps4W0"   # user's Drive voice-samples folder (public)


def _log(m):
    print(f"[voice-clone] {m}", file=sys.stderr, flush=True)


def _state_dir():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(here, ".pipeline", "state")
    os.makedirs(d, exist_ok=True)
    return d


def _download_samples(dest):
    """Pull the public Drive folder of voice clips (no auth needed)."""
    os.makedirs(dest, exist_ok=True)
    if glob.glob(os.path.join(dest, "*")):
        return dest
    try:
        import gdown
        gdown.download_folder(
            f"https://drive.google.com/drive/folders/{FOLDER_ID}",
            output=dest, quiet=False, use_cookies=False)
    except Exception as e:  # noqa
        _log(f"sample download failed: {e}")
    return dest


def _build_reference(sample_dir, out_wav):
    """Concatenate the clips into one clean 16k mono wav for embedding."""
    clips = sorted(glob.glob(os.path.join(sample_dir, "*")))
    clips = [c for c in clips if os.path.isfile(c)]
    if not clips:
        return None
    listf = os.path.join(sample_dir, "_list.txt")
    # transcode each to wav first (3gp/AMR -> wav), then concat
    wavs = []
    for i, c in enumerate(clips):
        w = os.path.join(sample_dir, f"_c{i}.wav")
        r = subprocess.run(["ffmpeg", "-y", "-i", c, "-ar", "16000", "-ac", "1", w],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(w):
            wavs.append(w)
    if not wavs:
        return None
    with open(listf, "w") as f:
        for w in wavs:
            f.write(f"file '{os.path.abspath(w)}'\n")
    r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf,
                        "-ar", "16000", "-ac", "1", out_wav], capture_output=True, text=True)
    return out_wav if (r.returncode == 0 and os.path.exists(out_wav)) else None


def _get_converter(device):
    from openvoice.api import ToneColorConverter
    conv = ToneColorConverter(f"{CKPT}/converter/config.json", device=device)
    conv.load_ckpt(f"{CKPT}/converter/checkpoint.pth")
    return conv


def _target_se(device, converter):
    """Load cached target speaker embedding, or build it from the Drive samples."""
    import torch
    se_path = os.path.join(_state_dir(), "voice_se.pth")
    if os.path.exists(se_path):
        try:
            return torch.load(se_path, map_location=device)
        except Exception:  # noqa
            pass
    from openvoice import se_extractor
    samples = _download_samples(os.path.join(_state_dir(), "voice_samples"))
    ref = _build_reference(samples, os.path.join(_state_dir(), "voice_ref.wav"))
    if not ref:
        return None
    se, _ = se_extractor.get_se(ref, converter, vad=True)
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
        tgt_se = _target_se(device, converter)
        if tgt_se is None:
            _log("no target speaker embedding -> fallback")
            return None
        # base TTS with MeloTTS (English)
        from melo.api import TTS
        speed = float(((cfg or {}).get("voice", {}) or {}).get("clone_speed", 1.0))
        tts = TTS(language="EN", device=device)
        spk = tts.hps.data.spk2id
        spk_id = spk.get("EN-US") or list(spk.values())[0]
        base_wav = os.path.join(_state_dir(), "_base.wav")
        tts.tts_to_file(text, spk_id, base_wav, speed=speed)
        # recolour to the target voice
        src_se = torch.load(f"{CKPT}/base_speakers/ses/en-us.pth", map_location=device)
        converter.convert(audio_src_path=base_wav, src_se=src_se, tgt_se=tgt_se,
                          output_path=out_path, message="@AstroTobby")
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
            _log(f"cloned voice -> {out_path}")
            return out_path
        return None
    except Exception as e:  # noqa
        _log(f"clone failed ({e}); caller will fall back to edge-tts")
        return None


if __name__ == "__main__":
    txt = sys.argv[1] if len(sys.argv) > 1 else \
        "Here's what nobody tells you about AI agents in 2026. This is my cloned voice."
    out = sys.argv[2] if len(sys.argv) > 2 else "cloned_sample.wav"
    r = synthesize(txt, out, {})
    print("RESULT:", r or "FAILED")
    sys.exit(0 if r else 1)
