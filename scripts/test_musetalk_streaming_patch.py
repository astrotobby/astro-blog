"""Tests for the bounded-disk patch applied to upstream MuseTalk inference."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from musetalk_streaming_patch import patch_inference_source, PATCH_MARKER


UPSTREAM_FIXTURE = '''import os
import cv2
import copy
import subprocess
import numpy as np
from pathlib import Path

def main(args):
    try:
        # Pad generated images to original video size
        for i, res_frame in enumerate(tqdm(res_frame_list)):
            bbox = coord_list_cycle[i%(len(coord_list_cycle))]
            ori_frame = copy.deepcopy(frame_list_cycle[i%(len(frame_list_cycle))])
            x1, y1, x2, y2 = bbox
            if args.version == "v15":
                y2 = y2 + args.extra_margin
                y2 = min(y2, frame.shape[0])
            try:
                res_frame = cv2.resize(res_frame.astype(np.uint8), (x2-x1, y2-y1))
            except:
                continue

            if args.version == "v15":
                combine_frame = get_image(ori_frame, res_frame, [x1, y1, x2, y2], mode=args.parsing_mode, fp=fp)
            else:
                combine_frame = get_image(ori_frame, res_frame, [x1, y1, x2, y2], fp=fp)
            cv2.imwrite(f"{result_img_save_path}/{str(i).zfill(8)}.png", combine_frame)

        # Save prediction results
        temp_vid_path = f"{temp_dir}/temp_{input_basename}_{audio_basename}.mp4"
        cmd_img2video = f"ffmpeg -y -v warning -r {fps} -f image2 -i {result_img_save_path}/%08d.png -vcodec libx264 -vf format=yuv420p -crf 18 {temp_vid_path}"
        print("Video generation command:", cmd_img2video)
        os.system(cmd_img2video)

        cmd_combine_audio = f"ffmpeg -y -v warning -i {audio_path} -i {temp_vid_path} {output_vid_name}"
        print("Audio combination command:", cmd_combine_audio)
        os.system(cmd_combine_audio)

        # Clean up temporary files
        shutil.rmtree(result_img_save_path)
        os.remove(temp_vid_path)

        shutil.rmtree(save_dir_full)
        if not args.saved_coord:
            os.remove(crop_coord_save_path)
    except Exception as e:
        print("Error occurred during processing:", e)
'''


class MuseTalkStreamingPatchTests(unittest.TestCase):
    def test_patch_replaces_png_sequence_with_raw_frame_pipe(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inference.py"
            path.write_text(UPSTREAM_FIXTURE, encoding="utf-8")
            self.assertTrue(patch_inference_source(path))
            updated = path.read_text(encoding="utf-8")
            compile(updated, str(path), "exec")
            self.assertIn(PATCH_MARKER, updated)
            self.assertIn('"rawvideo"', updated)
            self.assertIn("frame_writer.stdin.write", updated)
            self.assertIn("frame_writer_returncode", updated)
            self.assertIn("mux_result.returncode", updated)
            self.assertNotIn("cv2.imwrite", updated)
            self.assertNotIn("os.system(cmd_img2video)", updated)
            self.assertNotIn("os.system(cmd_combine_audio)", updated)
            self.assertRegex(updated, r"except Exception as e:\\n\\s+print\\(.+flush=True\\)\\n\\s+raise")

    def test_patch_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inference.py"
            path.write_text(UPSTREAM_FIXTURE, encoding="utf-8")
            self.assertTrue(patch_inference_source(path))
            once = path.read_text(encoding="utf-8")
            self.assertFalse(patch_inference_source(path))
            self.assertEqual(path.read_text(encoding="utf-8"), once)

    def test_unknown_upstream_layout_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inference.py"
            path.write_text("def main():\\n    pass\\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unexpected layout"):
                patch_inference_source(path)


if __name__ == "__main__":
    unittest.main()
