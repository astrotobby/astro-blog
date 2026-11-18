"""Offline tests for long-form voice chunking and optional TTS providers."""

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tts_elevenlabs
import tts_nvidia
from tts_helpers import split_text_chunks


class TextChunkingTests(unittest.TestCase):
    def test_chunks_respect_the_provider_limit_and_preserve_narration(self):
        narration = (
            "The first sentence remains intact. "
            + "The second sentence also stays together. " * 500
        )
        chunks = split_text_chunks(narration, 900)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 900 for chunk in chunks))
        self.assertEqual(" ".join(chunks), " ".join(narration.split()))

    def test_empty_text_returns_no_chunks(self):
        self.assertEqual(split_text_chunks("  \n ", 100), [])


class ElevenLabsChunkingTests(unittest.TestCase):
    @staticmethod
    def _response():
        alignment = {
            "characters": list("Hi there."),
            "character_start_times_seconds": [
                0.10, 0.18, 0.30, 0.38, 0.45, 0.52, 0.60, 0.68, 0.76
            ],
            "character_end_times_seconds": [
                0.17, 0.25, 0.37, 0.44, 0.51, 0.59, 0.67, 0.75, 0.88
            ],
        }
        return SimpleNamespace(
            status_code=200,
            headers={},
            text="",
            json=lambda: {
                "audio_base64": base64.b64encode(b"A" * 2048).decode("ascii"),
                "alignment": alignment,
            },
        )

    def test_long_narration_is_split_and_word_timings_are_offset(self):
        narration = "Sentence one is clear. " + "Sentence two remains complete. " * 500
        calls = []

        def fake_concat(parts, output):
            Path(output).write_bytes(b"joined audio" * 200)
            return Path(output)

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "narration.mp3"
            with patch.object(
                tts_elevenlabs, "env",
                side_effect=lambda name, default=None: (
                    "test-key" if name == "ELEVENLABS_API_KEY" else default
                ),
            ):
                with patch.object(
                    tts_elevenlabs.requests, "post",
                    side_effect=lambda *args, **kwargs: (
                        calls.append(kwargs["json"]["text"]) or self._response()
                    ),
                ):
                    with patch.object(
                        tts_elevenlabs, "audio_duration", side_effect=[5.0, 5.5]
                    ):
                        with patch.object(
                            tts_elevenlabs, "concat_audio_files", side_effect=fake_concat
                        ):
                            result = tts_elevenlabs.synthesize(narration, output)

            self.assertTrue(output.exists())
            self.assertIsNotNone(result)
            self.assertGreaterEqual(len(calls), 2)
            self.assertTrue(all(len(chunk) <= tts_elevenlabs.MAX_CHUNK_CHARS for chunk in calls))
            words = result[1]
            self.assertGreaterEqual(len(words), 4)
            self.assertGreaterEqual(words[2]["start"], 5.0)


class NVIDIATtsTests(unittest.TestCase):
    def test_magpie_is_opt_in_and_splits_under_the_documented_limit(self):
        narration = "A clear spoken sentence. " * 400
        calls = []
        wav = b"RIFF" + b"\\x00" * 4 + b"WAVE" + b"\\x00" * 2048

        def fake_concat(parts, output):
            Path(output).write_bytes(wav)
            return Path(output)

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "magpie.wav"
            with patch.object(
                tts_nvidia, "env",
                side_effect=lambda name, default=None: {
                    "NVIDIA_API_KEY": "test-nvidia-key",
                    "NVIDIA_TTS_ENABLED": "true",
                    "NVIDIA_TTS_VOICE": "Magpie-Multilingual.EN-US.Jason",
                }.get(name, default),
            ):
                with patch.object(
                    tts_nvidia.requests, "post",
                    side_effect=lambda url, **kwargs: (
                        calls.append((url, kwargs)) or SimpleNamespace(
                            status_code=200, headers={"Content-Type": "audio/wav"},
                            content=wav, text=""
                        )
                    ),
                ):
                    with patch.object(
                        tts_nvidia, "audio_duration",
                        side_effect=[2.0] * 20,
                    ):
                        with patch.object(
                            tts_nvidia, "concat_audio_files", side_effect=fake_concat
                        ):
                            result = tts_nvidia.synthesize(narration, output)

            self.assertEqual(result, output)
            self.assertTrue(output.exists())
            self.assertGreater(len(calls), 1)
            for url, kwargs in calls:
                self.assertEqual(url, tts_nvidia.API)
                self.assertLessEqual(len(kwargs["data"]["text"]), tts_nvidia.MAX_CHUNK_CHARS)
                self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-nvidia-key")

    def test_magpie_is_disabled_without_manual_dry_run_flag(self):
        with patch.object(
            tts_nvidia, "env",
            side_effect=lambda name, default=None: (
                "test-key" if name == "NVIDIA_API_KEY" else default
            ),
        ):
            with patch.object(tts_nvidia.requests, "post") as post:
                self.assertIsNone(tts_nvidia.synthesize("Hello world.", "/tmp/not-used.wav"))
                post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
