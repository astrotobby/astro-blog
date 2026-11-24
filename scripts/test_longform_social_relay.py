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


class LongformSocialDestinationTests(unittest.TestCase):
    def test_instagram_is_not_an_automated_longform_destination(self):
        self.assertEqual(longform_social_relay.AUTOMATED_DESTINATIONS, ("facebook",))


if __name__ == "__main__":
    unittest.main()
