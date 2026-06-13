"""Talking-avatar lip-sync via a free Hugging Face SadTalker Space (GPU offloaded).

Sends the avatar image + voiceover to a SadTalker Space and returns a talking-head
video WITH head motion. Tries each configured Space in order; returns None if none
answer, so generate_video falls back to the motion-graphics montage (never fails).

Needs: HF_TOKEN secret (free Hugging Face read token) + an avatar image
(assets/avatar.png). All free.
"""
import os
import shutil

from common import OUT, env, log


def _video_from_result(res):
    """gradio may return a filepath str, a list/tuple, or a dict — dig out the video."""
    if res is None:
        return None
    if isinstance(res, str):
        return res
    if isinstance(res, (list, tuple)):
        for item in res:
            v = _video_from_result(item)
            if v:
                return v
        return None
    if isinstance(res, dict):
        return res.get("video") or res.get("name") or res.get("path")
    return None


def generate_talking_head(avatar_path, audio_path, cfg):
    av = cfg.get("avatar", {})
    spaces = av.get("spaces", [])
    token = env("HF_TOKEN") or None
    if not token:
        log("avatar: no HF_TOKEN -> skipping SadTalker (motion-graphics fallback)")
        return None
    if not spaces:
        log("avatar: no spaces configured -> motion-graphics fallback")
        return None

    try:
        from gradio_client import Client
        try:
            from gradio_client import handle_file
        except Exception:  # noqa  (older client passes the path directly)
            def handle_file(p):
                return p
    except Exception as e:  # noqa
        log(f"avatar: gradio_client unavailable: {e}")
        return None

    img = handle_file(str(avatar_path))
    aud = handle_file(str(audio_path))
    pre = av.get("preprocess", "crop")
    still = bool(av.get("still", True))
    enh = bool(av.get("enhancer", False))
    batch = int(av.get("batch_size", 2))
    res = av.get("resolution", 256)
    pose = int(av.get("pose_style", 0))

    # SadTalker forks expose conflicting argument orders (the Space's /info and
    # /config disagree), so try each known ordering until one returns a video.
    # A wrong order fails fast on a type/count error before any GPU work.
    arg_orders = [
        [img, aud, pre, still, enh, batch, str(res), pose],   # /info: preprocess-first
        [img, aud, pre, still, enh, batch, int(res), pose],   # same, resolution as int
        [img, aud, pose, int(res), pre, still, batch, enh],   # /config: pose-first
    ]
    endpoints = ({"fn_index": 0}, {"api_name": "/predict"}, {"api_name": "/test"})

    for space in spaces:
        try:
            log(f"avatar: connecting to SadTalker space '{space}'")
            client = Client(space, hf_token=token, verbose=False)
            try:  # surface the real API in the log for debugging
                log(f"avatar: {space} API ->\n{str(client.view_api(return_format='str'))[:600]}")
            except Exception:  # noqa
                pass
            for ep in endpoints:
                for idx, a in enumerate(arg_orders):
                    try:
                        out = client.predict(*a, **ep)
                        v = _video_from_result(out)
                        if v and os.path.exists(v):
                            dst = OUT / "talking_head.mp4"
                            shutil.copy(v, dst)
                            log(f"avatar: SUCCESS from '{space}' {ep} order-{idx} -> {dst.name}")
                            return dst
                    except Exception as e:  # noqa
                        log(f"avatar: {space} {ep} order-{idx} failed: {str(e)[:140]}")
        except Exception as e:  # noqa
            log(f"avatar: space '{space}' unavailable: {str(e)[:160]}")

    log("avatar: no space produced a video -> motion-graphics fallback")
    return None
