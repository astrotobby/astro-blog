"""Regression tests proving Instagram is excluded from every long-form crosspost route."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import crosspost_longform  # noqa: E402


class LongformCrosspostDestinationTests(unittest.TestCase):
    def test_longform_destinations_exclude_instagram(self):
        self.assertEqual(crosspost_longform.LONGFORM_DESTINATIONS, ("facebook", "rumble"))

    def test_instagram_credentials_do_not_enable_longform_instagram(self):
        with patch.dict(
            os.environ,
            {"INSTAGRAM_USER_ID": "test-user", "INSTAGRAM_TOKEN": "test-token"},
            clear=False,
        ), patch.object(crosspost_longform.platforms, "ig_token", return_value="test-token") as ig_token:
            self.assertFalse(crosspost_longform._has_credentials("instagram"))
            ig_token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
