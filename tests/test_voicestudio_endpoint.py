"""Tests for local and remote VoiceStudio API base URL handling."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_video import _voicestudio_speech_url


class VoiceStudioEndpointTests(unittest.TestCase):
    def test_root_base_url_gets_v1_prefix(self):
        self.assertEqual(_voicestudio_speech_url("http://127.0.0.1:3900"),
                         "http://127.0.0.1:3900/v1/audio/speech")

    def test_base_url_already_ending_in_v1_is_not_duplicated(self):
        self.assertEqual(_voicestudio_speech_url("http://localhost:3900/v1"),
                         "http://localhost:3900/v1/audio/speech")

    def test_trailing_slash_is_normalized(self):
        self.assertEqual(_voicestudio_speech_url("https://voice.example/v1/"),
                         "https://voice.example/v1/audio/speech")


if __name__ == "__main__":
    unittest.main()
