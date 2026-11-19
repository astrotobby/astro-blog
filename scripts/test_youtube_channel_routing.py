"""Offline regression tests for explicit YouTube channel-to-token routing."""

import unittest
from unittest.mock import patch

import platforms


class _Request:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _Channels:
    def __init__(self, payload):
        self.payload = payload

    def list(self, **kwargs):
        assert kwargs.get("mine") is True
        assert kwargs.get("part") == "id,snippet"
        return _Request(self.payload)


class _YouTube:
    def __init__(self, payload):
        self._channels = _Channels(payload)

    def channels(self):
        return self._channels


class YouTubeChannelRoutingTests(unittest.TestCase):
    def test_digital_nomad_aliases_use_existing_dijitol_secret(self):
        for value in ("digital_nomad", "Digital Nomad", "DIJITAL NOMAD", "DIJITOL NOMAD", "dijitolnomad001"):
            with self.subTest(value=value):
                profile = platforms._youtube_channel_profile({"channel_key": value})
                self.assertEqual(profile["key"], "digital_nomad")
                self.assertEqual(profile["token_env"], "YOUTUBE_REFRESH_TOKEN_DIGITAL_NOMAD")
                self.assertEqual(profile["expected_title"], "DIJITAL NOMAD")
                self.assertEqual(profile["owner_account"], "chanzera3@gmail.com")

    def test_astrotobbyc_aliases_use_existing_astro_tobby_secret(self):
        for value in ("astrotobbyc", "Astro Tobby", "Astro Tobbyc", "astrotobyc"):
            with self.subTest(value=value):
                profile = platforms._youtube_channel_profile({"channel_key": value})
                self.assertEqual(profile["key"], "astrotobbyc")
                self.assertEqual(profile["token_env"], "YOUTUBE_REFRESH_TOKEN_ASTROTOBBYC")
                self.assertEqual(profile["expected_title"], "Astro Tobby")
                self.assertEqual(profile["owner_account"], "goodlucktobby@gmail.com")

    def test_reads_channel_key_from_post_or_profile(self):
        self.assertEqual(
            platforms._youtube_channel_profile({"post": {"channel_key": "digital_nomad"}})["key"],
            "digital_nomad",
        )
        self.assertEqual(
            platforms._youtube_channel_profile({"channel_profile": {"key": "astrotobbyc"}})["key"],
            "astrotobbyc",
        )

    def test_no_channel_key_preserves_legacy_single_token_workflow(self):
        self.assertIsNone(platforms._youtube_channel_profile({"post": {"slug": "existing-blog-post"}}))

    def test_unknown_explicit_channel_fails_closed(self):
        with self.assertRaises(ValueError):
            platforms._youtube_channel_profile({"channel_key": "some-other-channel"})

    def test_verifies_channel_title_and_optional_id(self):
        profile = platforms._youtube_channel_profile({"channel_key": "digital_nomad"})
        yt = _YouTube({"items": [{"id": "UC_DIGITAL", "snippet": {"title": "DIJITAL NOMAD"}}]})
        with patch.object(platforms, "env", side_effect=lambda key, default="": (
            "UC_DIGITAL" if key == "YOUTUBE_CHANNEL_ID_DIGITAL_NOMAD" else default
        )):
            identity = platforms._yt_verify_channel(yt, profile)
        self.assertEqual(identity, {"id": "UC_DIGITAL", "title": "DIJITAL NOMAD"})

    def test_channel_specific_dry_run_uses_correct_profile_without_network(self):
        values = {
            "YOUTUBE_REFRESH_TOKEN_DIGITAL_NOMAD": "placeholder-token",
            "YOUTUBE_CLIENT_ID": "placeholder-client",
            "YOUTUBE_CLIENT_SECRET": "placeholder-secret",
        }
        render = {
            "channel_key": "digital_nomad",
            "platform": {"yt_title": "Test title", "yt_desc": "Test description", "hashtags": []},
            "videos": {"horizontal": "test.mp4"},
        }
        cfg = {"platforms": {"youtube": {"also_short": False}}}
        with patch.object(platforms, "env", side_effect=lambda key, default="": values.get(key, default)):
            result = platforms.post_youtube(render, cfg, dry=True)
        self.assertTrue(result["youtube"]["ok"])
        self.assertEqual(result["youtube"]["channel"], "DIJITAL NOMAD")

    def test_channel_specific_job_never_falls_back_to_generic_token(self):
        values = {
            "YOUTUBE_REFRESH_TOKEN": "legacy-token-must-not-route-to-a-channel",
            "YOUTUBE_CLIENT_ID": "placeholder-client",
            "YOUTUBE_CLIENT_SECRET": "placeholder-secret",
        }
        render = {
            "channel_key": "astrotobbyc",
            "platform": {"yt_title": "Test title", "yt_desc": "Test description", "hashtags": []},
            "videos": {"horizontal": "test.mp4"},
        }
        cfg = {"platforms": {"youtube": {"also_short": False}}}
        with patch.object(platforms, "env", side_effect=lambda key, default="": values.get(key, default)):
            result = platforms.post_youtube(render, cfg, dry=True)
        self.assertFalse(result["youtube"]["ok"])
        self.assertIn("YOUTUBE_REFRESH_TOKEN_ASTROTOBBYC", result["youtube"]["skipped"])

    def test_legacy_dry_run_still_uses_generic_token(self):
        values = {
            "YOUTUBE_REFRESH_TOKEN": "legacy-token",
            "YOUTUBE_CLIENT_ID": "placeholder-client",
            "YOUTUBE_CLIENT_SECRET": "placeholder-secret",
        }
        render = {
            "platform": {"yt_title": "Legacy test", "yt_desc": "Test description", "hashtags": []},
            "videos": {"horizontal": "test.mp4"},
            "post": {"slug": "legacy-post"},
        }
        cfg = {"platforms": {"youtube": {"also_short": False}}}
        with patch.object(platforms, "env", side_effect=lambda key, default="": values.get(key, default)):
            result = platforms.post_youtube(render, cfg, dry=True)
        self.assertTrue(result["youtube"]["ok"])
        self.assertNotIn("channel", result["youtube"])

    def test_scheduled_dry_run_records_publish_time(self):
        values = {
            "YOUTUBE_REFRESH_TOKEN_ASTROTOBBYC": "placeholder-token",
            "YOUTUBE_CLIENT_ID": "placeholder-client",
            "YOUTUBE_CLIENT_SECRET": "placeholder-secret",
        }
        publish_at = "2099-04-05T07:00:00Z"
        render = {
            "channel_key": "astrotobby",
            "scheduled_publish_at": publish_at,
            "platform": {"yt_title": "Scheduled test", "yt_desc": "Test description", "hashtags": []},
            "videos": {"horizontal": "test.mp4"},
        }
        cfg = {"platforms": {"youtube": {"also_short": False}}}
        with patch.object(platforms, "env", side_effect=lambda key, default="": values.get(key, default)):
            result = platforms.post_youtube(render, cfg, dry=True)
        self.assertTrue(result["youtube"]["ok"])
        self.assertEqual(result["youtube"]["scheduled_publish_at"], publish_at)
        self.assertEqual(result["youtube"]["privacy"], "private until scheduled time")

    def test_scheduled_dry_run_rejects_timestamp_without_timezone(self):
        values = {
            "YOUTUBE_REFRESH_TOKEN_ASTROTOBBYC": "placeholder-token",
            "YOUTUBE_CLIENT_ID": "placeholder-client",
            "YOUTUBE_CLIENT_SECRET": "placeholder-secret",
        }
        render = {
            "channel_key": "astrotobby",
            "scheduled_publish_at": "2099-04-05T07:00:00",
            "platform": {"yt_title": "Scheduled test", "yt_desc": "Test description", "hashtags": []},
            "videos": {"horizontal": "test.mp4"},
        }
        cfg = {"platforms": {"youtube": {"also_short": False}}}
        with patch.object(platforms, "env", side_effect=lambda key, default="": values.get(key, default)):
            result = platforms.post_youtube(render, cfg, dry=True)
        self.assertFalse(result["youtube"]["ok"])
        self.assertIn("timezone", result["youtube"]["error"])

    def test_wrong_channel_title_is_blocked(self):
        profile = platforms._youtube_channel_profile({"channel_key": "astrotobbyc"})
        yt = _YouTube({"items": [{"id": "UC_WRONG", "snippet": {"title": "DIJITAL NOMAD"}}]})
        with patch.object(platforms, "env", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "upload blocked"):
                platforms._yt_verify_channel(yt, profile)

    def test_wrong_configured_channel_id_is_blocked(self):
        profile = platforms._youtube_channel_profile({"channel_key": "astrotobbyc"})
        yt = _YouTube({"items": [{"id": "UC_WRONG", "snippet": {"title": "Astro Tobby"}}]})
        with patch.object(platforms, "env", return_value="UC_EXPECTED"):
            with self.assertRaisesRegex(RuntimeError, "channel ID mismatch"):
                platforms._yt_verify_channel(yt, profile)


if __name__ == "__main__":
    unittest.main()
