"""Offline tests for NVIDIA Magpie's optional word-timed synthesis adapter."""
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tts_nvidia_riva as tts


class SplitTextTests(unittest.TestCase):
    def test_splits_only_at_sentence_or_word_boundaries_and_preserves_text(self):
        source = "First sentence is here. Second sentence has several words and details."
        chunks = tts.split_text(source, max_chars=28)
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 28 for chunk in chunks))
        self.assertEqual(" ".join(chunks), source)
        self.assertTrue(chunks[0].endswith("."))

    def test_empty_text_returns_no_chunks(self):
        self.assertEqual(tts.split_text("  "), [])


class WordTimingTests(unittest.TestCase):
    def test_riva_milliseconds_are_converted_to_seconds_with_chunk_offset(self):
        response = SimpleNamespace(meta=SimpleNamespace(words=[
            SimpleNamespace(word="Accurate", start_time=120, end_time=430),
            SimpleNamespace(word="captions.", start_time=450, end_time=910),
        ]))
        words = tts.response_word_timings(response, offset_seconds=4.5)
        self.assertEqual(words, [
            {"text": "Accurate", "start": 4.62, "end": 4.93},
            {"text": "captions.", "start": 4.95, "end": 5.41},
        ])

    def test_empty_word_metadata_is_safe(self):
        self.assertEqual(tts.response_word_timings(SimpleNamespace(meta=None)), [])


class MagpieIntegrationTests(unittest.TestCase):
    def test_missing_api_key_skips_without_importing_riva(self):
        with patch.object(tts, "env", side_effect=lambda name, default=None: default):
            self.assertIsNone(tts.synthesize("A complete sentence.", "unused.wav"))

    def test_synthesis_writes_wav_and_offsets_each_text_chunk(self):
        calls = []

        class FakeService:
            def synthesize(self, text, voice, language, **kwargs):
                calls.append((text, voice, language, kwargs))
                word = text.split()[0].strip(".!?")
                return SimpleNamespace(
                    audio=b"\x01\x00" * 2205,  # 0.1s mono PCM at 22,050 Hz
                    meta=SimpleNamespace(words=[
                        SimpleNamespace(word=word, start_time=10, end_time=80)
                    ]),
                )

        fake_riva = ModuleType("riva")
        fake_client = ModuleType("riva.client")
        fake_proto = ModuleType("riva.client.proto")
        fake_audio = ModuleType("riva.client.proto.riva_audio_pb2")
        fake_audio.AudioEncoding = SimpleNamespace(LINEAR_PCM=1)
        fake_service = FakeService()
        captured = {}

        def fake_auth(**kwargs):
            captured.update(kwargs)
            return object()

        fake_client.Auth = fake_auth
        fake_client.SpeechSynthesisService = lambda auth: fake_service
        fake_riva.client = fake_client

        fake_modules = {
            "riva": fake_riva,
            "riva.client": fake_client,
            "riva.client.proto": fake_proto,
            "riva.client.proto.riva_audio_pb2": fake_audio,
        }
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "voice.wav"
            with patch.object(tts, "env", side_effect=lambda name, default=None: {
                "NVIDIA_API_KEY": "test-key",
                "NVIDIA_TTS_FUNCTION_ID": "test-function",
                "NVIDIA_TTS_VOICE": "Magpie-Multilingual.EN-US.Jason",
            }.get(name, default)):
                with patch.object(tts, "split_text", return_value=["First.", "Second."]):
                    with patch.dict(sys.modules, fake_modules):
                        result = tts.synthesize("First. Second.", output)

            self.assertIsNotNone(result)
            path, words = result
            self.assertEqual(path, output)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][0], "First.")
            self.assertEqual(calls[1][0], "Second.")
            self.assertEqual(calls[0][1], "Magpie-Multilingual.EN-US.Jason")
            self.assertEqual(calls[0][2], "en-US")
            self.assertTrue(calls[0][3]["enable_word_time_offsets"])
            self.assertEqual(captured["uri"], "grpc.nvcf.nvidia.com:443")
            self.assertEqual(captured["metadata_args"][0], ("function-id", "test-function"))
            self.assertEqual(captured["metadata_args"][1], ("authorization", "Bearer test-key"))
            self.assertEqual([word["text"] for word in words], ["First", "Second"])
            self.assertAlmostEqual(words[1]["start"], 0.28, places=2)
            with wave.open(str(output), "rb") as audio_file:
                self.assertEqual(audio_file.getnchannels(), 1)
                self.assertEqual(audio_file.getsampwidth(), 2)
                self.assertEqual(audio_file.getframerate(), 22050)
                self.assertGreater(audio_file.getnframes(), 0)

    def test_provider_error_fails_open_and_removes_partial_output(self):
        fake_riva = ModuleType("riva")
        fake_client = ModuleType("riva.client")
        fake_proto = ModuleType("riva.client.proto")
        fake_audio = ModuleType("riva.client.proto.riva_audio_pb2")
        fake_audio.AudioEncoding = SimpleNamespace(LINEAR_PCM=1)
        fake_client.Auth = lambda **kwargs: object()

        class BrokenService:
            def synthesize(self, *args, **kwargs):
                raise RuntimeError("provider unavailable")

        fake_client.SpeechSynthesisService = lambda auth: BrokenService()
        fake_riva.client = fake_client
        fake_modules = {
            "riva": fake_riva,
            "riva.client": fake_client,
            "riva.client.proto": fake_proto,
            "riva.client.proto.riva_audio_pb2": fake_audio,
        }
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "failed.wav"
            with patch.object(tts, "env", side_effect=lambda name, default=None:
                              "test-key" if name == "NVIDIA_API_KEY" else default):
                with patch.dict(sys.modules, fake_modules):
                    result = tts.synthesize("A sentence.", output)
            self.assertIsNone(result)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
