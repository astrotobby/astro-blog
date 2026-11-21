"""Regression tests for the AI-GEMS long-form social handoff bridge."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import longform_social_bridge  # noqa: E402


class FakeResponse:
    def __init__(self, chunks, content_length):
        self.chunks = chunks
        self.headers = {"Content-Length": str(content_length)}
        self.status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield from self.chunks


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return self.responses.pop(0)


class LongformSocialDownloadTests(unittest.TestCase):
    def test_incomplete_release_download_is_retried_and_atomically_saved(self):
        expected = 120_000
        broken = FakeResponse([b"x" * 60_000], expected)
        complete = FakeResponse([b"y" * 70_000, b"y" * 50_000], expected)
        session = FakeSession([broken, complete])

        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "longform.mp4"
            with patch.object(longform_social_bridge, "DOWNLOAD_RETRY_SECONDS", 0), \
                 patch.object(longform_social_bridge.time, "sleep"):
                result = longform_social_bridge._download(
                    session,
                    {"browser_download_url": "https://github.com/example/video.mp4",
                     "size": expected},
                    destination,
                )

            self.assertEqual(result, destination)
            self.assertEqual(session.calls, 2)
            self.assertEqual(destination.stat().st_size, expected)
            self.assertEqual(destination.read_bytes(), b"y" * expected)
            self.assertFalse(destination.with_suffix(".mp4.part").exists())


if __name__ == "__main__":
    unittest.main()
