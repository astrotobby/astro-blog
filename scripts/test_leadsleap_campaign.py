import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from leadsleap_campaign import (
    campaign_active,
    campaign_day,
    load_json,
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


if __name__ == "__main__":
    unittest.main()
