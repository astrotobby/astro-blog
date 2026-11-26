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
        class FakeResponse:
            status_code = 200
            headers = {"content-type": "text/event-stream"}
            text = (
                'event: message\n'
                'data: {"jsonrpc":"2.0","id":2,'
                '"result":{"content":[{"type":"text","text":"ok"}]}}\n'
            )

            def __init__(self):
                self.closed = False

            def raise_for_status(self):
                return None

            def close(self):
                self.closed = True

        response = FakeResponse()
        result = _parse_rpc_response(response, 2)
        self.assertEqual(result["content"][0]["text"], "ok")
        self.assertTrue(response.closed)

    def test_explains_missing_kaggle_mcp_permission_with_kgat_token_remediation(self):
        class FakeResponse:
            status_code = 200
            headers = {"content-type": "application/json"}

            def __init__(self):
                self.closed = False

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "isError": True,
                        "content": [{
                            "type": "text",
                            "text": "Permission 'kernels.get' was denied",
                        }],
                    },
                }

            def close(self):
                self.closed = True

        with self.assertRaisesRegex(RuntimeError, "KGAT_"):
            _parse_rpc_response(FakeResponse(), 1)

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
