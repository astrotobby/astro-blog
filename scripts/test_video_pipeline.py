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


    def test_commons_licence_filter_rejects_restrictive_terms(self):
        self.assertEqual(generate_video._commons_license({
            "LicenseShortName": {"value": "CC BY 4.0"}
        }), ("by", "CC BY 4.0"))
        self.assertEqual(generate_video._commons_license({
            "LicenseShortName": {"value": "CC0 1.0"}
        }), ("cc0", "CC0 1.0"))
        self.assertEqual(generate_video._commons_license({
            "LicenseShortName": {"value": "Public domain"}
        }), ("pdm", "Public domain"))
        for licence in ("CC BY-SA 4.0", "CC BY-NC 4.0", "CC BY-ND 4.0", "All rights reserved"):
            self.assertIsNone(generate_video._commons_license({
                "LicenseShortName": {"value": licence}
            })[0], licence)

    def test_commons_search_keeps_only_commercial_safe_attributed_images(self):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            @staticmethod
            def json():
                def page(page_id, license_name):
                    return {
                        "pageid": page_id,
                        "title": f"File:film-production-studio-scene-{page_id}.jpg",
                        "imageinfo": [{
                            "url": f"https://upload.wikimedia.test/{page_id}.jpg",
                            "thumburl": f"https://upload.wikimedia.test/thumb-{page_id}.jpg",
                            "descriptionurl": f"https://commons.wikimedia.org/wiki/File:scene-{page_id}.jpg",
                            "width": 1920,
                            "height": 1080,
                            "extmetadata": {
                                "LicenseShortName": {"value": license_name},
                                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                                "Artist": {"value": "<a>Photographer A</a>"},
                                "ImageDescription": {"value": "A useful scene"},
                            },
                        }],
                    }
                return {"query": {"pages": {
                    "1": page(1, "CC BY 4.0"),
                    "2": page(2, "CC BY-SA 4.0"),
                    "3": page(3, "CC BY-NC 4.0"),
                    "4": page(4, "Public domain"),
                }}}

        with TemporaryDirectory() as temporary_dir:
            cache_file = Path(temporary_dir) / "footage_cache.json"
            with (
                patch.object(generate_video, "FOOTAGE_CACHE_FILE", cache_file),
                patch.object(generate_video, "_search_cache", {}),
                patch.object(generate_video.requests, "get", return_value=FakeResponse()) as request_get,
            ):
                candidates = generate_video._wikimedia_commons_image_search(
                    "film production studio", 1920, 1080
                )
        self.assertEqual({item["id"] for item in candidates},
                         {"wikimedia-commons:1", "wikimedia-commons:4"})
        self.assertEqual(candidates[0]["provider"], "Wikimedia Commons")
        self.assertEqual(candidates[0]["creator"], "Photographer A")
        self.assertIn("creativecommons.org", candidates[0]["license_url"])
        self.assertEqual(request_get.call_count, 1)

    def test_commons_query_broadening_removes_overly_specific_words(self):
        queries = generate_video._commons_search_queries({
            "broll": "record label executive office meeting",
            "fallback": "music industry office"
        })
        self.assertIn("record label executive office meeting", queries)
        self.assertIn("record label executive", queries)
        self.assertIn("music production studio", queries)
        self.assertIn("music executive", queries)
        self.assertLessEqual(len(queries), 7)

    def test_fetch_assets_uses_each_master_dimensions(self):
        script = {
            "post": {"slug": "format-test", "image_url": ""},
            "scene_prompts": [
                "scene one, scene_type:HOOK|kb:punch_in|dur:0.60|broll:software developer laptop|fallback:data center servers",
                "scene two, scene_type:CTA|kb:gentle_zoom|dur:1.20|broll:technology office team|fallback:software developer laptop",
            ],
        }
        cfg = {"video": {"vertical": {"w": 1080, "h": 1920}, "horizontal": {"w": 1920, "h": 1080}}}
        result_one = (Path("/tmp/scene-one.png"), {"scene_type": "HOOK"}, None)
        result_two = (Path("/tmp/scene-two.png"), {"scene_type": "CTA"}, None)
        with (
            patch.object(generate_video, "_load_footage_history", return_value=[]),
            patch.object(generate_video, "_save_footage_history"),
            patch.object(generate_video, "_visual_hashes", side_effect=[["1111111111111111"], ["eeeeeeeeeeeeeeee"]]),
            patch.object(generate_video, "_fetch_scene", side_effect=[result_one, result_two]) as fetch,
        ):
            assets, sources = generate_video.fetch_scene_assets(script, cfg, "horizontal")
        self.assertEqual(len(assets), 2)
        self.assertEqual(len(sources), 2)
        self.assertTrue(all(item["provider"] == "generated-image" for item in sources))
        self.assertEqual(fetch.call_args_list[0].args[2:4], (1920, 1080))
        self.assertEqual(fetch.call_args_list[0].args[-1], "horizontal")


    def test_fetch_scene_uses_commons_when_video_and_openverse_fail(self):
        asset = Path("/tmp/commons-scene.jpg")
        source = {"id": "wikimedia-commons:10", "provider": "Wikimedia Commons"}
        with (
            patch.object(generate_video, "_fetch_video_asset", return_value=(None, None)),
            patch.object(generate_video, "_fetch_openverse_scene", return_value=(None, None)),
            patch.object(generate_video, "_fetch_commons_scene", return_value=(asset, source)) as commons,
        ):
            result_asset, meta, provenance = generate_video._fetch_scene(
                1,
                "scene, scene_type:EXPLAIN|kb:static|dur:2|broll:music production studio|fallback:recording studio",
                1920, 1080, "test-story", None, set(), set(), set(), "horizontal",
            )
        self.assertEqual(result_asset, asset)
        self.assertEqual(provenance, source)
        self.assertEqual(meta["broll"], "music production studio")
        commons.assert_called_once()

    def test_commons_cc_by_assets_receive_youtube_description_attribution(self):
        source = {
            "id": "wikimedia-commons:42",
            "provider": "Wikimedia Commons",
            "title": "Recording studio.jpg",
            "creator": "Photographer A",
            "source_url": "https://commons.wikimedia.org/wiki/File:Recording_studio.jpg",
            "license": "by",
            "license_version": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
        }
        result = generate_video._with_attribution({"yt_desc": "Read more below."}, [source])
        self.assertIn("Image attribution (CC BY):", result["yt_desc"])
        self.assertIn("Photographer A", result["yt_desc"])
        self.assertIn(source["source_url"], result["yt_desc"])
        self.assertIn(source["license_url"], result["yt_desc"])
        self.assertIn("Changes: cropped, resized and animated", result["yt_desc"])
        self.assertEqual(len(result["footage_credits"]), 1)

    def test_commons_public_domain_assets_do_not_clutter_youtube_description(self):
        source = {
            "id": "wikimedia-commons:43",
            "provider": "Wikimedia Commons",
            "title": "Music producer.jpg",
            "creator": "Creator B",
            "source_url": "https://commons.wikimedia.org/wiki/File:Music_producer.jpg",
            "license": "cc0",
            "license_version": "CC0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        }
        result = generate_video._with_attribution({"yt_desc": "Read more below."}, [source])
        self.assertEqual(result["yt_desc"], "Read more below.")
        self.assertIn("Wikimedia Commons image:", result["footage_credits"][0])

    def test_youtube_description_excludes_asset_credits(self):
        platform = {"yt_desc": "Read the full post."}
        sources = [
            {"id": "pexels:1", "provider": "Pexels", "creator": "Ava", "source_url": "https://pexels.test/1"},
            {"id": "pexels:1", "provider": "Pexels", "creator": "Ava", "source_url": "https://pexels.test/1"},
            {"id": "pixabay:2", "provider": "Pixabay", "creator": "Ben", "source_url": "https://pixabay.test/2"},
        ]
        result = generate_video._with_attribution(platform, sources)
        self.assertEqual(len(result["footage_credits"]), 2)
        self.assertEqual(result["yt_desc"], platform["yt_desc"])
        self.assertNotIn("Footage credits:", result["yt_desc"])
        self.assertNotIn("Pexels: Ava", result["yt_desc"])
        self.assertNotIn("Pixabay: Ben", result["yt_desc"])


class VoiceAndEditTimingTests(unittest.TestCase):
    def test_elevenlabs_alignment_becomes_word_timings(self):
        import tts_elevenlabs
        alignment = {
            "characters": list("Hi there."),
            "character_start_times_seconds": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
            "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        }
        words = tts_elevenlabs.alignment_to_words(alignment)
        self.assertEqual([w["text"] for w in words], ["Hi", "there."])
        self.assertEqual((words[1]["start"], words[1]["end"]), (0.3, 0.9))

    def test_scene_cuts_follow_spoken_words(self):
        narration = "one two three four five six seven eight"
        words = [{"text": t, "start": i * 1.0, "end": i * 1.0 + 0.8}
                 for i, t in enumerate(narration.split())]
        windows = generate_video.scene_windows(words, narration, 4, 8.5)
        self.assertEqual(len(windows), 4)
        self.assertEqual(windows[0][0], 0.0)
        # Scene 2 starts on word 3 ("three", spoken at 2.0s), a beat early.
        self.assertAlmostEqual(windows[1][0], 1.92, places=2)
        self.assertEqual(windows[-1][1], 8.5)

    def test_captions_break_on_punctuation_and_cap_length(self):
        words = [{"text": t, "start": i * 0.3, "end": i * 0.3 + 0.25}
                 for i, t in enumerate("THIS IS BIG. AGENTS NOW RUN REAL WORK".split())]
        chunks = generate_video._caption_chunks(words, 3, 18)
        self.assertEqual([" ".join(w["text"] for w in c) for c in chunks],
                         ["THIS IS BIG.", "AGENTS NOW RUN", "REAL WORK"])


class VisualDuplicateGuardTests(unittest.TestCase):
    def _pattern_image(self, path, checker=False):
        from PIL import Image
        image = Image.new("RGB", (192, 128))
        pixels = []
        for y in range(128):
            for x in range(192):
                if checker:
                    value = 240 if ((x // 12) + (y // 12)) % 2 else 12
                    pixels.append((value, value, value))
                else:
                    value = int(35 + 0.8 * x + 0.2 * y) % 256
                    pixels.append((value, int(value * 0.65) % 256, 255 - value))
        image.putdata(pixels)
        image.save(path, format="PNG")

    def test_perceptual_hash_detects_the_same_image(self):
        with TemporaryDirectory() as temporary_dir:
            first = Path(temporary_dir) / "first.png"
            second = Path(temporary_dir) / "copy.png"
            self._pattern_image(first)
            self._pattern_image(second)
            first_hashes = generate_video._visual_hashes(first)
            second_hashes = generate_video._visual_hashes(second)
            self.assertEqual(first_hashes, second_hashes)
            match = generate_video._find_visual_duplicate(
                second_hashes, [{"id": "previous-channel-image", "visual_hashes": first_hashes}]
            )
            self.assertIsNotNone(match)
            self.assertEqual(match["id"], "previous-channel-image")

    def test_perceptually_different_images_are_not_duplicates(self):
        with TemporaryDirectory() as temporary_dir:
            first = Path(temporary_dir) / "gradient.png"
            second = Path(temporary_dir) / "checker.png"
            self._pattern_image(first)
            self._pattern_image(second, checker=True)
            first_hashes = generate_video._visual_hashes(first)
            second_hashes = generate_video._visual_hashes(second)
            self.assertIsNone(generate_video._find_visual_duplicate(
                second_hashes, [{"id": "different-image", "visual_hashes": first_hashes}]
            ))

    def test_single_matching_video_frame_blocks_reuse(self):
        current_hashes = [
            "1111111111111111", "2222222222222222", "3333333333333333",
            "4444444444444444", "5555555555555555",
        ]
        history = [{
            "id": "old-video-containing-reused-scene",
            "visual_hashes": ["1111111111111111", "aaaaaaaaaaaaaaaa",
                              "bbbbbbbbbbbbbbbb", "cccccccccccccccc",
                              "dddddddddddddddd"],
        }]
        match = generate_video._find_visual_duplicate(current_hashes, history)
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], "old-video-containing-reused-scene")

    def test_stock_video_search_never_relaxes_global_history_blocklist(self):
        from pathlib import Path
        from unittest.mock import patch
        with TemporaryDirectory() as temporary_dir:
            old_candidate = {
                "id": "pexels:already-used", "provider": "Pexels",
                "creator": "Old Creator", "score": 1, "url": "https://example.test/old",
            }
            with (
                patch.object(generate_video, "OUT", Path(temporary_dir)),
                patch.object(generate_video, "_pexels_video_search", return_value=[old_candidate]),
                patch.object(generate_video, "_pixabay_video_search", return_value=[]),
                patch.object(generate_video, "_download_candidate") as download,
            ):
                asset, source = generate_video._fetch_video_asset(
                    0, {"broll": "cinematic technology lab", "fallback": "technology lab"},
                    1920, 1080, set(), set(), {"pexels:already-used"}, "horizontal",
                )
            self.assertIsNone(asset)
            self.assertIsNone(source)
            download.assert_not_called()

    def test_scene_fetch_retries_duplicate_asset_before_accepting_new_one(self):
        with TemporaryDirectory() as temporary_dir:
            repeated = Path(temporary_dir) / "repeated.png"
            unique = Path(temporary_dir) / "unique.png"
            self._pattern_image(repeated)
            self._pattern_image(unique, checker=True)
            repeated_hashes = generate_video._visual_hashes(repeated)
            history = [{
                "id": "old-cross-channel-asset",
                "provider": "Openverse",
                "visual_hashes": repeated_hashes,
                "used_at": 1,
                "slug": "same-story",
                "variant": "vertical",
            }]
            script = {
                "post": {"slug": "same-story", "title": "A new story", "image_url": ""},
                "scene_prompts": ["HOOK|broll:topic-specific image|fallback:topic image"],
            }
            cfg = {"video": {"horizontal": {"w": 1920, "h": 1080}}}

            with (
                patch.object(generate_video, "_load_footage_history", return_value=history),
                patch.object(generate_video, "_save_footage_history") as save_history,
                patch.object(generate_video, "_fetch_scene", side_effect=[
                    (str(repeated), {}, {"id": "pexels:copy", "provider": "Pexels"}),
                    (str(unique), {}, {"id": "pixabay:unique", "provider": "Pixabay"}),
                ]) as fetch,
            ):
                assets, sources = generate_video.fetch_scene_assets(script, cfg, "horizontal")

            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(assets[0][0], str(unique))
            self.assertFalse(repeated.exists())
            self.assertEqual(sources[0]["id"], "pixabay:unique")
            save_history.assert_called_once()


if __name__ == "__main__":
    unittest.main()
