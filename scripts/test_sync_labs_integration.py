"""CPU-only regression tests for the managed Sync Labs integration."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_labs_lipsync
import influencer


class SyncLabsBudgetTests(unittest.TestCase):
    def test_timeline_caps_sync3_to_two_presenter_segments_per_master(self):
        cfg = {
            "influencer": {
                "lipsync_provider": "sync_labs",
                "aroll_seconds": [4.0, 4.8],
                "broll_seconds": [45.0, 60.0],
                "min_segment": 4.0,
                "sync_labs": {"max_segments_per_variant": 2},
            }
        }
        looks = [
            {"id": "front", "location": "front", "clip": Path("/tmp/front.mp4")},
            {"id": "monitor", "location": "monitor", "clip": Path("/tmp/monitor.mp4")},
        ]
        segments = influencer.plan_timeline(840.0, looks, cfg, "sync3-cap-test")
        a_roll = [segment for segment in segments if segment["kind"] == "A"]
        self.assertEqual(len(a_roll), 2)
        self.assertEqual(segments[-1]["kind"], "B")
        for segment in a_roll:
            self.assertLessEqual(segment["t1"] - segment["t0"], 4.800001)

    def setUp(self):
        sync_labs_lipsync.reset_run_budget_for_tests()

    def tearDown(self):
        sync_labs_lipsync.reset_run_budget_for_tests()

    def test_preflight_checks_sync3_model_access_without_generating(self):
        fake_models = type("Response", (), {
            "status_code": 200,
            "json": staticmethod(lambda: [{"id": "sync-3", "name": "sync-3"}]),
            "text": "",
        })()
        with (
            patch.dict(os.environ, {"SYNC_API_KEY": "test-key", "SYNC_LABS_MAX_SPEND_USD_PER_RUN": "0"}),
            patch.object(sync_labs_lipsync.requests, "get", return_value=fake_models) as get,
        ):
            with self.assertRaisesRegex(RuntimeError, "Paid Sync-3 production is disabled"):
                sync_labs_lipsync.preflight({"influencer": {"sync_labs": {"model": "sync-3"}}}, [])
        self.assertEqual(get.call_args.args[0], "https://api.sync.so/v2/models")

    def test_preflight_blocks_when_sync3_not_enabled_for_key(self):
        fake_models = type("Response", (), {
            "status_code": 200,
            "json": staticmethod(lambda: [{"id": "lipsync-2", "name": "lipsync-2"}]),
            "text": "",
        })()
        with (
            patch.dict(os.environ, {"SYNC_API_KEY": "test-key", "SYNC_LABS_MAX_SPEND_USD_PER_RUN": "0"}),
            patch.object(sync_labs_lipsync.requests, "get", return_value=fake_models),
        ):
            with self.assertRaisesRegex(RuntimeError, "does not currently have access to Sync-3"):
                sync_labs_lipsync.preflight({"influencer": {"sync_labs": {"model": "sync-3"}}}, [])

    def test_zero_budget_blocks_before_any_api_request(self):
        job = {"id": "horizontal_00", "audio": Path("audio.wav")}
        with (
            patch.dict(os.environ, {"SYNC_API_KEY": "test-key", "SYNC_LABS_MAX_SPEND_USD_PER_RUN": "0"}),
            patch.object(sync_labs_lipsync, "_duration", return_value=4.8),
            patch.object(sync_labs_lipsync.requests, "post") as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "blocked this batch before any API request"):
                sync_labs_lipsync.generate_batch([job], {"influencer": {"sync_labs": {"model": "sync-3"}}})
        post.assert_not_called()

    def test_under_budget_batch_reserves_upper_bound_and_returns_outputs(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / "talk.mp4"
        job = {"id": "horizontal_00", "audio": Path("audio.wav"), "output": output}
        with (
            patch.dict(os.environ, {"SYNC_API_KEY": "test-key", "SYNC_LABS_MAX_SPEND_USD_PER_RUN": "1.00"}),
            patch.object(sync_labs_lipsync, "_duration", return_value=4.0),
            patch.object(sync_labs_lipsync, "generate_one", return_value=output),
        ):
            result = sync_labs_lipsync.generate_batch([job], {"influencer": {"sync_labs": {"model": "sync-3"}}})
        self.assertEqual(result["horizontal_00"], output)
        self.assertAlmostEqual(sync_labs_lipsync._RESERVED_USD, (4.0 + 2 / 25) * 0.133, places=6)

    def test_budget_reservation_accumulates_across_vertical_and_horizontal_outputs(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        first = Path(temporary.name) / "one.mp4"
        second = Path(temporary.name) / "two.mp4"
        jobs1 = [{"id": "vertical_00", "audio": Path("a.wav"), "output": first}]
        jobs2 = [{"id": "horizontal_00", "audio": Path("b.wav"), "output": second}]
        with (
            patch.dict(os.environ, {"SYNC_API_KEY": "test-key", "SYNC_LABS_MAX_SPEND_USD_PER_RUN": "1.00"}),
            patch.object(sync_labs_lipsync, "_duration", return_value=4.0),
            patch.object(sync_labs_lipsync, "generate_one", side_effect=[first, second]),
        ):
            sync_labs_lipsync.generate_batch(jobs1, {"influencer": {"sync_labs": {"model": "sync-3"}}})
            with self.assertRaisesRegex(RuntimeError, "remaining authorized budget"):
                sync_labs_lipsync.generate_batch(jobs2, {"influencer": {"sync_labs": {"model": "sync-3"}}})
        self.assertAlmostEqual(sync_labs_lipsync._RESERVED_USD, 4.0 * 0.133, places=6)

    def test_unknown_or_different_model_is_rejected(self):
        job = {"id": "horizontal_00", "audio": Path("audio.wav")}
        with (
            patch.dict(os.environ, {"SYNC_API_KEY": "test-key", "SYNC_LABS_MAX_SPEND_USD_PER_RUN": "10"}),
            patch.object(sync_labs_lipsync, "_duration", return_value=1.0),
            patch.object(sync_labs_lipsync.requests, "post") as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "Unsupported Sync Labs model"):
                sync_labs_lipsync.generate_batch([job], {"influencer": {"sync_labs": {"model": "react-1"}}})
        post.assert_not_called()


class SyncLabsJobTests(unittest.TestCase):
    def test_build_jobs_creates_individual_audio_and_trimmed_video(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "kling.mp4"
        voice = root / "narration.wav"
        source.write_bytes(b"source-video")
        voice.write_bytes(b"narration-audio")
        out = root / "out"
        out.mkdir()

        def fake_run(command, **kwargs):
            target = Path(command[-1])
            target.write_bytes(b"trimmed" * 300)
            return subprocess.CompletedProcess(command, 0)

        plans = {"horizontal": [{
            "kind": "A", "t0": 1.0, "t1": 5.0,
            "look": {"id": "front", "clip": source},
        }]}
        with (
            patch.object(sync_labs_lipsync, "OUT", out),
            patch.object(sync_labs_lipsync, "_duration", side_effect=[4.0, 5.04]),
            patch.object(sync_labs_lipsync.subprocess, "run", side_effect=fake_run) as run,
        ):
            jobs = sync_labs_lipsync.build_jobs(plans, {"horizontal": voice})

        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["audio"].is_file())
        self.assertTrue(jobs[0]["video"].is_file())
        self.assertEqual(jobs[0]["tag"], "horizontal")
        ffmpeg_calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(ffmpeg_calls), 2)
        self.assertTrue(all("stream_loop" not in cmd and "reverse" not in cmd for cmd in ffmpeg_calls))
        self.assertTrue(any("-ss" in cmd for cmd in ffmpeg_calls))


if __name__ == "__main__":
    unittest.main()
