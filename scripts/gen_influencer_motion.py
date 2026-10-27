"""Generate a moving base clip for each AI-influencer look (one-time, free).

LTX-2 (free Hugging Face Space) animates the look's still into ~10 s of him talking:
head nods, expressions, hand gestures. The clip is saved at the look's `clip` path in
assets/influencer/looks.yaml. When the per-segment LTX quota runs out during a render,
Wav2Lip re-syncs the mouth on this MOVING clip instead of a frozen still, so the
presenter never looks robotic. Existing clips are never overwritten.

  HF_TOKEN=... python scripts/gen_influencer_motion.py [look_id ...]
"""
import asyncio
import os
import subprocess
import sys

import yaml

from common import OUT, ROOT, log
from influencer import LTX_NEGATIVE, LTX_PROMPT, LTX_SPACE

# Any natural, upbeat speech works: Wav2Lip replaces the mouth movement per video.
LINE = ("Okay, so here is what nobody is telling you about this. It is honestly one of the "
        "biggest shifts I have seen this year, and if you get it early, you win. Let me "
        "break it down for you.")
VOICE = "en-US-AndrewMultilingualNeural"
SECONDS = 10.0


def _speech(path):
    import edge_tts
    asyncio.run(edge_tts.Communicate(LINE, VOICE).save(str(path)))
    wav = path.with_suffix(".wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-t", f"{SECONDS}",
                    "-ac", "1", "-ar", "44100", str(wav)], check=True)
    return wav


def main():
    from gradio_client import Client, handle_file

    only = set(sys.argv[1:])
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    looks_file = ROOT / cfg.get("influencer", {}).get("looks_file", "assets/influencer/looks.yaml")
    looks = yaml.safe_load(looks_file.read_text(encoding="utf-8"))["looks"]
    todo = [lk for lk in looks if lk.get("clip") and lk.get("image")
            and (ROOT / lk["image"]).exists() and not (ROOT / lk["clip"]).exists()
            and (not only or lk["id"] in only)]
    if not todo:
        log("influencer motion clips: nothing to generate")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    audio = _speech(OUT / "_motion_line.mp3")
    client = Client(LTX_SPACE, token=os.environ.get("HF_TOKEN") or None)
    for lk in todo:
        try:
            video, _seed = client.predict(handle_file(str(ROOT / lk["image"])), handle_file(str(audio)),
                                          LTX_PROMPT, LTX_NEGATIVE, SECONDS, -1,
                                          api_name="/generate")
        except Exception as e:  # noqa  quota: the rest are generated on a later run
            log(f"motion {lk['id']}: generation failed ({str(e)[:200]})")
            if "quota" in str(e).lower() or "limit" in str(e).lower():
                break
            continue
        path = video.get("video", video) if isinstance(video, dict) else video
        dst = ROOT / lk["clip"]
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-an", "-c:v", "libx264",
                        "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(dst)], check=True)
        log(f"motion {lk['id']} -> {lk['clip']}")


if __name__ == "__main__":
    main()
