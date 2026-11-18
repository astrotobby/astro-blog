"""Fast offline regression tests for the long-form scheduler and safety gates."""
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


if __name__ == "__main__":
    unittest.main()
