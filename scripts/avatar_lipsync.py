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

    # SadTalker (OpenTalker) gradio signature — VERIFIED order against the live
    # Space config: image, audio, pose_style, resolution, preprocess, still,
    # batch_size, enhancer.
    args = [
        handle_file(str(avatar_path)),
        handle_file(str(audio_path)),
        int(av.get("pose_style", 0)),
        int(av.get("resolution", 256)),     # 256 fast | 512 sharper but slower
        av.get("preprocess", "crop"),
        bool(av.get("still", True)),
        int(av.get("batch_size", 2)),
        bool(av.get("enhancer", False)),     # GFPGAN; off = much faster
    ]

    for space in spaces:
        try:
            log(f"avatar: connecting to SadTalker space '{space}'")
            client = Client(space, hf_token=token, verbose=False)
            try:  # log the real API so we can lock the signature after the first run
                log(f"avatar: {space} API ->\n{str(client.view_api(return_format='str'))[:700]}")
            except Exception:  # noqa
                pass
            res = None
            for kw in ({"api_name": "/predict"}, {"fn_index": 0},
                       {"api_name": "/test"}, {"fn_index": 1}):
                try:
                    res = client.predict(*args, **kw)
                    if res:
                        break
                except Exception as e:  # noqa
                    log(f"avatar: predict {kw} failed on {space}: {str(e)[:160]}")
            video = _video_from_result(res)
            if video and os.path.exists(video):
                dst = OUT / "talking_head.mp4"
                shutil.copy(video, dst)
                log(f"avatar: got talking head from '{space}' -> {dst.name}")
                return dst
        except Exception as e:  # noqa
            log(f"avatar: space '{space}' unavailable: {str(e)[:160]}")

    log("avatar: no space produced a video -> motion-graphics fallback")
    return None
