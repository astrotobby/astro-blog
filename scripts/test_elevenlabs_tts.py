"""Offline tests for chunked ElevenLabs long-form synthesis and word timing."""
import base64
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tts_elevenlabs as tts


class TextChunkTests(unittest.TestCase):
    def test_long_narration_is_split_under_limit_without_losing_words(self):
        source = " ".join(["A sentence ends here."] * 600)
        chunks = tts.split_text(source)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= tts.MAX_CHARS_PER_REQUEST for chunk in chunks))
        self.assertEqual(" ".join(chunks), source)

    def test_long_sentence_splits_at_word_boundaries(self):
        source = " ".join(["word"] * 2500)
        chunks = tts.split_text(source, max_chars=100)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))
        self.assertEqual(" ".join(chunks), source)

    def test_empty_text_and_single_short_text(self):
        self.assertEqual(tts.split_text("  "), [])
        self.assertEqual(tts.split_text("Hello there."), ["Hello there."])


class AlignmentTests(unittest.TestCase):
    def test_character_alignment_is_grouped_into_words(self):
        alignment = {
            "characters": ["H", "i", " ", "t", "h", "e", "r", "e", "."],
            "character_start_times_seconds": [0, .1, .2, .3, .4, .5, .6, .7, .8],
            "character_end_times_seconds": [.1, .2, .2, .4, .5, .6, .7, .8, .9],
        }
        self.assertEqual(tts.alignment_to_words(alignment), [
            {"text": "Hi", "start": 0.0, "end": 0.2},
            {"text": "there.", "start": 0.3, "end": 0.9},
        ])


class LongFormSynthesisTests(unittest.TestCase):
    def test_chunks_are_synthesized_joined_and_timings_are_offset(self):
        api_audio = base64.b64encode(b"x" * 4096).decode("ascii")
        alignment = {
            "characters": ["H", "i"],
            "character_start_times_seconds": [0.0, 0.1],
            "character_end_times_seconds": [0.1, 0.2],
        }
        response = SimpleNamespace(
            status_code=200,
            headers={},
            json=lambda: {"audio_base64": api_audio, "alignment": alignment},
        )
        calls = []

        def fake_post(url, **kwargs):
            calls.append(kwargs["json"]["text"])
            return response

        def fake_run(command, **kwargs):
            if command[0] == "ffprobe":
                index = len([x for x in command if x.endswith(".mp3")])
                return SimpleNamespace(stdout="1.5\n")
            output = Path(command[-1])
            output.write_bytes(b"combined-mp3" * 500)
            return SimpleNamespace(stdout="", stderr="", returncode=0)

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "voice.mp3"
            with patch.object(tts, "env", side_effect=lambda name, default=None:
                              "test-elevenlabs-key" if name == "ELEVENLABS_API_KEY" else default):
                with patch.object(tts.requests, "post", side_effect=fake_post):
                    with patch.object(tts.subprocess, "run", side_effect=fake_run):
                        result = tts.synthesize(" ".join(["Hello."] * 1500), output)

            self.assertIsNotNone(result)
            path, words = result
            self.assertEqual(path, output)
            self.assertTrue(path.exists())
            self.assertGreater(len(calls), 1)
            self.assertTrue(all(len(part) <= tts.MAX_CHARS_PER_REQUEST for part in calls))
            self.assertEqual(len(words), len(calls) * 1)
            self.assertAlmostEqual(words[0]["start"], 0.0)
            self.assertAlmostEqual(words[1]["start"], 1.5)
            self.assertEqual(words[-1]["text"], "Hi")

    def test_no_key_skips_without_network_request(self):
        with patch.object(tts, "env", side_effect=lambda name, default=None: default):
            with patch.object(tts.requests, "post") as post:
                self.assertIsNone(tts.synthesize("A sentence.", "unused.mp3"))
                post.assert_not_called()

    def test_failed_chunk_returns_none_and_does_not_create_output(self):
        response = SimpleNamespace(status_code=400, headers={}, text="text_too_long")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "voice.mp3"
            with patch.object(tts, "env", side_effect=lambda name, default=None:
                              "test-key" if name == "ELEVENLABS_API_KEY" else default):
                with patch.object(tts.requests, "post", return_value=response):
                    self.assertIsNone(tts.synthesize("A sentence.", output))
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
