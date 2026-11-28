"""Unit tests for the private Kaggle MuseTalk batch runner."""
from __future__ import annotations

import contextlib
import json
import io
import os
import subprocess
import tempfile
import unittest

import requests
import sys
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

import musetalk_kaggle_batch as batch


class MuseTalkKaggleBatchTests(unittest.TestCase):
    def test_missing_kaggle_token_fails_closed_before_remote_calls(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(batch, "_run") as kaggle_call:
                with self.assertRaisesRegex(RuntimeError, "KAGGLE_API_TOKEN is missing"):
                    batch.generate_batch([])
                kaggle_call.assert_not_called()

    def test_kaggle_kernel_title_must_resolve_to_submitted_id_slug(self):
        kernel_id = "astrotobby/musetalk-batch-abcdef1234"
        self.assertEqual(
            batch._validate_kernel_title_slug(kernel_id, "musetalk-batch-abcdef1234"),
            "musetalk-batch-abcdef1234",
        )
        with self.assertRaisesRegex(ValueError, "does not resolve to the kernel id slug"):
            batch._validate_kernel_title_slug(
                kernel_id,
                "Private MuseTalk batch abcdef1234",
            )

    def test_kaggle_gpu_session_limit_is_detected_even_when_cli_exits_zero(self):
        rejected = SimpleNamespace(
            returncode=0,
            stdout="Kernel push error: Maximum batch GPU session count of 2 reached.",
            stderr="",
        )
        with patch.object(batch, "_run", return_value=rejected) as command:
            with self.assertRaisesRegex(
                RuntimeError,
                "already has the maximum of two batch GPU sessions active",
            ):
                batch._push_kernel(Path("/tmp/kernel"), "astrotobby/musetalk-batch-abc123")
        command.assert_called_once()
        self.assertFalse(any(
            call.args and call.args[0][:2] == ["kernels", "status"]
            for call in command.call_args_list
        ))

    def test_kernel_push_requires_success_confirmation_not_only_exit_zero(self):
        ambiguous = SimpleNamespace(
            returncode=0,
            stdout="Kernel submitted; waiting",
            stderr="",
        )
        with patch.object(batch, "_run", return_value=ambiguous):
            with self.assertRaisesRegex(RuntimeError, "without confirming"):
                batch._push_kernel(Path("/tmp/kernel"), "astrotobby/musetalk-batch-abc123")

    def test_successful_kernel_push_requires_and_accepts_cli_acknowledgement(self):
        accepted = SimpleNamespace(
            returncode=0,
            stdout="Kernel version 1 successfully pushed. Please check progress.",
            stderr="",
        )
        with patch.object(batch, "_run", return_value=accepted) as command, patch("builtins.print"):
            batch._push_kernel(Path("/tmp/kernel"), "astrotobby/musetalk-batch-abc123")
        command.assert_called_once()

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

    def test_private_kernel_status_permission_uses_signed_relay(self):
        denied = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Cannot access private kernel. Permission 'kernels.get' was denied.",
        )
        with patch.object(batch, "_run", return_value=denied) as command:
            with patch("builtins.print") as output:
                batch._wait_for_kernel(
                    "astrotobby/musetalk-batch-private",
                    relay_available=True,
                )
        command.assert_called_once()
        self.assertTrue(any(
            "output relay as the completion signal" in str(call)
            for call in output.call_args_list
        ))

    def test_private_kernel_status_permission_uses_session_output_without_relay(self):
        denied = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Cannot access private kernel. Permission 'kernels.get' was denied.",
        )
        with patch.object(batch, "_run", return_value=denied) as command:
            with patch("builtins.print") as output:
                completed = batch._wait_for_kernel(
                    "astrotobby/musetalk-batch-private",
                    relay_available=False,
                )
        command.assert_called_once()
        self.assertFalse(completed)
        self.assertTrue(any(
            "Polling the exact private notebook session outputs" in str(call)
            for call in output.call_args_list
        ))

    def test_kernel_status_404_uses_output_relay_instead_of_failing(self):
        unavailable = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="404 Client Error: Not Found for url: GetKernelSessionStatus",
        )
        with patch.object(batch, "_run", return_value=unavailable) as command:
            with patch("builtins.print") as output:
                completed = batch._wait_for_kernel(
                    "astrotobby/musetalk-batch-private",
                    relay_available=True,
                )
        command.assert_called_once()
        self.assertFalse(completed)
        self.assertTrue(any(
            "output relay as the completion signal" in str(call)
            for call in output.call_args_list
        ))

    def test_session_output_polling_retries_until_validated_mp4_arrives(self):
        calls = []

        def fake_download(kernel_id, filename, destination, *, session_only=False):
            calls.append((kernel_id, filename, session_only))
            if len(calls) == 1:
                raise FileNotFoundError("output is not available yet")
            Path(destination).write_bytes(b"x" * 120_000)

        fake_helper = SimpleNamespace(download_output=fake_download)
        with tempfile.TemporaryDirectory() as folder:
            target_dir = Path(folder)
            with (
                patch.dict(sys.modules, {"kaggle_mcp_download_output": fake_helper}),
                patch.object(batch, "_probe", return_value={"fps": 25.0}),
                patch.object(batch.time, "sleep"),
                patch("builtins.print"),
            ):
                batch._wait_for_session_outputs(
                    "astrotobby/musetalk-batch-private",
                    {"musetalk_preview_0.mp4"},
                    target_dir,
                    timeout=120,
                )
            self.assertTrue((target_dir / "musetalk_preview_0.mp4").is_file())
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[2] is True for call in calls))

    def test_session_output_polling_fails_closed_on_auth_error(self):
        def denied_download(kernel_id, filename, destination, *, session_only=False):
            raise RuntimeError("Kaggle MCP authorization denied list session output")

        fake_helper = SimpleNamespace(download_output=denied_download)
        with tempfile.TemporaryDirectory() as folder:
            with (
                patch.dict(sys.modules, {"kaggle_mcp_download_output": fake_helper}),
                patch.object(batch.time, "sleep") as sleep,
            ):
                with self.assertRaisesRegex(RuntimeError, "could not retrieve the private MuseTalk session output"):
                    batch._wait_for_session_outputs(
                        "astrotobby/musetalk-batch-private",
                        {"musetalk_preview_0.mp4"},
                        Path(folder),
                        timeout=120,
                    )
        sleep.assert_not_called()

    def test_mcp_http_404_falls_back_to_official_kaggle_cli_output(self):
        error = requests.HTTPError("404 Client Error: Not Found for url: https://www.kaggle.com/mcp")
        error.response = SimpleNamespace(status_code=404)
        fake_helper = SimpleNamespace(download_output=Mock(side_effect=error))

        def fake_kaggle_run(args, **kwargs):
            self.assertEqual(args[:3], ["kernels", "output", "astrotobby/musetalk-batch-private"])
            self.assertIn("--file-pattern", args)
            (Path(args[args.index("--path") + 1]) / "musetalk_preview_0.mp4").write_bytes(b"x" * 120_000)
            return SimpleNamespace(returncode=0, stdout="downloaded outputs", stderr="")

        with tempfile.TemporaryDirectory() as folder:
            target_dir = Path(folder)
            with (
                patch.dict(sys.modules, {"kaggle_mcp_download_output": fake_helper}),
                patch.object(batch, "_run", side_effect=fake_kaggle_run) as kaggle_call,
                patch.object(batch, "_probe", return_value={"fps": 25.0}),
                patch("builtins.print"),
            ):
                batch._wait_for_session_outputs(
                    "astrotobby/musetalk-batch-private",
                    {"musetalk_preview_0.mp4"},
                    target_dir,
                    timeout=120,
                )
            self.assertTrue((target_dir / "musetalk_preview_0.mp4").is_file())
            kaggle_call.assert_called_once()

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
