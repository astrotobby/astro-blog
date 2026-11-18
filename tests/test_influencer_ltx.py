"""Regression tests for the Hugging Face LTX-2 Gradio contract."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from influencer import _ltx_aspect_ratio, _ltx_duration, _ltx_predict_inputs


class LtxContractTests(unittest.TestCase):
    def test_vertical_uses_exact_gradio_choice(self):
        self.assertEqual(_ltx_aspect_ratio("vertical"), "9:16 (Vertical)")

    def test_horizontal_uses_exact_gradio_choice(self):
        self.assertEqual(_ltx_aspect_ratio("horizontal"), "16:9 (Cinematic)")

    def test_duration_is_rounded_to_half_seconds(self):
        self.assertEqual(_ltx_duration(4.26), 4.5)
        self.assertEqual(_ltx_duration(5.9), 6.0)

    def test_generate_request_uses_seven_inputs_in_current_order(self):
        args = _ltx_predict_inputs("image", "audio", "9:16 (Vertical)", 6.0)
        self.assertEqual(len(args), 7)
        self.assertEqual(args[0:2], ("image", "audio"))
        self.assertEqual(args[4], "9:16 (Vertical)")
        self.assertEqual(args[5:], (6.0, -1))

    def test_out_of_range_segments_fall_back(self):
        self.assertIsNone(_ltx_duration(6.01))
        self.assertIsNone(_ltx_duration(0.9))


if __name__ == "__main__":
    unittest.main()
