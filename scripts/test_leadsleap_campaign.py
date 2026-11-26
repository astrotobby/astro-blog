import json
import sys
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from leadsleap_campaign import (
    _permanent_block_reason,
    campaign_active,
    campaign_day,
    load_json,
    load_state,
    publish_threads,
    tracked_url,
)


class LeadsLeapCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_json(ROOT / "config" / "leadsleap-campaign.json")

    def test_campaign_has_fourteen_distinct_daily_variants(self):
        posts = self.cfg["posts"]
        self.assertEqual(len(posts), 14)
        for platform in self.cfg["platforms"]:
            messages = [post[platform] for post in posts]
            self.assertTrue(all(message.strip() for message in messages))
            self.assertEqual(len(set(messages)), len(messages))

    def test_campaign_is_limited_to_fourteen_days(self):
        self.assertFalse(campaign_active(self.cfg, date(2026, 11, 21)))
        self.assertTrue(campaign_active(self.cfg, date(2026, 11, 22)))
        self.assertTrue(campaign_active(self.cfg, date(2026, 12, 5)))
        self.assertFalse(campaign_active(self.cfg, date(2026, 12, 6)))

    def test_campaign_day_rotates_deterministically(self):
        index, first = campaign_day(self.cfg, date(2026, 11, 22))
        self.assertEqual(index, 0)
        self.assertEqual(first, self.cfg["posts"][0])
        index, second = campaign_day(self.cfg, date(2026, 11, 23))
        self.assertEqual(index, 1)
        self.assertEqual(second, self.cfg["posts"][1])

    def test_tracking_url_keeps_destination_and_adds_utm(self):
        url = tracked_url(
            self.cfg["landing_url"], "threads", self.cfg["campaign_id"]
        )
        self.assertTrue(url.startswith("https://astrotobby.site/blog/"))
        self.assertIn("utm_source=threads", url)
        self.assertIn("utm_medium=social", url)
        self.assertIn("utm_campaign=leadsleap_free_coop_pilot_14d", url)

    def test_post_lengths_fit_platform_limits(self):
        for post in self.cfg["posts"]:
            x_link = tracked_url(self.cfg["landing_url"], "x", self.cfg["campaign_id"])
            x_text = f"{post['x'].rstrip()}\n{x_link}"
            self.assertLessEqual(len(x_text), 280)
            threads_link = tracked_url(self.cfg["landing_url"], "threads", self.cfg["campaign_id"])
            self.assertLessEqual(len(post["threads"]) + 2 + len(threads_link), 500)

    def test_copy_does_not_claim_unverified_personal_account_results(self):
        forbidden = (
            "my starting dashboard showed",
            "my account showed",
            "my first leadsleap snapshot",
            "i tested the free leadsleap account",
            "$1 every day guaranteed",
        )
        for post in self.cfg["posts"]:
            combined = " ".join(post.values()).lower()
            for phrase in forbidden:
                self.assertNotIn(phrase, combined)

    def test_campaign_links_are_separated(self):
        self.assertIn("lltrco.com", self.cfg["coop_url"])
        self.assertIn("leadsleap.com", self.cfg["affiliate_url"])
        self.assertNotEqual(self.cfg["coop_url"], self.cfg["affiliate_url"])



    def test_permanent_provider_blocks_are_classified_without_hiding_them(self):
        self.assertIn(
            "invalidated",
            _permanent_block_reason(
                "facebook",
                {"error": "Facebook OAuthException code: 190 error_subcode: 460"},
            ),
        )
        self.assertIn(
            "credits are depleted",
            _permanent_block_reason(
                "x",
                {"error": "X publish failed: HTTPException: 402 Payment Required: credits depleted"},
            ),
        )
        self.assertIsNone(
            _permanent_block_reason("threads", {"error": "temporary transport error"})
        )

    def test_blocked_destinations_survive_a_new_campaign_day(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            path.write_text(json.dumps({
                "date": "2026-11-25",
                "posted": {"facebook": {"ok": True, "url": "https://example.test/1"}},
                "blocked": {"x": {"fingerprint": "opaque", "reason": "credits depleted"}},
            }), encoding="utf-8")
            state = load_state(path, date(2026, 11, 26))
        self.assertEqual(state["date"], "2026-11-26")
        self.assertEqual(state["posted"], {})
        self.assertEqual(state["blocked"]["x"]["fingerprint"], "opaque")

    def test_threads_waits_for_container_to_finish_before_publishing(self):
        class Response:
            def __init__(self, body, status_code=200):
                self._body = body
                self.status_code = status_code
                self.content = json.dumps(body).encode("utf-8")

            def json(self):
                return self._body

        post_responses = [
            Response({"id": "container-123"}),
            Response({"id": "post-456"}),
        ]
        get_responses = [
            Response({"id": "container-123", "status": "IN_PROGRESS"}),
            Response({"id": "container-123", "status": "FINISHED"}),
        ]
        with patch.dict("os.environ", {
            "THREADS_USER_ID": "user-1", "THREADS_ACCESS_TOKEN": "test-token"
        }), patch("requests.post", side_effect=post_responses) as post, \
             patch("requests.get", side_effect=get_responses) as get, \
             patch("leadsleap_campaign.time.sleep"):
            result = publish_threads("Test message", "https://example.test")

        self.assertTrue(result["ok"])
        self.assertEqual(result["url"], "https://www.threads.net/t/post-456")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[1].kwargs["data"]["creation_id"], "container-123")
        self.assertIn("\n\n", post.call_args_list[0].kwargs["data"]["text"])

    def test_threads_retries_same_container_after_meta_propagation_error(self):
        class Response:
            def __init__(self, body, status_code=200):
                self._body = body
                self.status_code = status_code
                self.content = json.dumps(body).encode("utf-8")

            def json(self):
                return self._body

        post_responses = [
            Response({"id": "container-123"}),
            Response({"error": {"code": 24, "error_subcode": 4279009,
                                "message": "The media with id cannot be found"}}, 400),
            Response({"id": "post-456"}),
        ]
        get_responses = [
            Response({"id": "container-123", "status": "FINISHED"}),
            Response({"id": "container-123", "status": "FINISHED"}),
        ]
        with patch.dict("os.environ", {
            "THREADS_USER_ID": "user-1", "THREADS_ACCESS_TOKEN": "test-token"
        }), patch("requests.post", side_effect=post_responses) as post, \
             patch("requests.get", side_effect=get_responses), \
             patch("leadsleap_campaign.time.sleep"):
            result = publish_threads("Test message", "https://example.test")

        self.assertTrue(result["ok"])
        self.assertEqual(result["url"], "https://www.threads.net/t/post-456")
        self.assertEqual(post.call_count, 3)
        self.assertEqual(
            post.call_args_list[1].kwargs["data"]["creation_id"],
            post.call_args_list[2].kwargs["data"]["creation_id"],
        )


if __name__ == "__main__":
    unittest.main()
