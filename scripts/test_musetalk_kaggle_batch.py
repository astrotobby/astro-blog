"""Unit tests for the private Kaggle MuseTalk batch runner."""
from __future__ import annotations

import contextlib
import json
import io
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import musetalk_kaggle_batch as batch


class MuseTalkKaggleBatchTests(unittest.TestCase):
    def test_missing_kaggle_token_fails_closed_before_remote_calls(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(batch, "_run") as kaggle_call:
                with self.assertRaisesRegex(RuntimeError, "KAGGLE_API_TOKEN is missing"):
                    batch.generate_batch([])
                kaggle_call.assert_not_called()

    def test_explicit_username_avoids_kaggle_config_lookup(self):
        with patch.dict(os.environ, {"KAGGLE_USERNAME": "AstroTobby"}, clear=True):
            with patch.object(batch.subprocess, "run") as command:
                self.assertEqual(batch._username(), "astrotobby")
                command.assert_not_called()

    def test_config_lookup_extracts_username_without_printing_config(self):
        private_config = (
            "username: astrotobby\n"
            "key: DO_NOT_PRINT_THIS_VALUE\n"
            "access_token: DO_NOT_PRINT_THIS_VALUE_TOO\n"
        )
        completed = SimpleNamespace(returncode=0, stdout=private_config, stderr="")
        captured = io.StringIO()
        with patch.dict(os.environ, {"KAGGLE_USERNAME": ""}, clear=True):
            with patch.object(batch.subprocess, "run", return_value=completed) as command:
                with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                    self.assertEqual(batch._username(), "astrotobby")
        command.assert_called_once()
        self.assertNotIn("DO_NOT_PRINT_THIS_VALUE", captured.getvalue())

    def test_dataset_readiness_retries_transient_403_after_successful_upload(self):
        denied = SimpleNamespace(returncode=1, stdout="", stderr="403 Forbidden. You don't have access to this resource.")
        visible = SimpleNamespace(returncode=0, stdout="presenter_0.mp4 narration_0.wav musetalk_manifest.json", stderr="")
        with patch.object(batch, "_run", side_effect=[denied, visible]) as command:
            with patch.object(batch.time, "sleep") as sleep:
                batch._wait_for_dataset("astrotobby/musetalk-input-test", {"presenter_0.mp4", "narration_0.wav", "musetalk_manifest.json"})
        self.assertEqual(command.call_count, 2)
        sleep.assert_called_once_with(10)

    def test_dataset_readiness_403_times_out_after_bounded_retries(self):
        denied = SimpleNamespace(returncode=1, stdout="", stderr="403 Forbidden. You don't have access to this resource.")
        with patch.object(batch, "_run", return_value=denied) as command:
            with patch.object(batch.time, "sleep"):
                with self.assertRaisesRegex(TimeoutError, "within five minutes"):
                    batch._wait_for_dataset("astrotobby/musetalk-input-test", {"presenter_0.mp4"})
        self.assertEqual(command.call_count, 30)

    def test_probe_accepts_only_preview_matched_25fps_output(self):
        payload = {
            "streams": [
                {"codec_type": "video", "width": 720, "height": 1280, "avg_frame_rate": "25/1"},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "4.6"},
        }
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "musetalk_preview_0.mp4"
            video.write_bytes(b"x" * 120_000)
            result = SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            with patch.object(batch.subprocess, "run", return_value=result):
                media = batch._probe(video)
        self.assertEqual(media["fps"], 25.0)
        self.assertEqual(media["resolution"], "720x1280")

    def test_probe_rejects_output_with_non_preview_frame_rate(self):
        payload = {
            "streams": [
                {"codec_type": "video", "width": 720, "height": 1280, "avg_frame_rate": "24/1"},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "4.6"},
        }
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "musetalk_preview_0.mp4"
            video.write_bytes(b"x" * 120_000)
            result = SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            with patch.object(batch.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(RuntimeError, "preview cadence of 25 fps"):
                    batch._probe(video)

    def test_username_parser_rejects_unexpected_account_format(self):
        with patch.dict(os.environ, {"KAGGLE_USERNAME": "bad/owner"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "invalid account username"):
                batch._username()


if __name__ == "__main__":
    unittest.main()
