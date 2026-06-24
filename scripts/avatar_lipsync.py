"""Talking-avatar lip-sync via Wav2Lip, run INSIDE the GitHub runner — no external
Space, no timeouts/quotas. Wav2Lip is installed by scripts/setup_wav2lip.sh.

generate_talking_head(avatar_image, voice_audio, cfg) -> talking-head mp4, or None
(so generate_video falls back to the image montage and the render never breaks).
"""
import subprocess

from common import OUT, ROOT, log

WAV2LIP_DIR = ROOT / "Wav2Lip"


def generate_talking_head(avatar_path, audio_path, cfg):
    av = cfg.get("avatar", {})
    ckpt = WAV2LIP_DIR / "checkpoints" / "wav2lip_gan.pth"
    if not ckpt.exists():
        log(f"avatar: Wav2Lip not set up ({ckpt} missing) -> motion-graphics fallback")
        return None

    out = OUT / "talking_head.mp4"
    if out.exists():
        out.unlink()
    # A moving base clip (.mp4/.mov/...) is lip-synced frame-by-frame and auto-looped
    # to cover the audio, so the avatar keeps its gestures/expressions. A still image
    # gets lips-only motion. For video we KEEP face-detection smoothing (drop
    # --nosmooth) so the synced mouth tracks the moving head cleanly.
    is_video = str(avatar_path).lower().endswith(
        (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"))
    cmd = [
        "python", "inference.py",
        "--checkpoint_path", "checkpoints/wav2lip_gan.pth",
        "--face", str(avatar_path),
        "--audio", str(audio_path),
        "--outfile", str(out),
        "--pads", "0", "20", "0", "0",       # add chin padding
        "--face_det_batch_size", "1",         # CPU-friendly
        "--wav2lip_batch_size", "16",
    ]
    if not is_video:
        cmd.append("--nosmooth")              # smoothing only helps moving footage
    timeout = int(av.get("timeout", 900))
    try:
        log("avatar: running Wav2Lip on the runner (CPU)...")
        r = subprocess.run(cmd, cwd=str(WAV2LIP_DIR), timeout=timeout,
                           capture_output=True, text=True)
        if r.returncode != 0:
            log(f"avatar: Wav2Lip failed (rc={r.returncode}):\n{(r.stderr or '')[-600:]}")
            return None
        if out.exists() and out.stat().st_size > 1000:
            log(f"avatar: Wav2Lip SUCCESS -> {out.name}")
            return out
        log("avatar: Wav2Lip produced no output -> motion-graphics fallback")
        return None
    except subprocess.TimeoutExpired:
        log(f"avatar: Wav2Lip timed out after {timeout}s -> fallback")
        return None
    except Exception as e:  # noqa
        log(f"avatar: Wav2Lip error -> fallback: {str(e)[:200]}")
        return None
