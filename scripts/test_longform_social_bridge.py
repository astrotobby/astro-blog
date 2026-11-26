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


class LongformSocialSessionTests(unittest.TestCase):
    def test_github_actions_token_is_attached_to_release_polling_session(self):
        with patch.dict("os.environ", {"GH_TOKEN": "test-workflow-token"}, clear=False):
            session = longform_social_bridge._github_session()
        self.assertEqual(
            session.headers.get("Authorization"),
            "Bearer test-workflow-token",
        )
        self.assertEqual(
            session.headers.get("Accept"),
            "application/vnd.github+json",
        )


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


class LongformSocialDestinationSafetyTests(unittest.TestCase):
    def test_manual_rumble_handoff_does_not_call_automated_publisher(self):
        video_url = "https://github.com/astrotobby/AI-GEMS/releases/download/test/video_16x9.mp4"
        render = {"post": {"url": "https://youtu.be/test-video"}}
        with patch.object(longform_social_bridge, "_post_one") as post_one:
            result = longform_social_bridge._publish_destination(
                "rumble",
                render,
                {},
                False,
                Path("master-16x9.mp4"),
                "test-job",
                {"browser_download_url": video_url},
            )

        post_one.assert_not_called()
        self.assertTrue(result["manual_handoff"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["video_url"], video_url)
        self.assertEqual(result["youtube_url"], "https://youtu.be/test-video")

    def test_manual_handoff_is_done_for_poller_but_not_claimed_as_published(self):
        self.assertTrue(
            longform_social_bridge._destination_done(
                {"ok": False, "manual_handoff": True}
            )
        )
        self.assertTrue(longform_social_bridge._destination_done({"ok": True}))
        self.assertFalse(
            longform_social_bridge._destination_done(
                {"ok": False, "error": "temporary failure"}
            )
        )
        self.assertFalse(longform_social_bridge._destination_done(None))

    def test_revoked_facebook_token_is_detected(self):
        self.assertTrue(
            longform_social_bridge._facebook_token_invalid({
                "error": "Facebook resumable upload HTTP 400: "
                         "{'code': 190, 'error_subcode': 460, "
                         "'message': 'The session has been invalidated'}"
            })
        )
        self.assertFalse(
            longform_social_bridge._facebook_token_invalid({
                "error": "Facebook upload failed due to a temporary network error"
            })
        )

    def test_facebook_block_applies_only_to_the_same_credential_fingerprint(self):
        with patch.dict("os.environ", {
            "FACEBOOK_PAGE_ID": "page-123",
            "FACEBOOK_PAGE_TOKEN": "invalid-token",
        }):
            fingerprint = longform_social_bridge._facebook_credential_fingerprint()
            state = {"destination_blocks": {
                "facebook": {"fingerprint": fingerprint, "reason": "reauthorize"}
            }}
            self.assertTrue(longform_social_bridge._destination_blocked(state, "facebook"))
            self.assertTrue(longform_social_bridge._destination_done(None, "facebook", state))
        with patch.dict("os.environ", {
            "FACEBOOK_PAGE_ID": "page-123",
            "FACEBOOK_PAGE_TOKEN": "new-token",
        }):
            self.assertFalse(longform_social_bridge._destination_blocked(state, "facebook"))
            self.assertFalse(longform_social_bridge._destination_done(None, "facebook", state))


    def test_longform_destinations_exclude_instagram(self):
        self.assertEqual(longform_social_bridge.DESTINATIONS, ("facebook", "rumble"))

    def test_instagram_is_explicitly_rejected_for_longform(self):
        render = {"post": {"url": "https://youtu.be/test-video"}}
        with patch.object(longform_social_bridge, "_post_one") as post_one:
            result = longform_social_bridge._publish_destination(
                "instagram", render, {}, False, Path("master-16x9.mp4"), "test-job", {}
            )
        post_one.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertIn("disabled", result["skipped"])



class FacebookResumableUploadTests(unittest.TestCase):
    class Response:
        def __init__(self, payload, status_code=200):
            import json
            self._payload = payload
            self.status_code = status_code
            self.content = json.dumps(payload).encode("utf-8")
            self.text = self.content.decode("utf-8")

        def json(self):
            return self._payload

    class Requests:
        def __init__(self, responses):
            self.responses = list(responses)
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return self.responses.pop(0)

    def test_page_video_is_uploaded_in_server_directed_chunks(self):
        with TemporaryDirectory() as tmp:
            video = Path(tmp) / "master.mp4"
            video.write_bytes(b"abcdefgh")
            requests = self.Requests([
                self.Response({
                    "upload_session_id": "session-1",
                    "video_id": "video-1",
                    "start_offset": "0",
                    "end_offset": "4",
                }),
                self.Response({"start_offset": "4", "end_offset": "8"}),
                self.Response({"start_offset": "8", "end_offset": "8"}),
                self.Response({"success": True, "video_id": "video-1"}),
            ])

            url = longform_social_bridge.platforms._facebook_resumable_upload(
                requests,
                "https://graph.facebook.com/v27.0/123456/videos",
                "123456",
                "page-token",
                video,
                "Test upload",
            )

        self.assertEqual(url, "https://www.facebook.com/video-1")
        self.assertEqual(len(requests.calls), 4)
        expected_url = "https://graph-video.facebook.com/v27.0/123456/videos"
        self.assertTrue(all(call[0] == expected_url for call in requests.calls))
        self.assertEqual(requests.calls[0][1]["data"]["upload_phase"], "start")
        self.assertEqual(requests.calls[0][1]["data"]["file_size"], "8")
        first_transfer = requests.calls[1][1]
        second_transfer = requests.calls[2][1]
        self.assertEqual(first_transfer["data"]["start_offset"], "0")
        self.assertEqual(first_transfer["data"]["upload_session_id"], "session-1")
        self.assertEqual(first_transfer["files"]["video_file_chunk"][1].getvalue(), b"abcd")
        self.assertEqual(second_transfer["data"]["start_offset"], "4")
        self.assertEqual(second_transfer["files"]["video_file_chunk"][1].getvalue(), b"efgh")
        finish = requests.calls[3][1]["data"]
        self.assertEqual(finish["upload_phase"], "finish")
        self.assertEqual(finish["upload_session_id"], "session-1")
        self.assertEqual(finish["description"], "Test upload")

    def test_skip_upload_session_finishes_without_transfer(self):
        with TemporaryDirectory() as tmp:
            video = Path(tmp) / "master.mp4"
            video.write_bytes(b"video-data")
            requests = self.Requests([
                self.Response({
                    "upload_session_id": "session-2",
                    "video_id": "video-2",
                    "skip_upload": True,
                    "start_offset": "0",
                    "end_offset": "0",
                }),
                self.Response({"success": True, "video_id": "video-2"}),
            ])
            url = longform_social_bridge.platforms._facebook_resumable_upload(
                requests,
                "https://graph.facebook.com/v27.0/123456/videos",
                "123456",
                "page-token",
                video,
                "Existing video",
            )

        self.assertEqual(url, "https://www.facebook.com/video-2")
        self.assertEqual(len(requests.calls), 2)
        self.assertEqual(requests.calls[1][1]["data"]["upload_phase"], "finish")

    def test_rejects_non_advancing_server_offsets(self):
        with TemporaryDirectory() as tmp:
            video = Path(tmp) / "master.mp4"
            video.write_bytes(b"abcdefgh")
            requests = self.Requests([
                self.Response({
                    "upload_session_id": "session-3",
                    "video_id": "video-3",
                    "start_offset": "0",
                    "end_offset": "4",
                }),
                self.Response({"start_offset": "0", "end_offset": "4"}),
            ])
            with self.assertRaisesRegex(RuntimeError, "did not advance"):
                longform_social_bridge.platforms._facebook_resumable_upload(
                    requests,
                    "https://graph.facebook.com/v27.0/123456/videos",
                    "123456",
                    "page-token",
                    video,
                    "Bad offsets",
                )


if __name__ == "__main__":
    unittest.main()
