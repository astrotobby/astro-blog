"""Local HTTP tests for the per-run MuseTalk output relay."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from musetalk_output_relay import OutputRelay


class MuseTalkOutputRelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="musetalk-relay-test-")
        self.root = Path(self.temp.name)
        self.filename = "musetalk_preview_0.mp4"
        self.relay = OutputRelay(
            {self.filename},
            self.root,
            max_upload_bytes=2 * 1024 * 1024,
        )
        self.local_url = self.relay.start_local()
        self.payload = (b"synthetic-mp4-payload-" * 7000)[:140_000]
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def tearDown(self):
        self.relay.close()
        self.temp.cleanup()

    def _request(self, filename=None, token=None, digest=None, body=None):
        filename = filename or self.filename
        token = self.relay.token if token is None else token
        digest = self.digest if digest is None else digest
        body = self.payload if body is None else body
        request = Request(
            f"{self.local_url}/upload/{self.relay.route}/{filename}",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "video/mp4",
                "X-Content-SHA256": digest,
            },
            method="PUT",
        )
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_accepts_allowlisted_upload_with_valid_bearer_and_digest(self):
        status, receipt = self._request()
        saved = self.root / self.filename
        self.assertEqual(status, 201)
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.read_bytes(), self.payload)
        self.assertEqual(receipt["sha256"], self.digest)
        self.assertEqual(receipt["file"], self.filename)

    def test_rejects_request_without_valid_bearer_token(self):
        with self.assertRaises(HTTPError) as caught:
            self._request(token="wrong-token")
        self.assertEqual(caught.exception.code, 401)
        self.assertFalse((self.root / self.filename).exists())

    def test_rejects_filename_not_in_the_run_allowlist(self):
        with self.assertRaises(HTTPError) as caught:
            self._request(filename="other.mp4")
        self.assertEqual(caught.exception.code, 404)

    def test_rejects_invalid_sha256_without_creating_output_file(self):
        with self.assertRaises(HTTPError) as caught:
            self._request(digest="0" * 64)
        self.assertEqual(caught.exception.code, 400)
        self.assertFalse((self.root / self.filename).exists())

    def test_rejects_oversized_file_before_writing(self):
        oversized = b"x" * (2 * 1024 * 1024 + 1)
        with self.assertRaises(HTTPError) as caught:
            self._request(body=oversized, digest=hashlib.sha256(oversized).hexdigest())
        self.assertEqual(caught.exception.code, 413)
        self.assertFalse((self.root / self.filename).exists())


if __name__ == "__main__":
    unittest.main()
