"""Talking-avatar lip-sync via Wav2Lip, run INSIDE the GitHub runner — no external
Space, no timeouts/quotas. Wav2Lip is installed by scripts/setup_wav2lip.sh.

generate_talking_head(avatar_image, voice_audio, cfg, out_name=...) -> talking-head mp4, or None
(so generate_video falls back to the image montage and the render never breaks).
"""
import subprocess

from common import OUT, ROOT, log

WAV2LIP_DIR = ROOT / "Wav2Lip"
# Runs Wav2Lip's inference.py with a persistent face-box cache (see that file).
CACHED_RUNNER = ROOT / "scripts" / "wav2lip_cached.py"


def _is_video(path):
    return str(path).lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"))


def _wav2lip_cmd(face, audio, outfile, warm=False):
    cmd = [
        "python", str(CACHED_RUNNER), *(["--warm-only"] if warm else []),
        "--checkpoint_path", "checkpoints/wav2lip_gan.pth",
        "--face", str(face),
        "--audio", str(audio),
        "--outfile", str(outfile),
        "--pads", "0", "20", "0", "0",       # add chin padding
        "--face_det_batch_size", "1",         # CPU-friendly
        "--wav2lip_batch_size", "16",
    ]
    if not _is_video(face):
        cmd.append("--nosmooth")              # smoothing only helps moving footage
    return cmd


def warm_face_cache(face_path, timeout=1800):
    """Detect and cache the face boxes of a moving base clip without lip-syncing, so
    later renders skip detection. Returns True when the cache is ready."""
    if not (WAV2LIP_DIR / "inference.py").exists() or not _is_video(face_path):
        return False
    r = subprocess.run(_wav2lip_cmd(face_path, "unused.wav", "unused.mp4", warm=True),
                       cwd=str(WAV2LIP_DIR), timeout=timeout, capture_output=True, text=True)
    for line in (r.stdout or "").splitlines():
        if line.startswith("[facecache]"):
            log(line)
    if r.returncode != 0:
        log(f"facecache: warm-up failed (rc={r.returncode}): {(r.stderr or '')[-400:]}")
    return r.returncode == 0


def generate_talking_head(avatar_path, audio_path, cfg, out_name="talking_head.mp4"):
    av = cfg.get("avatar", {})
    ckpt = WAV2LIP_DIR / "checkpoints" / "wav2lip_gan.pth"
    if not ckpt.exists():
        log(f"avatar: Wav2Lip not set up ({ckpt} missing) -> motion-graphics fallback")
        return None

    out = OUT / out_name
    if out.exists():
        out.unlink()
    # A moving base clip (.mp4/.mov/...) is lip-synced frame-by-frame and auto-looped
    # to cover the audio, so the avatar keeps its gestures/expressions. A still image
    # gets lips-only motion. For video we KEEP face-detection smoothing (drop
    # --nosmooth) so the synced mouth tracks the moving head cleanly.
    timeout = int(av.get("timeout", 900))
    try:
        log("avatar: running Wav2Lip on the runner (CPU)...")
        r = subprocess.run(_wav2lip_cmd(avatar_path, audio_path, out), cwd=str(WAV2LIP_DIR),
                           timeout=timeout, capture_output=True, text=True)
        for line in (r.stdout or "").splitlines():
            if line.startswith("[facecache]"):
                log(line)
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
