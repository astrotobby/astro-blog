"""Unit tests for the private Kaggle MuseTalk batch runner."""
from __future__ import annotations

import contextlib
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

    def test_username_parser_rejects_unexpected_account_format(self):
        with patch.dict(os.environ, {"KAGGLE_USERNAME": "bad/owner"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "invalid account username"):
                batch._username()


if __name__ == "__main__":
    unittest.main()
