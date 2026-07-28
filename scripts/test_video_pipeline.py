"""Regression tests for the footage-first blog-to-video contract.

Run from the repository root:
    python3 -m unittest scripts/test_video_pipeline.py
"""
import copy
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_script  # noqa: E402
import generate_video  # noqa: E402
from common import load_config  # noqa: E402


class FootageBriefTests(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(load_config())
        self.cfg["visuals"]["scenes"] = 7
        self.cfg["script"]["target_seconds"] = 40
        self.post = {
            "slug": "llm-data-centers",
            "title": "Why LLM Inference Is Changing Data Centers",
            "description": "AI companies are investing in inference infrastructure and GPU capacity.",
            "body": (
                "A data center needs efficient cooling for GPU workloads. "
                "The new model benchmarks are changing how teams deploy software. "
                "Analysts estimate a 40% increase in computing demand. "
                "That creates a workflow challenge for engineering teams."
            ),
            "url": "https://example.test/blog/llm-data-centers",
            "tags": ["AI"],
        }

    def test_scene_metadata_contains_concrete_footage_queries(self):
        prompts = build_script.make_scenes(self.post, self.cfg)
        self.assertEqual(len(prompts), self.cfg["visuals"]["scenes"])
        self.assertTrue(all("|broll:" in prompt and "|fallback:" in prompt for prompt in prompts))
        # A technology story should search visible computing infrastructure, not a
        # broad article title or generic scenery.
        self.assertTrue(any("data center" in prompt or "software developer" in prompt
                            for prompt in prompts))
        self.assertFalse(any("theme:" in prompt for prompt in prompts))

    def test_real_world_concepts_override_generic_ai_filler(self):
        primary, fallback = build_script._footage_brief(
            "A smart thermostat learns from an intelligent environment.", "general_ai", "EXPLAIN"
        )
        self.assertEqual(primary, "smart home thermostat")
        self.assertNotEqual(primary, fallback)

    def test_renderer_parses_scene_brief_and_stat(self):
        prompt = (
            "test prompt, scene_type:DATA|kb:static|dur:1.20"
            "|broll:financial data charts screen|fallback:business analytics dashboard"
            "|stat:Revenue increased by 42 percent"
        )
        meta = generate_video._parse_scene_meta(prompt)
        self.assertEqual(meta["scene_type"], "DATA")
        self.assertEqual(meta["broll"], "financial data charts screen")
        self.assertEqual(meta["fallback"], "business analytics dashboard")
        self.assertEqual(meta["stat"], "Revenue increased by 42 percent")

    def test_pexels_results_prefer_target_aspect_ratio(self):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "videos": [
                        {
                            "id": 1,
                            "user": {"name": "Wide"},
                            "url": "https://pexels.test/1",
                            "video_files": [{
                                "link": "https://cdn.test/wide.mp4",
                                "width": 1920,
                                "height": 1080,
                                "file_type": "video/mp4",
                            }],
                        },
                        {
                            "id": 2,
                            "user": {"name": "Tall"},
                            "url": "https://pexels.test/2",
                            "video_files": [{
                                "link": "https://cdn.test/tall.mp4",
                                "width": 1080,
                                "height": 1920,
                                "file_type": "video/mp4",
                            }],
                        },
                    ]
                }

        with TemporaryDirectory() as temporary_dir:
            cache_file = Path(temporary_dir) / "footage_cache.json"
            with (
                patch.object(generate_video, "FOOTAGE_CACHE_FILE", cache_file),
                patch.object(generate_video, "_search_cache", {}),
                patch.object(generate_video, "env", return_value="redacted-test-key"),
                patch.object(generate_video.requests, "get", return_value=FakeResponse()) as request_get,
            ):
                candidates = generate_video._pexels_video_search("data center servers", 1080, 1920)
                cached_candidates = generate_video._pexels_video_search("data center servers", 1080, 1920)
        self.assertEqual(candidates[0]["id"], "pexels:2")
        self.assertEqual(candidates[0]["query"], "data center servers")
        self.assertEqual(cached_candidates, candidates)
        self.assertEqual(request_get.call_count, 1)

    def test_fetch_assets_uses_each_master_dimensions(self):
        script = {
            "post": {"slug": "format-test", "image_url": ""},
            "scene_prompts": [
                "scene one, scene_type:HOOK|kb:punch_in|dur:0.60|broll:software developer laptop|fallback:data center servers",
                "scene two, scene_type:CTA|kb:gentle_zoom|dur:1.20|broll:technology office team|fallback:software developer laptop",
            ],
        }
        cfg = {"video": {"vertical": {"w": 1080, "h": 1920}, "horizontal": {"w": 1920, "h": 1080}}}
        result = (Path("/tmp/scene.mp4"), {"scene_type": "HOOK"}, None)
        with patch.object(generate_video, "_fetch_scene", return_value=result) as fetch:
            assets, sources = generate_video.fetch_scene_assets(script, cfg, "horizontal")
        self.assertEqual(len(assets), 2)
        self.assertEqual(sources, [])
        self.assertEqual(fetch.call_args_list[0].args[2:4], (1920, 1080))
        self.assertEqual(fetch.call_args_list[0].args[-1], "horizontal")

    def test_youtube_description_includes_distinct_asset_credits(self):
        platform = {"yt_desc": "Read the full post."}
        sources = [
            {"id": "pexels:1", "provider": "Pexels", "creator": "Ava", "source_url": "https://pexels.test/1"},
            {"id": "pexels:1", "provider": "Pexels", "creator": "Ava", "source_url": "https://pexels.test/1"},
            {"id": "pixabay:2", "provider": "Pixabay", "creator": "Ben", "source_url": "https://pixabay.test/2"},
        ]
        credited = generate_video._with_attribution(platform, sources)
        self.assertEqual(len(credited["footage_credits"]), 2)
        self.assertIn("Footage credits:", credited["yt_desc"])
        self.assertIn("Pexels: Ava", credited["yt_desc"])
        self.assertIn("Pixabay: Ben", credited["yt_desc"])


if __name__ == "__main__":
    unittest.main()
