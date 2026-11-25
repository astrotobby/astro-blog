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
import tbdub_worker


class TBDubTimelineTests(unittest.TestCase):
    def test_tbdub_a_roll_never_exceeds_source_clip_duration(self):
        cfg = {
            "influencer": {
                "lipsync_provider": "tbdub",
                "aroll_seconds": [2.4, 2.8],
                "broll_seconds": [45.0, 60.0],
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
                self.assertLessEqual(segment["t1"] - segment["t0"], 2.800001)


class TBDubJobTests(unittest.TestCase):
    def test_tbdub_frame_count_is_converted_to_seconds(self):
        class StubCore:
            @staticmethod
            def get_audio_length(_audio_path):
                return 120  # 4.8 seconds at TBDub's 25 fps
        self.assertAlmostEqual(tbdub_worker._audio_duration_seconds(StubCore, "voice.wav"), 4.8)

    def _inputs(self, duration=2.6):
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
        cfg = {"influencer": {"tbdub": {}}}
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
            patch.object(tbdub_lipsync, "_source_frame_count", return_value=121),
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
        self.assertGreaterEqual(jobs[0]["start_frame"], 0)
        self.assertLessEqual(jobs[0]["start_frame"], 49)

    def test_build_jobs_refuses_audio_that_needs_more_than_one_72_frame_window(self):
        temporary, root, _video, voice, segment, cfg = self._inputs(duration=3.2)
        self.addCleanup(temporary.cleanup)
        out = root / "out"
        out.mkdir()
        with (
            patch.object(tbdub_lipsync, "OUT", out),
            patch.object(tbdub_lipsync, "_source_duration", return_value=5.04),
            patch.object(tbdub_lipsync, "_source_frame_count", return_value=121),
            patch.object(tbdub_lipsync, "_run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "Cannot proceed without source-frame looping"):
                tbdub_lipsync.build_jobs({"horizontal": [segment]}, {"horizontal": voice}, cfg)
        run.assert_not_called()

    def test_batch_manifest_preserves_varied_source_start_frame(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        out = root / "out"
        out.mkdir()
        video, audio, output = root / "source.mp4", root / "voice.wav", out / "talk.mp4"
        video.write_bytes(b"video")
        audio.write_bytes(b"audio")
        output.write_bytes(b"rendered video" * 1000)
        jobs = [{
            "id": "horizontal_00", "video": video, "audio": audio, "output": output,
            "tag": "horizontal", "index": 0, "seed": 42, "start_frame": 17,
        }]

        def fake_run(command, **kwargs):
            manifest = Path(command[command.index("--manifest") + 1])
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["jobs"][0]["start_frame"], 17)
            results = manifest.with_suffix(".results.json")
            results.write_text(json.dumps({"jobs": [{
                "id": "horizontal_00", "output": str(output), "bytes": output.stat().st_size,
                "duration": 2.6,
            }]}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        cfg = {"influencer": {"tbdub": {}}}
        with (
            patch.object(tbdub_lipsync, "OUT", out),
            patch.object(tbdub_lipsync, "_runtime", return_value=(Path(sys.executable), root)),
            patch.object(tbdub_lipsync.subprocess, "run", side_effect=fake_run),
        ):
            result = tbdub_lipsync.generate_tbdub_batch(jobs, cfg)
        self.assertEqual(result["horizontal_00"], output)

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
