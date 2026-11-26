import json
import unittest
from unittest.mock import Mock

from kaggle_mcp_download_output import (
    _find_download_url,
    _find_int,
    _parse_rpc_response,
    _result_value,
)


class KaggleMcpDownloadOutputTests(unittest.TestCase):
    def test_extracts_kernel_version_from_metadata(self):
        value = {
            "metadata": {
                "current_version_number": 17,
                "slug": "musetalk-preview",
            }
        }
        self.assertEqual(
            _find_int(
                value,
                {"currentVersionNumber", "current_version_number", "versionNumber", "version_number"},
            ),
            17,
        )

    def test_extracts_signed_download_url_from_redirect(self):
        url = "https://storage.googleapis.com/private-output/signed?token=abc"
        self.assertEqual(
            _find_download_url({"redirect": {"url": url}}),
            url,
        )

    def test_extracts_signed_download_url_from_text_content(self):
        url = "https://storage.googleapis.com/output/file.mp4?signature=secret"
        result = {"content": [{"type": "text", "text": json.dumps({"url": url})}]}
        self.assertEqual(_find_download_url(_result_value(result)), url)

    def test_parses_mcp_streamable_http_event(self):
        class FakeStreamingResponse:
            status_code = 200
            headers = {"content-type": "text/event-stream"}

            def __init__(self):
                self.closed = False

            def raise_for_status(self):
                return None

            def iter_lines(self, decode_unicode=True):
                yield b"event: message"
                yield (
                    b'data: {"jsonrpc":"2.0","id":2,'
                    b'"result":{"content":[{"type":"text","text":"ok"}]}}'
                )
                raise AssertionError("Parser should stop after the matching JSON-RPC event.")

            def close(self):
                self.closed = True

        response = FakeStreamingResponse()
        result = _parse_rpc_response(response, 2)
        self.assertEqual(result["content"][0]["text"], "ok")
        self.assertTrue(response.closed)

    def test_rejects_mismatched_json_rpc_id(self):
        response = Mock()
        response.status_code = 200
        response.headers = {"content-type": "application/json"}
        response.json.return_value = {"jsonrpc": "2.0", "id": 99, "result": {}}
        response.raise_for_status.return_value = None

        response.close.return_value = None
        with self.assertRaises(RuntimeError):
            _parse_rpc_response(response, 2)
        response.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
