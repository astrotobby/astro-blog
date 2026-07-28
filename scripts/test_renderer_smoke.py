"""Local smoke test for the finished-video FFmpeg filter graph.

Creates tiny synthetic inputs and exercises word-by-word bottom captions and
music ducking without using network footage or external APIs.

Run from the repository root:
    python3 scripts/test_renderer_smoke.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import OUT, load_config  # noqa: E402
from generate_video import finalize, run  # noqa: E402


def main():
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for this smoke test")
    OUT.mkdir(parents=True, exist_ok=True)
    base = OUT / "_smoke_base.mp4"
    voice = OUT / "_smoke_voice.wav"
    music = OUT / "_smoke_music.wav"
    output = OUT / "_smoke_finished.mp4"

    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
         "-t", "4", "-pix_fmt", "yuv420p", str(base)])
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-t", "4", str(voice)])
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=160:sample_rate=44100",
         "-t", "4", str(music)])

    # Synthetic word-level timings (matching the 4-second synthetic voice)
    word_timings = [
        {"text": "A", "start": 0.1, "end": 0.3},
        {"text": "concise", "start": 0.35, "end": 0.75},
        {"text": "caption", "start": 0.8, "end": 1.2},
        {"text": "remains", "start": 1.25, "end": 1.7},
        {"text": "readable.", "start": 1.75, "end": 2.2},
    ]

    cfg = load_config()
    cfg["video"] = dict(cfg["video"])
    cfg["video"].update({
        "hook_card": False,       # no overlays covering the video
        "data_lower_third": False,
        "end_card": False,
        "music_volume": 0.08,
        "caption_margin_v": 24,
    })
    scene_assets = []
    finalize(base, voice, word_timings, music, {"w": 640, "h": 360}, output, cfg,
             scene_assets, "", 4.0)
    if not output.exists() or output.stat().st_size < 10_000:
        raise RuntimeError("FFmpeg smoke test did not create a usable output")
    print(f"Renderer smoke test passed: {output}")


if __name__ == "__main__":
    main()
