"""Media-only tests for the long-form social relay. No external accounts are contacted."""
import sys
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import longform_social_relay  # noqa: E402


class InstagramVerticalRenderTests(unittest.TestCase):
    def test_full_frame_vertical_reel_is_created_without_cropping_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            out_dir = root / "out"
            out_dir.mkdir()

            command = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-t", "61", "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34",
                "-c:a", "aac", "-b:a", "64k", str(source),
            ]
            subprocess.run(command, check=True, capture_output=True, timeout=300)

            with patch.object(longform_social_relay, "OUT", out_dir):
                output = longform_social_relay._make_instagram_vertical(
                    source, "test-instagram-vertical"
                )

            self.assertTrue(output.exists())
            media = longform_social_relay._probe_video(output)
            self.assertEqual((media["width"], media["height"]), (1080, 1920))
            self.assertGreaterEqual(media["duration_seconds"], 60)
            self.assertLessEqual(media["duration_seconds"], 15 * 60)
            self.assertLess(media["bytes"], 1_000_000_000)
            self.assertTrue(source.exists(), "The source 16:9 master must remain untouched")


if __name__ == "__main__":
    unittest.main()
