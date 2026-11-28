#!/usr/bin/env python3
"""Patch upstream MuseTalk inference to stream rendered frames into FFmpeg.

The upstream script writes every composited frame as a PNG before encoding the
MP4. Long narrations can create tens of thousands of temporary PNGs. On Kaggle
this can exhaust the notebook disk and leave a truncated MP4. This patch keeps
the same MuseTalk V1.5 model, frames, frame rate and H.264 quality target, but
pipes BGR frames directly to FFmpeg and checks every encoder/muxer exit code.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

PATCH_MARKER = "ASTROTobby: stream MuseTalk output frames directly to FFmpeg"

STREAMING_BLOCK = r'''            # ASTROTobby: stream MuseTalk output frames directly to FFmpeg.
            # Avoid materializing thousands of full-resolution PNG files. The
            # raw BGR pipe keeps disk usage bounded for long narration tracks.
            temp_vid_path = f"{temp_dir}/temp_{input_basename}_{audio_basename}.mp4"
            ffmpeg_log_path = temp_vid_path + ".ffmpeg.log"
            frame_height, frame_width = frame_list[0].shape[:2]
            if frame_height < 1 or frame_width < 1 or fps <= 0:
                raise RuntimeError(
                    f"Invalid source frame geometry/rate: {frame_width}x{frame_height} at {fps} fps."
                )

            frame_writer = None
            with open(ffmpeg_log_path, "wb") as ffmpeg_log:
                frame_writer = subprocess.Popen(
                    [
                        "ffmpeg", "-y", "-loglevel", "error",
                        "-f", "rawvideo", "-pixel_format", "bgr24",
                        "-video_size", f"{frame_width}x{frame_height}",
                        "-framerate", str(fps), "-i", "-",
                        "-an", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "18", "-pix_fmt", "yuv420p",
                        temp_vid_path,
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=ffmpeg_log,
                )
                try:
                    for i, res_frame in enumerate(tqdm(res_frame_list)):
                        bbox = coord_list_cycle[i % (len(coord_list_cycle))]
                        ori_frame = copy.deepcopy(frame_list_cycle[i % (len(frame_list_cycle))])
                        x1, y1, x2, y2 = bbox
                        if args.version == "v15":
                            y2 = y2 + args.extra_margin
                            y2 = min(y2, frame.shape[0])
                        try:
                            res_frame = cv2.resize(
                                res_frame.astype(np.uint8),
                                (x2 - x1, y2 - y1),
                            )
                        except Exception as exc:
                            raise RuntimeError(
                                f"Could not resize MuseTalk result frame {i}: {exc}"
                            ) from exc

                        if args.version == "v15":
                            combine_frame = get_image(
                                ori_frame, res_frame, [x1, y1, x2, y2],
                                mode=args.parsing_mode, fp=fp,
                            )
                        else:
                            combine_frame = get_image(
                                ori_frame, res_frame, [x1, y1, x2, y2], fp=fp
                            )

                        if (
                            combine_frame is None
                            or getattr(combine_frame, "ndim", 0) != 3
                            or combine_frame.shape[:2] != (frame_height, frame_width)
                            or combine_frame.shape[2] != 3
                        ):
                            raise RuntimeError(
                                f"MuseTalk composited frame {i} has an unexpected shape: "
                                f"{getattr(combine_frame, 'shape', None)}; expected "
                                f"{(frame_height, frame_width, 3)}."
                            )
                        if frame_writer.stdin is None:
                            raise RuntimeError("MuseTalk FFmpeg frame pipe closed unexpectedly.")
                        frame_writer.stdin.write(
                            np.ascontiguousarray(combine_frame, dtype=np.uint8).tobytes()
                        )

                    frame_writer.stdin.close()
                    frame_writer.stdin = None
                    frame_writer_returncode = frame_writer.wait()
                except BaseException:
                    if frame_writer.stdin is not None and not frame_writer.stdin.closed:
                        frame_writer.stdin.close()
                    if frame_writer.poll() is None:
                        frame_writer.kill()
                    frame_writer.wait()
                    raise

            if frame_writer_returncode != 0:
                try:
                    encoder_log = Path(ffmpeg_log_path).read_text(
                        encoding="utf-8", errors="replace"
                    )[-4000:]
                except OSError:
                    encoder_log = "FFmpeg diagnostic log could not be read."
                raise RuntimeError(
                    f"MuseTalk frame encoder exited with code {frame_writer_returncode}: "
                    f"{encoder_log}"
                )
            if not os.path.isfile(temp_vid_path) or os.path.getsize(temp_vid_path) < 100_000:
                raise RuntimeError(
                    "MuseTalk frame encoder did not create a complete temporary MP4."
                )

            # Mux the original narration with the encoded lip-synced frames.
            mux_cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", audio_path, "-i", temp_vid_path,
                "-map", "0:a:0", "-map", "1:v:0",
                "-c:v", "copy", "-c:a", "aac",
                "-shortest", "-movflags", "+faststart",
                output_vid_name,
            ]
            mux_result = subprocess.run(
                mux_cmd, capture_output=True, text=True, check=False
            )
            if mux_result.returncode != 0:
                raise RuntimeError(
                    "MuseTalk audio/video mux failed: "
                    + (mux_result.stderr or mux_result.stdout or "No FFmpeg diagnostics.")[-4000:]
                )
            if not os.path.isfile(output_vid_name) or os.path.getsize(output_vid_name) < 100_000:
                raise RuntimeError(
                    "MuseTalk audio/video mux did not create a complete output MP4."
                )
            try:
                os.remove(ffmpeg_log_path)
            except FileNotFoundError:
                pass
''';

def patch_inference_source(path: str | Path) -> bool:
    """Apply the bounded-disk frame writer to an upstream inference.py file.

    Returns True when changed and False when the same patch is already present.
    Refuses unknown upstream source layouts rather than silently running the
    disk-heavy original implementation.
    """
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    if PATCH_MARKER in source:
        compile(source, str(source_path), "exec")
        return False

    start_marker = "            # Pad generated images to original video size\n"
    end_marker = "            # Clean up temporary files\n"
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise RuntimeError(
            "MuseTalk upstream inference.py has an unexpected layout; "
            "refusing to run without the bounded-disk frame writer."
        )
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    if end <= start:
        raise RuntimeError("MuseTalk frame-writer patch boundaries are invalid.")

    old_error_handler = (
        '        except Exception as e:\n'
        '            print("Error occurred during processing:", e)\n'
    )
    if source.count(old_error_handler) != 1:
        raise RuntimeError(
            "MuseTalk upstream task error handler changed; refusing to suppress a render failure."
        )

    patched = (
        source[:start]
        + STREAMING_BLOCK
        + source[end:]
    )
    patched = patched.replace(
        old_error_handler,
        '        except Exception as e:\n'
        '            print("Error occurred during processing:", e, flush=True)\n'
        '            raise\n',
    )
    compile(patched, str(source_path), "exec")

    temporary_path = source_path.with_suffix(source_path.suffix + ".tmp")
    temporary_path.write_text(patched, encoding="utf-8")
    os.replace(temporary_path, source_path)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inference_py", type=Path)
    args = parser.parse_args()
    changed = patch_inference_source(args.inference_py)
    print(
        "MuseTalk streaming frame-writer patch "
        + ("applied." if changed else "already present.")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
