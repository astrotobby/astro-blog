"""Unit tests for the fail-closed TBDub influencer integration.

These tests do not download model weights or require CUDA. A real GPU smoke test is a
separate required release gate on the configured NVIDIA runner.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import influencer
import tbdub_lipsync


class TBDubTimelineTests(unittest.TestCase):
    def test_tbdub_a_roll_never_exceeds_source_clip_duration(self):
        cfg = {
            "influencer": {
                "lipsync_provider": "tbdub",
                "aroll_seconds": [4.0, 4.8],
                "broll_seconds": [30.0, 42.0],
                "min_segment": 4.0,
            }
        }
        looks = [
            {"id": "front", "location": "front", "clip": Path("/tmp/front.mp4")},
            {"id": "monitor", "location": "monitor", "clip": Path("/tmp/monitor.mp4")},
        ]
        for seed in range(25):
            segments = influencer.plan_timeline(900.0, looks, cfg, f"tbdub-{seed}")
            a_roll = [s for s in segments if s["kind"] == "A"]
            self.assertTrue(a_roll)
            self.assertEqual(segments[0]["kind"], "A")
            self.assertIn(segments[-1]["kind"], {"A", "B"})
            for segment in a_roll:
                self.assertLessEqual(segment["t1"] - segment["t0"], 4.800001)


class TBDubJobTests(unittest.TestCase):
    def _inputs(self, duration=4.5):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        video = root / "source.mp4"
        voice = root / "voice.wav"
        video.write_bytes(b"source video")
        voice.write_bytes(b"narration")
        segment = {
            "kind": "A", "t0": 2.0, "t1": 2.0 + duration,
            "look": {"id": "front", "clip": video},
        }
        cfg = {"influencer": {"tbdub": {"source_headroom_seconds": 0.18}}}
        return temporary, root, video, voice, segment, cfg

    def test_build_jobs_extracts_one_audio_excerpt_per_a_roll(self):
        temporary, root, video, voice, segment, cfg = self._inputs()
        self.addCleanup(temporary.cleanup)
        out = root / "out"
        out.mkdir()
        def fake_run(command, **kwargs):
            (out / command[-1]).write_bytes(b"wav bytes" * 200)
            return subprocess.CompletedProcess(command, 0)
        with (
            patch.object(tbdub_lipsync, "OUT", out),
            patch.object(tbdub_lipsync, "_source_duration", return_value=5.04),
            patch.object(tbdub_lipsync, "_run", side_effect=fake_run) as run,
        ):
            jobs = tbdub_lipsync.build_jobs({"horizontal": [segment]}, {"horizontal": voice}, cfg)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["tag"], "horizontal")
        self.assertEqual(jobs[0]["index"], 0)
        self.assertEqual(jobs[0]["video"], video)
        self.assertEqual(jobs[0]["audio"].suffix, ".wav")
        self.assertTrue(jobs[0]["audio"].is_file())
        self.assertIn(str(voice.resolve()), run.call_args.args[0])

    def test_build_jobs_refuses_to_loop_or_boomerang_short_source(self):
        temporary, root, _video, voice, segment, cfg = self._inputs(duration=4.9)
        self.addCleanup(temporary.cleanup)
        out = root / "out"
        out.mkdir()
        with (
            patch.object(tbdub_lipsync, "OUT", out),
            patch.object(tbdub_lipsync, "_source_duration", return_value=5.04),
            patch.object(tbdub_lipsync, "_run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "must not loop or boomerang"):
                tbdub_lipsync.build_jobs({"horizontal": [segment]}, {"horizontal": voice}, cfg)
        run.assert_not_called()

    def test_missing_gpu_or_inference_failure_blocks_tbdub_batch(self):
        temporary, root, video, voice, segment, cfg = self._inputs()
        self.addCleanup(temporary.cleanup)
        out = root / "out"
        out.mkdir()
        audio = root / "segment.wav"
        audio.write_bytes(b"narration")
        output = out / "talk.mp4"
        jobs = [{
            "id": "horizontal_00", "video": video, "audio": audio, "output": output,
            "tag": "horizontal", "index": 0, "seed": 42,
        }]
        with (
            patch.object(tbdub_lipsync, "OUT", out),
            patch.object(tbdub_lipsync, "_runtime", return_value=(Path(sys.executable), root)),
            patch.object(tbdub_lipsync.subprocess, "run",
                         return_value=subprocess.CompletedProcess(["worker"], 1, "", "CUDA unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "refusing unsynchronized presenter footage"):
                tbdub_lipsync.generate_tbdub_batch(jobs, cfg)


if __name__ == "__main__":
    unittest.main()
