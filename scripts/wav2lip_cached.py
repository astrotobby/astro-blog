"""Wav2Lip inference with a persistent face-detection cache.

Face detection (S3FD on CPU) is the slow part of lip-syncing a MOVING base clip: it runs
on every frame, every render, although the influencer's base clips never change. This
wrapper runs Wav2Lip's own inference.py but swaps its face_detect() for one that saves
the per-frame face boxes to assets/influencer/facecache/<key>.npy and reuses them.
The key is the face video's bytes plus the box options, so any change re-detects.

  (cwd = Wav2Lip/)  python wav2lip_cached.py <inference.py args>
  (cwd = Wav2Lip/)  python wav2lip_cached.py --warm-only <inference.py args>

--warm-only detects and caches the boxes without lip-syncing (no audio is read).
"""
import hashlib
import os
import sys
from pathlib import Path

import numpy as np

CACHE_DIR = Path(__file__).resolve().parents[1] / "assets" / "influencer" / "facecache"


def _key(inf):
    a = inf.args
    opts = repr((list(a.pads), bool(a.nosmooth), a.resize_factor, list(a.crop), bool(a.rotate)))
    return hashlib.sha256(Path(a.face).read_bytes() + opts.encode()).hexdigest()[:24]


def _cached_face_detect(inf, original):
    cache = CACHE_DIR / f"{_key(inf)}.npy"

    def face_detect(images):
        if cache.exists():
            boxes = np.load(cache)
            if len(boxes) >= len(images):
                print(f"[facecache] reusing {cache.name} ({len(images)} frames)")
                return [[img[y1:y2, x1:x2], (y1, y2, x1, x2)]
                        for img, (y1, y2, x1, x2) in zip(images, boxes.tolist())]
        results = original(images)
        if len(images) > 1:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            np.save(cache, np.array([coords for _crop, coords in results], dtype=np.int32))
            print(f"[facecache] saved {cache.name} ({len(images)} frames)")
        return results

    return face_detect


def _read_frames(path):
    import cv2
    stream, frames = cv2.VideoCapture(path), []
    while True:
        ok, frame = stream.read()
        if not ok:
            break
        frames.append(frame)
    stream.release()
    return frames


def main():
    warm = sys.argv[1:2] == ["--warm-only"]
    if warm:
        sys.argv.pop(1)
    sys.path.insert(0, os.getcwd())
    import inference as inf  # Wav2Lip's script; parses sys.argv on import

    inf.face_detect = _cached_face_detect(inf, inf.face_detect)
    if warm:
        if not inf.args.static:
            inf.face_detect(_read_frames(inf.args.face))
        return
    inf.main()


if __name__ == "__main__":
    main()
