"""Local smoke test for the finished-video FFmpeg filter graph.

Creates tiny synthetic inputs and exercises captions, music ducking, a data lower
third, hook card, and end card without using network footage or external APIs.

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
    captions = OUT / "_smoke.srt"
    output = OUT / "_smoke_finished.mp4"

    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
         "-t", "4", "-pix_fmt", "yuv420p", str(base)])
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-t", "4", str(voice)])
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=160:sample_rate=44100",
         "-t", "4", str(music)])
    captions.write_text("1\n00:00:00,100 --> 00:00:02,000\nA concise caption remains readable.\n", encoding="utf-8")

    cfg = load_config()
    cfg["video"] = dict(cfg["video"])
    cfg["video"].update({
        "hook_card": True,
        "data_lower_third": True,
        "end_card": True,
        "music_volume": 0.08,
        "caption_margin_v": 24,
    })
    scene_assets = [(None, {"stat": "42% more efficient", "start": 1.0, "end": 2.5})]
    finalize(base, voice, captions, music, {"w": 640, "h": 360}, output, cfg,
             scene_assets, "Why this footage-first workflow matters", 4.0)
    if not output.exists() or output.stat().st_size < 10_000:
        raise RuntimeError("FFmpeg smoke test did not create a usable output")
    print(f"Renderer smoke test passed: {output}")


if __name__ == "__main__":
    main()
