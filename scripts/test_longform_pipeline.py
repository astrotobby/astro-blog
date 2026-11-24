"""Fast offline regression tests for the long-form scheduler and safety gates."""
import asyncio
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import longform_pipeline as pipeline


class LLMJsonParsingTests(unittest.TestCase):
    def test_strict_json_parses_without_repair(self):
        raw = '{"title":"AI watchdog","description":"A short summary","tags":["AI","technology"],"narration":"A supported account."}'
        data = pipeline.parse_model_json(raw)
        self.assertEqual(data["title"], "AI watchdog")
        self.assertEqual(data["tags"], ["AI", "technology"])

    def test_malformed_model_json_is_repaired(self):
        # Simulates an unescaped quote and a trailing comma in an LLM response.
        raw = '{"title":"AI watchdog","description":"A short summary","tags":["AI","technology",],"narration":"The report called the glasses "always listening" and raised concerns."'
        data = pipeline.parse_model_json(raw)
        self.assertEqual(data["title"], "AI watchdog")
        self.assertIn("always listening", data["narration"])
        self.assertEqual(data["tags"], ["AI", "technology"])


class LLMAuthenticationTests(unittest.TestCase):
    def test_gemini_interactions_uses_secret_header_and_extracts_model_text(self):
        values = {
            "GEMINI_API_KEY": "test-gemini-key",
            "GEMINI_MODEL": "gemini-3.8-flash",
            "CLAUDE_CODE_OAUTH_TOKEN": "must-not-be-used",
        }
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "generated text"}]}]},
        )
        with patch.object(pipeline, "env", side_effect=lambda name, default=None: values.get(name, default)):
            with patch.object(pipeline.requests, "post", return_value=response) as post:
                output = pipeline._generate_text("prompt", "system", "unused-anthropic-model")
        self.assertEqual(output, "generated text")
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-gemini-key")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "gemini-3.8-flash")
        self.assertEqual(post.call_args.kwargs["timeout"], pipeline.GEMINI_REQUEST_TIMEOUT)
        self.assertFalse(post.call_args.kwargs["json"]["store"])

    def test_gemini_retries_503_then_falls_back_to_supported_model(self):
        values = {
            "GEMINI_API_KEY": "test-gemini-key",
            "GEMINI_MODEL": "gemini-3.8-flash",
            "GEMINI_FALLBACK_MODEL": "",
            "GEMINI_FALLBACK_MODELS": "gemini-3.7-flash",
        }
        unavailable = pipeline.requests.Response()
        unavailable.status_code = 503
        unavailable.headers["Retry-After"] = "1"
        success = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "fallback text"}]}]},
        )
        with patch.object(pipeline, "env", side_effect=lambda name, default=None: values.get(name, default)):
            with patch.object(pipeline.requests, "post", side_effect=[unavailable, unavailable, success]) as post:
                with patch.object(pipeline.time_module, "sleep") as sleep:
                    output = pipeline._generate_text("prompt", "system", "unused-model")
        self.assertEqual(output, "fallback text")
        self.assertEqual(post.call_count, 3)
        self.assertEqual([c.kwargs["json"]["model"] for c in post.call_args_list], [
            "gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.7-flash"
        ])
        self.assertEqual(sleep.call_count, 1)

    def test_gemini_fallback_models_try_flash_lite_candidates_in_order(self):
        values = {
            "GEMINI_API_KEY": "test-gemini-key",
            "GEMINI_MODEL": "gemini-3.8-flash",
            "GEMINI_FALLBACK_MODELS": "gemini-3.5-flash-lite,gemini-3.1-flash-lite",
            "GEMINI_FALLBACK_MODEL": "",
        }
        unavailable = pipeline.requests.Response()
        unavailable.status_code = 503
        success = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "Flash-Lite fallback text"}]}]},
        )
        with patch.object(pipeline, "env", side_effect=lambda name, default=None: values.get(name, default)):
            with patch.object(pipeline.requests, "post", side_effect=[unavailable, unavailable, unavailable, success]) as post:
                with patch.object(pipeline.time_module, "sleep") as sleep:
                    output = pipeline._generate_text("prompt", "system", "unused-model")
        self.assertEqual(output, "Flash-Lite fallback text")
        self.assertEqual(
            [call.kwargs["json"]["model"] for call in post.call_args_list],
            ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
        )
        self.assertEqual(post.call_args_list[2].kwargs["timeout"], pipeline.GEMINI_REQUEST_TIMEOUT)
        self.assertEqual(sleep.call_count, 1)

    def test_claude_code_oauth_uses_subscription_cli_without_api_key(self):
        values = {
            "CLAUDE_CODE_OAUTH_TOKEN": "test-oauth-token",
            "ANTHROPIC_API_KEY": "test-api-key-with-no-credit",
        }
        with patch.object(pipeline, "env", side_effect=lambda name, default=None: values.get(name, default)):
            with patch.object(pipeline.shutil, "which", return_value="/usr/bin/claude"):
                with patch.object(pipeline.subprocess, "run", return_value=SimpleNamespace(
                    returncode=0, stdout='{"title":"test"}', stderr=""
                )) as run:
                    output = pipeline._generate_text("prompt", "system prompt", "claude-sonnet-5")
        self.assertEqual(output, '{"title":"test"}')
        command = run.call_args.args[0]
        self.assertIn("--append-system-prompt", command)
        child_env = run.call_args.kwargs["env"]
        self.assertNotIn("ANTHROPIC_API_KEY", child_env)
        self.assertEqual(child_env["CLAUDE_CODE_OAUTH_TOKEN"], "test-oauth-token")

    def test_configured_oauth_without_cli_fails_clearly(self):
        with patch.object(pipeline, "env", side_effect=lambda name, default=None: "test-token" if name == "CLAUDE_CODE_OAUTH_TOKEN" else default):
            with patch.object(pipeline.shutil, "which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "CLI is not installed"):
                    pipeline._generate_text("prompt", "system", "claude-sonnet-5")


    def test_gemini_outage_uses_opencode_before_anthropic(self):
        values = {
            "GEMINI_API_KEY": "test-gemini-key",
            "GEMINI_MODEL": "gemini-3.8-flash",
            "GEMINI_FALLBACK_MODEL": "",
            "GEMINI_FALLBACK_MODELS": "",
            "OPENCODE_API_KEY": "test-opencode-key",
            "OPENCODE_FALLBACK_MODELS": "opencode/nemotron-3.5-lightning-free,opencode/deepseek-v4.1-flash-free",
            "ANTHROPIC_API_KEY": "must-not-be-used",
        }
        unavailable = pipeline.requests.Response()
        unavailable.status_code = 503
        unavailable.headers["Retry-After"] = "1"
        result = SimpleNamespace(returncode=0, stdout='{"title":"OpenCode output"}', stderr="")
        with patch.object(pipeline, "env", side_effect=lambda name, default=None: values.get(name, default)):
            with patch.object(pipeline.requests, "post", side_effect=[unavailable] * 2):
                with patch.object(pipeline.time_module, "sleep"):
                    with patch.object(pipeline.shutil, "which", return_value="/usr/bin/opencode"):
                        with patch.object(pipeline.subprocess, "run", return_value=result) as run:
                            output = pipeline._generate_text("prompt", "system", "unused-model")
        self.assertEqual(output, '{"title":"OpenCode output"}')
        command = run.call_args.args[0]
        self.assertEqual(command[0:5], ["/usr/bin/opencode", "run", "--standalone", "--model", "opencode/nemotron-3.5-lightning-free"])
        self.assertEqual(run.call_args.kwargs["env"]["OPENCODE_API_KEY"], "test-opencode-key")
        self.assertEqual(run.call_args.kwargs["timeout"], pipeline.OPENCODE_REQUEST_TIMEOUT)

    def test_gemini_outage_falls_back_to_freellmapi_before_anthropic(self):
        values = {
            "GEMINI_API_KEY": "test-gemini-key",
            "GEMINI_MODEL": "gemini-3.8-flash",
            "GEMINI_FALLBACK_MODEL": "",
            "GEMINI_FALLBACK_MODELS": "",
            "FREELLMAPI_API_KEY": "test-local-profile-key",
            "FREELLMAPI_BASE_URL": "http://127.0.0.1:3001/v1",
            "FREELLMAPI_MODEL": "auto:smart",
            "ANTHROPIC_API_KEY": "must-not-be-used",
        }
        unavailable = pipeline.requests.Response()
        unavailable.status_code = 503
        unavailable.headers["Retry-After"] = "1"
        free_success = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content": "FreeLLMAPI script JSON"}}]},
            headers={"X-Routed-Via": "ovh/example-free-model"},
        )
        with patch.object(pipeline, "env", side_effect=lambda name, default=None: values.get(name, default)):
            with patch.object(pipeline.requests, "post", side_effect=[unavailable] * 2 + [free_success]) as post:
                with patch.object(pipeline.time_module, "sleep"):
                    output = pipeline._generate_text("prompt", "system", "unused-model")
        self.assertEqual(output, "FreeLLMAPI script JSON")
        self.assertEqual(post.call_count, 3)
        self.assertEqual(post.call_args.kwargs["timeout"], pipeline.FREELLMAPI_REQUEST_TIMEOUT)
        call = post.call_args
        self.assertEqual(call.args[0], "http://127.0.0.1:3001/v1/chat/completions")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer test-local-profile-key")
        self.assertEqual(call.kwargs["json"]["model"], "auto:smart")

    def test_gemini_outage_falls_back_to_anthropic_api(self):
        values = {
            "GEMINI_API_KEY": "test-gemini-key",
            "GEMINI_MODEL": "gemini-3.8-flash",
            "GEMINI_FALLBACK_MODEL": "",
            "GEMINI_FALLBACK_MODELS": "",
            "FREELLMAPI_API_KEY": "test-local-profile-key",
            "ANTHROPIC_API_KEY": "test-anthropic-key",
        }
        unavailable = pipeline.requests.Response()
        unavailable.status_code = 503
        unavailable.headers["Retry-After"] = "1"
        message = SimpleNamespace(content=[SimpleNamespace(type="text", text="anthropic fallback text")])
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: message))
        constructed = {}
        def make_anthropic_client(**kwargs):
            constructed.update(kwargs)
            return client
        anthropic_module = SimpleNamespace(Anthropic=make_anthropic_client)
        with patch.object(pipeline, "env", side_effect=lambda name, default=None: values.get(name, default)):
            with patch.object(pipeline.requests, "post", side_effect=[unavailable] * 3):
                with patch.object(pipeline.time_module, "sleep"):
                    with patch.dict(sys.modules, {"anthropic": anthropic_module}):
                        output = pipeline._generate_text("prompt", "system", "unused-model")
        self.assertEqual(output, "anthropic fallback text")
        self.assertEqual(constructed["timeout"], pipeline.ANTHROPIC_REQUEST_TIMEOUT)



class CreatePackageLengthTests(unittest.TestCase):
    def test_short_first_draft_appends_sourced_continuation_and_keeps_minimum(self):
        first_narration = " ".join(["verified"] * 1700)
        extra_narration = " ".join(["additional"] * 500)
        first_response = json.dumps({
            "title": "Verified technology story",
            "description": "A sourced long-form report.",
            "tags": ["technology", "news", "analysis"],
            "narration": first_narration,
        })
        source = {
            "publisher": "Example Publisher",
            "published_at": "2026-11-19T00:00:00Z",
            "title": "Primary report about the event",
            "url": "https://news.example/report",
            "article_text": "The verified report describes the event, the people involved and the documented timeline.",
            "summary": "A corroborating summary.",
        }
        values = {"GEMINI_API_KEY": "test-key", "LONGFORM_MODEL": "test-model"}
        with patch.object(pipeline, "env", side_effect=lambda name, default=None: values.get(name, default)):
            with patch.object(pipeline, "_generate_text", side_effect=[first_response, extra_narration]) as generate:
                package = pipeline.create_package(
                    "digital_nomad",
                    {"title": "Verified lead story", "url": "https://news.example/lead"},
                    [source],
                )

        self.assertEqual(package["word_count"], 2200)
        self.assertTrue(package["narration"].startswith("verified verified"))
        self.assertTrue(package["narration"].endswith("additional"))
        self.assertEqual(generate.call_count, 2)
        continuation_prompt = generate.call_args_list[1].args[0]
        self.assertIn("EXISTING NARRATION:", continuation_prompt)
        self.assertIn("SOURCE BUNDLE:", continuation_prompt)
        self.assertIn("Publisher: Example Publisher", continuation_prompt)
        self.assertIn("Primary report about the event", continuation_prompt)
        self.assertIn("Write only 500 additional spoken words", continuation_prompt)

    def test_oversized_sourced_continuation_is_trimmed_at_sentence_boundary(self):
        first_narration = " ".join(["verified"] * 1700)
        extra_narration = "additional facts are supported. " * 400
        first_response = json.dumps({
            "title": "Verified technology story",
            "description": "A sourced long-form report.",
            "tags": ["technology", "news", "analysis"],
            "narration": first_narration,
        })
        source = {
            "publisher": "Example Publisher",
            "published_at": "2026-11-19T00:00:00Z",
            "title": "Primary report about the event",
            "url": "https://news.example/report",
            "article_text": "The verified report describes the event, the people involved and the documented timeline.",
            "summary": "A corroborating summary.",
        }
        values = {"GEMINI_API_KEY": "test-key", "LONGFORM_MODEL": "test-model"}
        with patch.object(pipeline, "env", side_effect=lambda name, default=None: values.get(name, default)):
            with patch.object(pipeline, "_generate_text", side_effect=[first_response, extra_narration]):
                package = pipeline.create_package(
                    "digital_nomad",
                    {"title": "Verified lead story", "url": "https://news.example/lead"},
                    [source],
                )

        self.assertLessEqual(package["word_count"], 2500)
        self.assertGreaterEqual(package["word_count"], 1900)
        self.assertLessEqual(pipeline.narration_word_count(package["narration"]), 2500)
        self.assertTrue(package["narration"].endswith("supported."))


class EdgeTtsWordTimingTests(unittest.TestCase):
    def test_edge_tts_stream_keeps_native_word_boundaries(self):
        class FakeCommunicate:
            def __init__(self, text, voice, **kwargs):
                self.kwargs = kwargs

            async def stream(self):
                yield {"type": "audio", "data": b"x" * 2048}
                yield {"type": "WordBoundary", "offset": 1_000_000,
                       "duration": 2_000_000, "text": "Hello"}
                yield {"type": "WordBoundary", "offset": 3_500_000,
                       "duration": 1_500_000, "text": "there."}

        observed = {}
        class RecordingCommunicate(FakeCommunicate):
            def __init__(self, text, voice, **kwargs):
                observed.update(kwargs)
                super().__init__(text, voice, **kwargs)

        fake_edge_tts = SimpleNamespace(Communicate=RecordingCommunicate)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "voice.mp3"
            with patch.dict(sys.modules, {"edge_tts": fake_edge_tts}):
                words = asyncio.run(pipeline.renderer._tts(
                    "Hello there.", "en-US-AndrewNeural", "+0%", "+0Hz", output
                ))
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1024)

        self.assertEqual(observed.get("boundary"), "WordBoundary")
        self.assertEqual(len(words), 2)
        self.assertAlmostEqual(words[0]["start"], 0.1)
        self.assertAlmostEqual(words[0]["end"], 0.3)
        self.assertEqual(words[1]["text"], "there.")
        self.assertAlmostEqual(words[1]["start"], 0.35)

    def test_caption_timing_validator_accepts_complete_ordered_words(self):
        narration = "One two three four five six seven eight"
        words = [
            {"text": token, "start": index * 0.3, "end": index * 0.3 + 0.2}
            for index, token in enumerate(narration.split())
        ]
        self.assertTrue(pipeline.renderer.word_timings_valid(words, narration))

    def test_caption_timing_validator_rejects_sparse_or_malformed_words(self):
        narration = "One two three four five six seven eight"
        sparse = [{"text": "One", "start": 0.0, "end": 0.2}]
        malformed = [
            {"text": "One", "start": 0.5, "end": 0.2},
            {"text": "two", "start": 0.7, "end": 0.8},
        ]
        self.assertFalse(pipeline.renderer.word_timings_valid(sparse, narration))
        self.assertFalse(pipeline.renderer.word_timings_valid(malformed, narration))

    def test_scene_fails_instead_of_creating_black_video_frame(self):
        with patch.object(pipeline.renderer, "_fetch_video_asset", return_value=(None, None)):
            with patch.object(pipeline.renderer.requests, "get", return_value=SimpleNamespace(
                status_code=503, content=b""
            )):
                with patch.object(pipeline.renderer.time, "sleep"):
                    with self.assertRaisesRegex(RuntimeError, "refusing to render a black placeholder"):
                        pipeline.renderer._fetch_scene(
                            1,
                            "a visual scene|broll:relevant subject|fallback:alternative subject",
                            1280, 720, "offline-test", None, set(), set(), set(), "horizontal"
                        )


class ContextualVisualAssetTests(unittest.TestCase):
    def test_music_story_gets_entertainment_scene_profile(self):
        narration = (
            "Universal Music has appointed a new president for its Latin American and Iberian "
            "record label business. The music executive will work with artists, producers and "
            "songwriters, while the company expands its music catalogue, streaming relationships "
            "and concert partnerships. The announcement comes as Latin music continues to grow "
            "across albums, singles, touring and global music charts. A recording studio, a live "
            "concert stage and a record label office are all relevant visual settings for this story. "
        ) * 4
        package = {
            "title": "Universal Music Names New Regional President",
            "description": "A leadership change at a major music company.",
            "tags": ["music", "record label", "Latin music"],
            "narration": narration,
            "word_count": len(narration.split()),
        }
        lead = {"url": "https://news.example/music-story"}
        source = [{"url": "https://publisher.example/music-story"}]
        cfg = pipeline.load_config()
        cfg["visuals"]["scenes"] = 6

        script = pipeline.build_render_script(
            "music-visual-test", lead, source, package, cfg
        )

        self.assertEqual(script["topic_category"], "entertainment")
        self.assertIn(narration, script["post"]["body"])
        prompts = script["scene_prompts"]
        self.assertEqual(len(prompts), 6)
        self.assertTrue(any(
            "record label" in prompt.lower() or "music recording" in prompt.lower()
            or "concert" in prompt.lower()
            for prompt in prompts
        ))


class OpenverseFallbackTests(unittest.TestCase):
    def test_openverse_core_query_removes_renderer_camera_directions(self):
        query = "live concert crowd and stage wide establishing shot, visible environment"
        self.assertEqual(
            pipeline.renderer._openverse_core_query(query),
            "live concert crowd and stage",
        )

    def test_openverse_search_is_anonymous_and_commercial_use_licensed(self):
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "results": [
                    {
                        "id": "cc0-image",
                        "url": "https://media.example/cc0.jpg",
                        "thumbnail": "https://media.example/cc0-thumb.jpg",
                        "foreign_landing_url": "https://commons.example/cc0",
                        "title": "Recording studio",
                        "creator": "Example creator",
                        "license": "cc0",
                        "license_version": "",
                        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                        "width": 1920,
                        "height": 1080,
                    },
                    {
                        "id": "by-image",
                        "url": "https://media.example/by.jpg",
                        "foreign_landing_url": "https://commons.example/by",
                        "title": "Live concert",
                        "creator": "Another creator",
                        "creator_url": "https://creators.example/another",
                        "license": "by",
                        "license_version": "4.0",
                        "license_url": "https://creativecommons.org/licenses/by/4.0/",
                        "attribution": "Another creator / Openverse",
                        "width": 1920,
                        "height": 1080,
                    },
                    {
                        "id": "by-nc-image",
                        "url": "https://media.example/by-nc.jpg",
                        "license": "by-nc",
                        "width": 1920,
                        "height": 1080,
                    },
                ]
            },
        )
        with patch.object(pipeline.renderer, "_cache_get", return_value=None):
            with patch.object(pipeline.renderer, "_cache_put") as cache_put:
                with patch.object(pipeline.renderer.requests, "get", return_value=response) as get:
                    items = pipeline.renderer._openverse_image_search(
                        "live concert crowd and stage wide establishing shot, visible environment",
                        1920,
                        1080,
                    )

        self.assertEqual(len(items), 2)
        self.assertEqual({item["license"] for item in items}, {"cc0", "by"})
        by_item = next(item for item in items if item["license"] == "by")
        self.assertEqual(by_item["creator_url"], "https://creators.example/another")
        self.assertEqual(by_item["license_url"], "https://creativecommons.org/licenses/by/4.0/")
        self.assertEqual(by_item["attribution"], "Another creator / Openverse")
        self.assertEqual(get.call_args.args[0], pipeline.renderer.OPENVERSE_IMAGES_URL)
        self.assertEqual(get.call_args.kwargs["params"]["q"], "live concert crowd and stage")
        self.assertEqual(
            get.call_args.kwargs["params"]["license"],
            pipeline.renderer.OPENVERSE_LICENSE_FILTER,
        )
        self.assertEqual(get.call_args.kwargs["params"]["license_type"], "commercial")
        self.assertNotIn("size", get.call_args.kwargs["params"])
        self.assertNotIn("aspect_ratio", get.call_args.kwargs["params"])
        self.assertNotIn("Authorization", get.call_args.kwargs["headers"])
        cache_put.assert_called_once()

    def test_openverse_attribution_includes_creator_source_and_license(self):
        credits = pipeline.renderer._source_credits(
            [
                {
                    "id": "openverse:by-image",
                    "provider": "Openverse",
                    "title": "Live concert",
                    "creator": "Another creator",
                    "creator_url": "https://creators.example/another",
                    "source_url": "https://commons.example/by",
                    "license": "by",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                }
            ]
        )
        self.assertEqual(len(credits), 1)
        self.assertIn("Another creator", credits[0])
        self.assertIn("https://creators.example/another", credits[0])
        self.assertIn("https://commons.example/by", credits[0])
        self.assertIn("CC BY", credits[0])
        self.assertIn("https://creativecommons.org/licenses/by/4.0/", credits[0])

    def test_openverse_download_verifies_image_bytes(self):
        from io import BytesIO
        from PIL import Image

        image = Image.effect_noise((1280, 720), 80).convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=95)
        payload = buffer.getvalue()
        response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "image/jpeg"},
            content=payload,
        )
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "scene.jpg"
            with patch.object(pipeline.renderer.requests, "get", return_value=response):
                ok = pipeline.renderer._download_openverse_image(
                    {"url": "https://media.example/scene.jpg", "thumbnail": ""},
                    destination,
                )
            self.assertTrue(ok)
            with Image.open(destination) as downloaded:
                self.assertEqual(downloaded.size, (1280, 720))

    def test_scene_uses_openverse_before_pollinations_when_stock_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            image_path = Path(temp) / "openverse.jpg"
            image_path.write_bytes(b"verified-test-image")
            provenance = {
                "id": "openverse:cc0",
                "provider": "Openverse",
                "creator": "Example creator",
                "source_url": "https://commons.example/cc0",
                "license": "cc0",
            }
            with patch.object(pipeline.renderer, "_fetch_video_asset", return_value=(None, None)):
                with patch.object(
                    pipeline.renderer, "_fetch_openverse_scene",
                    return_value=(image_path, provenance),
                ) as openverse:
                    with patch.object(pipeline.renderer.requests, "get") as request:
                        asset, meta, source = pipeline.renderer._fetch_scene(
                            2,
                            "music studio|broll:record label office|fallback:recording studio",
                            1920, 1080, "music-test", None, set(), set(), set(), "horizontal"
                        )
            self.assertEqual(asset, image_path)
            self.assertEqual(source["provider"], "Openverse")
            openverse.assert_called_once()
            request.assert_not_called()


class ScheduleTests(unittest.TestCase):
    def test_four_publication_times_are_converted_from_kenya_to_utc(self):
        fixed_now = datetime(2026, 11, 18, 8, 0, tzinfo=pipeline.EAT)
        expected = {
            ("astrotobby", "10:00"): "2026-11-19T07:00:00+00:00",
            ("astrotobby", "15:00"): "2026-11-19T12:00:00+00:00",
            ("digital_nomad", "12:00"): "2026-11-19T09:00:00+00:00",
            ("digital_nomad", "18:00"): "2026-11-19T15:00:00+00:00",
        }
        for (channel, slot), value in expected.items():
            with self.subTest(channel=channel, slot=slot):
                target = pipeline.publish_time(channel, slot, "2026-11-19", fixed_now)
                self.assertEqual(target.isoformat(), value)

    def test_wrong_channel_slot_is_rejected(self):
        with self.assertRaises(ValueError):
            pipeline.publish_time("astrotobby", "12:00", "2026-11-19")
        with self.assertRaises(ValueError):
            pipeline.publish_time("digital_nomad", "10:00", "2026-11-19")

    def test_past_slot_is_rejected_for_manual_target_date(self):
        now = datetime(2026, 11, 18, 11, 0, tzinfo=pipeline.EAT)
        with self.assertRaisesRegex(ValueError, "future"):
            pipeline.publish_time("astrotobby", "10:00", "2026-11-18", now)

    def test_job_ids_are_stable_and_slot_specific(self):
        target = datetime(2026, 11, 19, 7, 0, tzinfo=timezone.utc)
        self.assertEqual(
            pipeline.make_job_id("astrotobby", "10:00", target),
            "20261119_astrotobby_1000",
        )
        self.assertNotEqual(
            pipeline.make_job_id("astrotobby", "10:00", target),
            pipeline.make_job_id("digital_nomad", "12:00", target),
        )

    def test_youtube_schedule_comparison_accepts_equivalent_iso8601_formats(self):
        self.assertTrue(
            pipeline._same_youtube_time(
                "2026-11-25T07:00:00.000Z",
                "2026-11-25T07:00:00Z",
            )
        )
        self.assertTrue(
            pipeline._same_youtube_time(
                "2026-11-25T10:00:00+03:00",
                "2026-11-25T07:00:00Z",
            )
        )

    def test_youtube_schedule_comparison_rejects_different_or_invalid_times(self):
        self.assertFalse(
            pipeline._same_youtube_time(
                "2026-11-25T07:00:01Z",
                "2026-11-25T07:00:00Z",
            )
        )
        self.assertFalse(pipeline._same_youtube_time(None, "2026-11-25T07:00:00Z"))
        self.assertFalse(pipeline._same_youtube_time("not-a-date", "2026-11-25T07:00:00Z"))

    def test_private_unscheduled_rollback_omits_publish_at_and_preserves_settings(self):
        status = pipeline._private_unscheduled_status({
            "privacyStatus": "private",
            "publishAt": "2026-11-25T07:00:00Z",
            "license": "youtube",
            "embeddable": True,
            "publicStatsViewable": False,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
            "uploadStatus": "processed",
        })
        self.assertEqual(status["privacyStatus"], "private")
        self.assertNotIn("publishAt", status)
        self.assertNotIn("uploadStatus", status)
        self.assertEqual(status["license"], "youtube")
        self.assertTrue(status["embeddable"])
        self.assertFalse(status["publicStatsViewable"])
        self.assertFalse(status["selfDeclaredMadeForKids"])
        self.assertTrue(status["containsSyntheticMedia"])


class TopicTests(unittest.TestCase):
    def test_similarity_ignores_generic_headline_words(self):
        self.assertGreaterEqual(
            pipeline.similarity(
                "What happened in the AI technology industry today",
                "AI technology industry latest update",
            ),
            0.6,
        )

    def test_unrelated_topics_do_not_match(self):
        self.assertLess(
            pipeline.similarity("Hollywood box office movie premiere", "Open source Python AI agents"),
            0.2,
        )

    def test_article_parser_extracts_visible_paragraphs_and_ignores_scripts(self):
        parser = pipeline.ArticleText()
        parser.feed(
            "<html><head><meta name='description' content='Summary'></head>"
            "<body><script>ignore this text entirely</script>"
            "<p>This paragraph contains useful article information for the test.</p>"
            "<footer>Ignore this footer content.</footer></body></html>"
        )
        self.assertIn("useful article information", " ".join(parser.parts))
        self.assertNotIn("ignore this text", " ".join(parser.parts))
        self.assertEqual(parser.description, "Summary")

    def test_enrichment_keeps_rss_summary_when_page_extract_is_short(self):
        response = SimpleNamespace(
            url="https://publisher.example/story",
            ok=True,
            headers={"content-type": "text/html"},
            text="<html><body><p>This is a short but valid extracted article paragraph with sufficient detail.</p></body></html>",
        )
        rss_summary = "The publisher's RSS feed provides the longer original story summary that remains useful evidence."
        with patch.object(pipeline.requests, "get", return_value=response):
            result = pipeline.enrich({
                "title": "Example story",
                "url": "https://news.example/story",
                "summary": rss_summary,
                "publisher": "Example Publisher",
            })
        self.assertIn("short but valid extracted article paragraph", result["article_text"])
        self.assertIn(rss_summary, result["article_text"])

    def test_astrotobby_source_pool_contains_requested_publishers_and_video_refs(self):
        queries = pipeline.CHANNELS["astrotobby"]["queries"]
        self.assertEqual(pipeline.CHANNELS["astrotobby"]["channel_id"], "UCxndvpcFaVhN1bJxgWIjG_A")
        self.assertEqual(pipeline.CHANNELS["digital_nomad"]["channel_id"], "UCE_cklDludc6nkU1_4K6JzA")
        self.assertTrue(any("site:cnn.com" in q for q in queries))
        self.assertTrue(any("site:bbc.com/news" in q and "site:bbc.co.uk/news" in q for q in queries))
        publishers = {name for name, _url in pipeline.CHANNEL_FEEDS["astrotobby"]}
        self.assertIn("The Guardian Culture", publishers)
        self.assertFalse(any(name.startswith("BBC") for name in publishers))
        self.assertTrue(any("CRqhR0tQnKM" in x["url"] for x in pipeline.ASTROTOBBY_YOUTUBE_REFERENCES))
        self.assertTrue(any("18by3TXfH5k" in x["url"] for x in pipeline.ASTROTOBBY_YOUTUBE_REFERENCES))
        self.assertTrue(any("@VALUETAINMENT" in x["url"] for x in pipeline.ASTROTOBBY_YOUTUBE_REFERENCES))
        self.assertNotIn("valuetainment", pipeline.TRUSTED)

    def test_atom_youtube_feed_is_parsed_with_publisher_hint(self):
        atom = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Valuetainment current affairs discussion</title>
            <link href="https://www.youtube.com/watch?v=abcdefghijk"/>
            <published>2026-11-18T07:00:00+00:00</published>
          </entry>
        </feed>"""
        rows = pipeline.parse_rss(atom, "Valuetainment uploads", "Valuetainment")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["publisher"], "Valuetainment")
        self.assertEqual(rows[0]["title"], "Valuetainment current affairs discussion")
        self.assertEqual(rows[0]["published_at"], "2026-11-18T07:00:00+00:00")

    def test_valuetainment_upload_feed_is_tagged_as_commentary(self):
        atom = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Valuetainment current affairs discussion</title>
            <link href="https://www.youtube.com/watch?v=abcdefghijk"/>
            <published>2026-11-18T07:00:00+00:00</published>
          </entry>
        </feed>"""
        channel_page = '<html><script>{"channelId":"UCabcdefghijklmnopqrstuv"}</script></html>'
        responses = [
            SimpleNamespace(raise_for_status=lambda: None, text=channel_page),
            SimpleNamespace(raise_for_status=lambda: None, text=atom),
        ]
        with patch.object(pipeline.requests, "get", side_effect=responses):
            rows = pipeline.valuetainment_uploads_feed()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_type"], "commentary")
        self.assertEqual(rows[0]["publisher"], "Valuetainment")

    def test_youtube_oembed_metadata_is_not_misrepresented_as_transcript(self):
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"title": "A referenced YouTube video", "author_name": "Example Channel"},
        )
        with patch.object(pipeline.requests, "get", return_value=response):
            result = pipeline.youtube_reference_metadata("https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(result["title"], "A referenced YouTube video")
        self.assertTrue(result["metadata_only"])
        self.assertEqual(result["article_text"], "")



class SourceDiscoveryTests(unittest.TestCase):
    def test_targeted_headline_search_finds_second_independent_report(self):
        now = datetime.now(timezone.utc).isoformat()
        lead = {
            "title": "Famous actor announces major new film",
            "url": "https://cnn.example/story",
            "summary": "A" * 400,
            "publisher": "CNN",
            "published_at": now,
        }
        corroborating = {
            "title": "Major new film announced by famous actor",
            "url": "https://ap.example/story",
            "summary": "B" * 400,
            "publisher": "Associated Press",
            "published_at": now,
        }

        def fake_feed(query):
            if '"Famous actor announces major new film"' in query:
                return [dict(corroborating)]
            if "entertainment OR film" in query:
                return [dict(lead)]
            return []

        def fake_enrich(row):
            result = dict(row)
            result["article_text"] = (row.get("summary") or "") + (" evidence" * 20)
            return result

        with patch.object(pipeline, "publisher_feeds", return_value=[]):
            with patch.object(pipeline, "valuetainment_uploads_feed", return_value=[]):
                with patch.object(pipeline, "youtube_channel_uploads_feed", return_value=[]):
                    with patch.object(pipeline, "feed", side_effect=fake_feed):
                        with patch.object(pipeline, "enrich", side_effect=fake_enrich):
                            selected_lead, sources = pipeline.discover("astrotobby", [])

        self.assertEqual(selected_lead["title"], lead["title"])
        self.assertGreaterEqual(len(sources), 2)
        self.assertEqual({source["publisher"] for source in sources}, {"CNN", "Associated Press"})
class LedgerMergeTests(unittest.TestCase):
    def test_concurrent_workers_keep_both_independent_jobs(self):
        remote = {
            "schema": 1,
            "jobs": {"astro10": {"status": "rendered", "updated_at": "2026-11-18T07:00:00+00:00"}},
            "recent_topics": [{"job_id": "astro10", "title": "Film release"}],
        }
        local = {
            "schema": 1,
            "jobs": {"digital12": {"status": "scheduled", "updated_at": "2026-11-18T09:00:00+00:00"}},
            "recent_topics": [{"job_id": "digital12", "title": "AI automation"}],
        }
        merged = pipeline._merge_ledgers(local, remote)
        self.assertIn("astro10", merged["jobs"])
        self.assertIn("digital12", merged["jobs"])
        self.assertEqual({x["job_id"] for x in merged["recent_topics"]}, {"astro10", "digital12"})

    def test_newer_job_state_wins_for_the_same_job(self):
        remote = {"schema": 1, "jobs": {
            "astro10": {"status": "rendering", "updated_at": "2026-11-18T07:00:00+00:00"}
        }}
        local = {"schema": 1, "jobs": {
            "astro10": {"status": "scheduled", "updated_at": "2026-11-18T07:30:00+00:00"}
        }}
        merged = pipeline._merge_ledgers(local, remote)
        self.assertEqual(merged["jobs"]["astro10"]["status"], "scheduled")


class MediaGateTests(unittest.TestCase):
    def test_accepts_a_real_10_minute_1080p_video_with_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "video.mp4"
            path.write_bytes(b"x" * 150_000)
            probe = SimpleNamespace(
                stdout=json.dumps({
                    "streams": [
                        {"codec_type": "video", "width": 1920, "height": 1080},
                        {"codec_type": "audio"},
                    ]
                })
            )
            with patch.object(pipeline.renderer, "ffprobe_duration", return_value=600.5), patch.object(
                pipeline.subprocess, "run", return_value=probe
            ):
                result = pipeline.check_media(path)
            self.assertEqual(result["duration_seconds"], 600.5)
            self.assertEqual(result["width"], 1920)
            self.assertEqual(result["height"], 1080)

    def test_rejects_a_video_shorter_than_ten_minutes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "short.mp4"
            path.write_bytes(b"x" * 150_000)
            with patch.object(pipeline.renderer, "ffprobe_duration", return_value=599.9):
                with self.assertRaisesRegex(RuntimeError, "minimum required"):
                    pipeline.check_media(path)

    def test_rejects_missing_audio_stream(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "silent.mp4"
            path.write_bytes(b"x" * 150_000)
            probe = SimpleNamespace(
                stdout=json.dumps({
                    "streams": [{"codec_type": "video", "width": 1920, "height": 1080}]
                })
            )
            with patch.object(pipeline.renderer, "ffprobe_duration", return_value=610), patch.object(
                pipeline.subprocess, "run", return_value=probe
            ):
                with self.assertRaisesRegex(RuntimeError, "audio"):
                    pipeline.check_media(path)


class VisualManifestGateTests(unittest.TestCase):
    def test_final_gate_rejects_one_perceptually_matching_frame(self):
        assets = [
            {"id": "pexels:scene-a", "visual_hashes": [
                "1111111111111111", "2222222222222222"
            ]},
            {"id": "pixabay:scene-b", "visual_hashes": [
                "aaaaaaaaaaaaaaaa", "1111111111111111"
            ]},
        ]
        with self.assertRaisesRegex(RuntimeError, "perceptually repeated"):
            pipeline.validate_visual_manifest("astrotobby", "test-job", 2, assets)

    def test_final_gate_rejects_assets_without_fingerprints(self):
        assets = [{"id": "openverse:scene-a", "visual_hashes": []}]
        with self.assertRaisesRegex(RuntimeError, "fingerprint"):
            pipeline.validate_visual_manifest("digital_nomad", "test-job", 1, assets)

    def test_final_gate_accepts_unique_fingerprinted_scenes(self):
        assets = [
            {"id": "pexels:scene-a", "visual_hashes": ["1111111111111111", "2222222222222222"]},
            {"id": "pixabay:scene-b", "visual_hashes": ["eeeeeeeeeeeeeeee", "ffffffffffffffff"]},
        ]
        result = pipeline.validate_visual_manifest("digital_nomad", "test-job", 2, assets)
        self.assertEqual(result["policy"], "global-zero-reuse")
        self.assertEqual(result["asset_count"], 2)


if __name__ == "__main__":
    unittest.main()
