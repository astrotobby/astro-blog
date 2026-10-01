import json
import tempfile
import unittest
from pathlib import Path

from whop_pipeline import Campaign, ClipSpec, StateStore, build_submission_packet, score_campaign, validate_clips


class WhopPipelineTests(unittest.TestCase):
    def setUp(self):
        self.campaign = Campaign.from_dict({
            "campaign_id": "camp-1", "title": "AI Podcast Clipping", "campaign_url": "https://contentrewards.com/discover/camp-1",
            "allowed_platforms": ["youtube", "instagram"], "reward_per_1000_views": 3, "remaining_budget": 2000,
            "source_material_urls": ["https://example.com/source.mp4"], "requirements": ["captions", "9:16"],
        })

    def test_campaign_normalization_rejects_non_https(self):
        with self.assertRaises(ValueError):
            Campaign.from_dict({"campaign_id": "x", "title": "X", "campaign_url": "http://bad"})

    def test_score_is_explainable(self):
        result = score_campaign(self.campaign, {"youtube"}, preferred_platform="youtube", creator_terms=["AI", "podcast"])
        self.assertGreater(result["score"], 50)
        self.assertIn("platform_fit", result["components"])
        self.assertTrue(result["reasons"])

    def test_validate_clips_rejects_overlap_and_accepts_safe_ranges(self):
        valid = validate_clips([
            {"start_time": 0, "end_time": 30, "platform": "youtube", "caption": "One", "source_asset_hash": "h"},
            {"start_time": 40, "end_time": 70, "platform": "youtube", "caption": "Two", "source_asset_hash": "h"},
        ], 100, self.campaign)
        self.assertEqual(len(valid), 2)
        with self.assertRaises(ValueError):
            validate_clips([
                {"start_time": 0, "end_time": 30, "platform": "youtube", "caption": "One"},
                {"start_time": 20, "end_time": 50, "platform": "youtube", "caption": "Two"},
            ], 100, self.campaign)

    def test_state_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(Path(td) / "state.json")
            self.assertTrue(store.put_once("k", {"ok": True}))
            self.assertFalse(store.put_once("k", {"ok": False}))
            self.assertEqual(store.load()["items"]["k"]["ok"], True)

    def test_submission_packet_requires_public_post_urls(self):
        clips = [ClipSpec(0, 30, "youtube", caption="Caption", source_asset_hash="h", post_url="https://youtube.com/shorts/x")]
        packet = build_submission_packet(self.campaign, clips)
        self.assertEqual(packet["status"], "ready_for_manual_whop_submission")
        self.assertTrue(packet["checklist"]["public_post_urls_present"])
        self.assertTrue(packet["checklist"]["manual_whop_submission_required"])


if __name__ == "__main__":
    unittest.main()
