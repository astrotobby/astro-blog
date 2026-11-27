"""Contract checks for the reusable existing-Kling long-form presenter."""
from pathlib import Path
import json
import subprocess
import unittest
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from influencer import _face_source

import yaml

ROOT = Path(__file__).resolve().parents[1]


class KlingInfluencerAssetsTests(unittest.TestCase):
    def setUp(self):
        self.cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        self.looks = yaml.safe_load(
            (ROOT / "assets/influencer/looks.yaml").read_text(encoding="utf-8")
        )["looks"]

    def test_longform_uses_existing_presenter_clips_only(self):
        inf = self.cfg["influencer"]
        self.assertTrue(inf["enabled"])
        self.assertFalse(inf["ltx"], "LTX video generation must remain disabled")
        self.assertEqual(len(self.looks), 2)
        self.assertEqual({row['id'] for row in self.looks}, {'kling_studio_front', 'kling_studio_monitor'})
        self.assertEqual(self.cfg['influencer']['looks_per_video'], 2)
        # The committed approval library currently contains two unique views of
        # the same presenter; do not invent or substitute an unapproved third clip.
        self.assertEqual(len({row["clip"] for row in self.looks}), 2)
        for row in self.looks:
            self.assertTrue(row["clip"].endswith(".mp4"))
            self.assertTrue((ROOT / row["clip"]).is_file(), row["clip"])
            self.assertEqual(row["outfit"], "black collared shirt")

    def test_source_clips_are_short_valid_video_references(self):
        for row in self.looks:
            path = ROOT / row["clip"]
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-show_entries", "format=duration", "-of", "json", str(path),
                ],
                check=True, capture_output=True, text=True,
            )
            data = json.loads(probe.stdout)
            self.assertTrue(data.get("streams"), row["clip"])
            duration = float(data["format"]["duration"])
            self.assertGreaterEqual(duration, 3.0)
            self.assertLessEqual(duration, 8.0)

    def test_musetalk_input_matches_preview_cfr25_normalization(self):
        clip = ROOT / self.looks[0]["clip"]
        cfg = {"influencer": {"lipsync_backend": "musetalk"}}
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_out = Path(temp_dir)
            def fake_ffmpeg(command, cwd=None):
                (temp_out / command[-1]).write_bytes(b"validated-test-output" * 100)
            with patch("influencer.OUT", temp_out):
                with patch("influencer._run", side_effect=fake_ffmpeg) as ffmpeg:
                    result = _face_source({"id": "approved", "clip": str(clip)}, 24, cfg)
        self.assertTrue(result.is_file())
        command = " ".join(ffmpeg.call_args.args[0])
        self.assertIn("fps=25,scale=trunc(iw/2)*2:trunc(ih/2)*2", command)
        self.assertIn("-crf 20", command)
        self.assertIn("yuv420p", command)
        self.assertNotIn("scale=540", command)
        self.assertNotIn("reverse", command)

    def test_presenter_grade_preserves_source_skin_without_colour_effects(self):
        source = (ROOT / "scripts/influencer.py").read_text(encoding="utf-8")
        start = source.index("_SKIN_GRADE =")
        end = source.index("\n", start)
        grade = source[start:end]
        self.assertIn('format=yuv420p', grade)
        self.assertNotIn("saturation=", grade)
        self.assertNotIn("colorbalance=", grade)
        self.assertNotIn("noise=", grade)

    def test_presenter_is_not_overused_against_broll(self):
        inf = self.cfg["influencer"]
        self.assertLessEqual(float(inf["aroll_seconds"][1]), 6.0)
        self.assertGreaterEqual(float(inf["broll_seconds"][0]), 10.0)
        self.assertTrue(inf["require_lipsync"])
        self.assertGreater(float(inf["pip_height_frac"]), 0.25)
        self.assertEqual(inf["pip_position"], "top-right")

    def test_lipsync_uses_the_exact_master_audio_mixed_into_final_video(self):
        renderer = (ROOT / "scripts/generate_video.py").read_text(encoding="utf-8")
        self.assertIn("presented = compose(montage, voiced, word_timings", renderer)
        self.assertNotIn("presented = compose(montage, voice, word_timings", renderer)

    def test_longform_pipeline_uses_the_musetalk_25fps_cadence(self):
        pipeline = (ROOT / "scripts/longform_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('cfg["video"]["fps"]=25', pipeline)
        self.assertNotIn('cfg["video"]["fps"]=24', pipeline)

    def test_longform_pipeline_keeps_the_influencer_enabled(self):
        pipeline = (ROOT / "scripts/longform_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('cfg["influencer"]["enabled"]=True', pipeline)
        self.assertIn('cfg["influencer"]["ltx"]=False', pipeline)
        self.assertIn('cfg["influencer"]["lipsync_backend"]="musetalk"', pipeline)
        self.assertNotIn('cfg["influencer"]["enabled"]=False', pipeline)


if __name__ == "__main__":
    unittest.main()
