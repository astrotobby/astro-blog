"""AI influencer presenter — one consistent person, rotating outfits + locations.

The influencer is ONE identity (assets/avatar.png). Each "look" is that same man in a
different outfit/location (studio suit, private jet, fine dining, supercar, ...),
listed in assets/influencer/looks.yaml as a short moving clip and/or a still. Looks
whose files don't exist yet are skipped, so the library can grow one look at a time.

Per video:
  1. pick_looks()      -> 2-3 looks, rotated by post slug (consecutive videos differ)
  2. plan_timeline()   -> alternating A-roll (presenter full-screen, on camera) and
                          B-roll (topic visuals, voice-over) segments, cut on word gaps,
                          opening AND closing on camera; each A segment cycles the look,
                          so the outfit/location changes inside the video like a vlog
  3. render_talking()  -> Wav2Lip lip-syncs ONLY the A-roll audio, ONE run per look
                          covering every cut (vertical + horizontal), then splits it back
                          into per-segment clips. Wav2Lip time ~= half a voiceover.
  4. build_aroll()     -> full-screen presenter shot with handheld drift, a slow push-in
                          and alternating wide / punch-in framing (creator jump-cut style)
  5. compose()         -> cuts the A-roll into the finished stock-footage montage, which
                          stays as the B-roll (so scene cuts remain locked to the words)

Long-form requires synchronized MuseTalk footage for every presenter interval.
When influencer.require_lipsync is true, a failed GPU job or missing output aborts
the render; no unsynchronized or presenter-free fallback is allowed. Legacy
non-required configurations may still use their configured fallback behavior.
"""
import hashlib
import random
import subprocess
from pathlib import Path

import yaml

from common import OUT, ROOT, log


def _run(cmd, **kw):
    log("$ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def _dur(path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)]).strip())


def _dims(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)])
    w, h = out.decode().strip().split("x")[:2]
    return int(w), int(h)


def _seed(slug, salt=""):
    return int(hashlib.sha256(f"{slug}|{salt}".encode()).hexdigest()[:8], 16)


# ---------- 1. look library ----------
def load_looks(cfg):
    """Looks from looks.yaml that actually have media on disk. Falls back to the
    legacy avatar.motion_video / avatar.image as a single 'studio' look, so the
    presenter works even before any new look is generated."""
    inf = cfg.get("influencer", {})
    looks = []
    lf = ROOT / inf.get("looks_file", "assets/influencer/looks.yaml")
    if lf.exists():
        for lk in (yaml.safe_load(lf.read_text(encoding="utf-8")) or {}).get("looks", []):
            clip = ROOT / lk["clip"] if lk.get("clip") else None
            img = ROOT / lk["image"] if lk.get("image") else None
            lk = dict(lk, clip=clip if clip and clip.exists() else None,
                      image=img if img and img.exists() else None)
            if lk["clip"] or lk["image"]:
                looks.append(lk)
    if not looks:
        av = cfg.get("avatar", {})
        clip = ROOT / av.get("motion_video", "assets/avatar_motion.mp4")
        img = ROOT / av.get("image", "assets/avatar.png")
        if clip.exists() or img.exists():
            looks.append({"id": "studio", "location": "studio",
                          "clip": clip if clip.exists() else None,
                          "image": img if img.exists() else None})
    log(f"influencer looks available: {[lk['id'] for lk in looks]}")
    return looks


def pick_looks(looks, slug, n):
    """n distinct looks for this post, rotated by slug so back-to-back videos open in
    different places. Prefers distinct locations, and looks with motion clips."""
    if not looks:
        return []
    rng = random.Random(_seed(slug, "looks"))
    moving = [lk for lk in looks if lk.get("clip")]
    pool = moving if len(moving) >= min(n, len(looks)) else looks
    pool = pool[:]
    rng.shuffle(pool)
    picked, seen_loc = [], set()
    for lk in pool:                         # first pass: one look per location
        if lk.get("location") not in seen_loc:
            picked.append(lk)
            seen_loc.add(lk.get("location"))
        if len(picked) == n:
            return picked
    for lk in pool:                         # then fill with remaining looks
        if lk not in picked:
            picked.append(lk)
        if len(picked) == n:
            break
    return picked


# ---------- 2. timeline ----------
def plan_timeline(dur, looks, cfg, slug, words=None):
    """Plan alternating full-screen presenter and B-roll cuts.

    The presenter is assigned to EVERY segment. A-roll uses a full-screen
    presenter; B-roll retains the same look as a small picture-in-picture
    presenter, so the host never disappears while supporting visuals are shown.
    Cuts snap to the end of a spoken word when timings are available.
    """
    inf = cfg.get("influencer", {})
    a_rng = inf.get("aroll_seconds", [4.0, 7.0])
    b_rng = inf.get("broll_seconds", [12.0, 20.0])
    min_seg = float(inf.get("min_segment", 2.5))
    rng = random.Random(_seed(slug, "timeline"))
    gaps = [float(w["end"]) for w in (words or [])]

    def snap(t):
        near = [g for g in gaps if abs(g - t) <= 0.7]
        return min(near, key=lambda g: abs(g - t)) if near else t

    segs, t, kind = [], 0.0, "A"
    while dur - t > 0.05:
        lo, hi = a_rng if kind == "A" else b_rng
        end = snap(t + rng.uniform(lo, hi))
        if dur - end < min_seg:
            end = dur
        end = min(float(dur), max(t + 0.05, end))
        segs.append({"kind": kind, "t0": t, "t1": end})
        t, kind = end, ("B" if kind == "A" else "A")

    if not looks:
        for segment in segs:
            segment["kind"] = "B"
        return segs

    if segs[-1]["kind"] == "B":
        # Keep the supporting-footage interval, then reserve a short on-camera
        # closing line. Do not turn the whole final B-roll segment into A-roll:
        # that would create two adjacent full-screen cuts with no contextual flow.
        available = segs[-1]["t1"] - segs[-1]["t0"]
        close_seconds = min(
            6.0,
            max(min_seg, float(inf.get("closing_aroll_seconds", 4.5))),
        )
        if len(segs) > 1 and available >= min_seg + close_seconds:
            close_start = segs[-1]["t1"] - close_seconds
            segs[-1]["t1"] = close_start
            segs.append({"kind": "A", "t0": close_start, "t1": float(dur)})

    seen = {}
    a_idx = 0
    active_look = looks[0]
    for segment in segs:
        if segment["kind"] == "A":
            active_look = looks[a_idx % len(looks)]
            a_idx += 1
            n = seen.get(active_look["id"], 0)
            seen[active_look["id"]] = n + 1
            segment["close"] = n % 2 == 1
        else:
            # Keep the same presenter look across the adjacent B-roll cut.
            segment["close"] = False
        segment["look"] = active_look

    missing = [i for i, segment in enumerate(segs) if not segment.get("look")]
    if missing:
        raise RuntimeError(f"Presenter missing from timeline segment(s): {missing}")

    log("timeline: " + " | ".join(
        f"{segment['kind']}/{segment['look']['id']}"
        f"{'*' if segment.get('close') else ''} {segment['t1'] - segment['t0']:.1f}s"
        for segment in segs
    ))
    return segs

# ---------- 3. lip-sync ----------
def _write_face_key(face, clip, recipe):
    """Sidecar <face>.key read by wav2lip_cached.py: the face-box cache is keyed on the
    committed clip and this recipe, not on the re-encoded file, whose bytes differ from
    run to run although its frames (and so the face boxes) are the same."""
    digest = hashlib.sha256(clip.read_bytes() + recipe.encode()).hexdigest()
    face.with_name(face.name + ".key").write_text(digest, encoding="utf-8")


def _face_source(lk, fps, cfg=None):
    """Choose the approved face clip for the selected lip-sync backend.

    MuseTalk production receives the same untouched source frames as the
    validated Kaggle preview: no 540px downscale, reverse/boomerang, extra
    H.264 generation, or pre-inference resampling. Wav2Lip retains its legacy
    normalized source path.
    """
    if lk.get("clip"):
        source = Path(lk["clip"]).resolve()
        backend = str((cfg or {}).get("influencer", {}).get(
            "lipsync_backend", "wav2lip"
        )).strip().lower()
        if backend == "musetalk":
            if not source.is_file():
                raise FileNotFoundError(f"Approved MuseTalk presenter clip is missing: {source}")
            log(f"look {lk['id']}: MuseTalk uses original approved source frames ({source.name})")
            return source

        src = OUT / f"_lk_{lk['id']}_src.mp4"
        bounce = OUT / f"_lk_{lk['id']}_bounce.mp4"
        try:
            _run(["ffmpeg", "-y", "-i", str(source), "-an", "-r", str(fps),
                  "-filter_complex",
                  "[0:v]scale=540:-2,split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1[v]",
                  "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                  "-pix_fmt", "yuv420p", bounce.name], cwd=OUT)
            _write_face_key(bounce, source, f"boomerang|540|{fps}")
            return bounce
        except Exception as e:  # noqa
            log(f"look {lk['id']}: boomerang failed ({e}); using raw clip")
            _run(["ffmpeg", "-y", "-i", str(source), "-an", "-r", str(fps),
                  "-vf", "scale=540:-2", "-pix_fmt", "yuv420p", src.name], cwd=OUT)
            _write_face_key(src, source, f"raw|540|{fps}")
            return src
    return lk["image"]

def _unsynced(face_src, offset, seg_dur, fps, out):
    """Fallback A-roll source when Wav2Lip is unavailable: the look's own talking
    clip, looped from a varying offset so repeats don't show the same gesture."""
    if str(face_src).lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return face_src
    loop_len = max(0.5, _dur(face_src))
    _run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(face_src),
          "-ss", f"{offset % loop_len:.3f}", "-t", f"{seg_dur:.3f}", "-an",
          "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
          "-pix_fmt", "yuv420p", out.name], cwd=OUT)
    return out


LTX_SPACE = "multimodalart/ltx2-audio-to-video"
LTX_PROMPT = ("A confident, charismatic man talks directly to the camera like a social media "
              "influencer explaining something exciting. Natural expressive hand gestures, "
              "small head nods and tilts, eyebrow raises, blinking, a slight smile, subtle "
              "body movement. Lips perfectly in sync with the speech. Static camera, "
              "photorealistic, natural skin.")
LTX_NEGATIVE = ("low quality, worst quality, deformed, distorted, blurry face, extra fingers, "
                "frozen face, robotic, stiff, text, watermark")


class _LtxQuotaError(RuntimeError):
    pass


def _ltx_client():
    """Client for the free LTX-2 audio-to-video Space (ZeroGPU), or None."""
    import os
    try:
        from gradio_client import Client
        return Client(LTX_SPACE, token=os.environ.get("HF_TOKEN") or None, verbose=False)
    except Exception as e:  # noqa  Space down / gradio_client missing
        log(f"ltx: Space unavailable ({str(e)[:160]})")
        return None


def _ltx_duration(seg_dur):
    """Return a supported half-second duration, or None when LTX cannot cover the cut."""
    duration = float(seg_dur)
    if duration < 1.0 or duration > 6.0:
        return None
    return min(6.0, max(1.0, round(duration * 2) / 2))


def _ltx_aspect_ratio(tag):
    """Map the output variant to the exact Gradio radio label."""
    return "9:16 (Vertical)" if tag == "vertical" else "16:9 (Cinematic)"


def _ltx_predict_inputs(image, audio, aspect_ratio, duration, seed=-1):
    """Build the current LTX-2 Space /generate inputs in the required order."""
    return (image, audio, LTX_PROMPT, LTX_NEGATIVE, aspect_ratio, duration, seed)


def _ltx_segment(client, image, audio, seg_dur, aspect_ratio, out):
    """Generate one <=6s lip-synced LTX-2 segment in the target aspect ratio."""
    from gradio_client import handle_file
    duration = _ltx_duration(seg_dur)
    if duration is None:
        raise ValueError(f"LTX-2 supports 1-6s segments; got {seg_dur:.2f}s")
    try:
        # Current Space /generate contract: image, audio, prompts, ratio, duration, seed.
        video, _seed = client.predict(
            *_ltx_predict_inputs(handle_file(str(image)), handle_file(str(audio)),
                                 aspect_ratio, duration),
            api_name="/generate")
    except Exception as e:  # noqa
        msg = str(e)
        if "quota" in msg.lower() or "limit" in msg.lower():
            raise _LtxQuotaError(msg) from e
        raise
    path = video.get("video", video) if isinstance(video, dict) else video
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-t", f"{seg_dur:.3f}", "-an",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
          out.name], cwd=OUT)
    return out


def _render_ltx(plans, voices, cfg):
    """Try LTX-2 for every A-roll segment, vertical cut first (it reaches the most
    platforms), up to influencer.ltx_max_segments. Stops at the first quota error;
    whatever is left falls back to Wav2Lip. Returns {(tag, i): clip}."""
    inf = cfg.get("influencer", {})
    budget = int(inf.get("ltx_max_segments", 12))
    if not inf.get("ltx") or budget <= 0:
        return {}
    client = _ltx_client()
    if client is None:
        return {}
    done = {}
    order = sorted(plans, key=lambda t: t != "vertical")
    for tag in order:
        for i, s in enumerate(plans[tag]):
            if s["kind"] != "A" or not s["look"].get("image") or len(done) >= budget:
                continue
            seg_dur = s["t1"] - s["t0"]
            if _ltx_duration(seg_dur) is None:
                log(f"ltx: {tag}/{i} is {seg_dur:.1f}s; outside the 1-6s Space limit -> Wav2Lip")
                continue
            audio = OUT / f"_ltx_{tag}_{i:02d}.wav"
            _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s['t0']:.3f}", "-t", f"{seg_dur:.3f}",
                  "-i", str(voices[tag]), "-ac", "1", "-ar", "44100", audio.name], cwd=OUT)
            try:
                done[(tag, i)] = _ltx_segment(
                    client, s["look"]["image"], audio, seg_dur, _ltx_aspect_ratio(tag),
                    OUT / f"_talk_{tag}_{i:02d}.mp4")
                log(f"ltx: {tag}/{i} ({s['look']['id']}, {seg_dur:.1f}s) talking video")
            except _LtxQuotaError as e:
                log(f"ltx: quota reached after {len(done)} segments ({str(e)[:120]})")
                return done
            except Exception as e:  # noqa  one bad segment -> Wav2Lip for that one
                log(f"ltx: {tag}/{i} failed ({str(e)[:160]})")
    return done


def render_talking(plans, voices, cfg, fps):
    """Lip-sync every presenter interval, including B-roll picture-in-picture.

    Each look's speech slices are concatenated into one audio track. MuseTalk 1.5
    processes one task per look in a single private Kaggle GPU session; the result
    is split back into the timeline's frame-exact segments.
    """
    inf_cfg = cfg.get("influencer", {})
    talking = _render_ltx(plans, voices, cfg)
    by_look = {}
    for tag, segments in plans.items():
        for index, segment in enumerate(segments):
            if segment.get("look") and (tag, index) not in talking:
                by_look.setdefault(
                    segment["look"]["id"], (segment["look"], [])
                )[1].append((tag, index, segment))

    prepared = []
    for look_id, (look, items) in by_look.items():
        face_src = _face_source(look, fps, cfg)
        parts = []
        for part_index, (tag, index, segment) in enumerate(items):
            audio_part = OUT / f"_lk_{look_id}_a{part_index:02d}.wav"
            _run([
                "ffmpeg", "-y", "-ss", f"{segment['t0']:.3f}",
                "-t", f"{segment['t1'] - segment['t0']:.3f}",
                "-i", str(voices[tag]), "-ac", "1", "-ar", "16000",
                audio_part.name,
            ], cwd=OUT)
            parts.append(audio_part)

        list_file = OUT / f"_lk_{look_id}_alist.txt"
        list_file.write_text(
            "".join(f"file '{part.name}'\n" for part in parts),
            encoding="utf-8",
        )
        combined_audio = OUT / f"_lk_{look_id}_audio.wav"
        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i",
            list_file.name, "-c", "copy", combined_audio.name,
        ], cwd=OUT)
        prepared.append({
            "id": look_id,
            "look": look,
            "items": items,
            "parts": parts,
            "face": Path(face_src),
            "audio": combined_audio,
            "output": OUT / f"_lk_{look_id}_musetalk.mp4",
        })

    backend = str(inf_cfg.get("lipsync_backend", "wav2lip")).strip().lower()
    synced_by_look = {}
    if prepared and backend == "musetalk":
        from musetalk_kaggle_batch import generate_batch

        batch_tasks = [
            {
                "id": group["id"],
                "video": group["face"],
                "audio": group["audio"],
                "output": group["output"],
            }
            for group in prepared
        ]
        # MuseTalk failures are fatal when lip-sync is required. Never silently
        # replace the approved production model with unsynchronized source footage.
        synced_by_look = generate_batch(batch_tasks)
    elif prepared and backend == "wav2lip":
        from avatar_lipsync import generate_talking_head

        for group in prepared:
            try:
                result = generate_talking_head(
                    group["face"], group["audio"], cfg,
                    out_name=group["output"].name,
                )
                if result:
                    synced_by_look[group["id"]] = Path(result)
            except Exception as exc:
                log(f"look {group['id']}: Wav2Lip failed ({str(exc)[:200]})")
    elif prepared:
        raise ValueError(
            f"Unsupported influencer.lipsync_backend={backend!r}; "
            "choose 'musetalk' or 'wav2lip'."
        )

    for group in prepared:
        look_id = group["id"]
        synced = synced_by_look.get(look_id)
        if not synced and inf_cfg.get("require_lipsync", False):
            raise RuntimeError(
                f"look {look_id}: required {backend} lip-sync failed; "
                "refusing to use unsynchronized presenter footage"
            )

        cursor = 0.0
        for part_index, (tag, index, segment) in enumerate(group["items"]):
            segment_duration = _dur(group["parts"][part_index])
            output = OUT / f"_talk_{tag}_{index:02d}.mp4"
            try:
                if synced:
                    _run([
                        "ffmpeg", "-y", "-ss", f"{cursor:.3f}", "-i", str(synced),
                        "-t", f"{segment_duration:.3f}", "-an", "-r", str(fps),
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-pix_fmt", "yuv420p", output.name,
                    ], cwd=OUT)
                    if not output.is_file() or output.stat().st_size < 1000:
                        raise RuntimeError("lip-synced presenter segment was not created")
                    talking[(tag, index)] = output
                else:
                    talking[(tag, index)] = _unsynced(
                        group["face"], cursor * 1.7 + segment["t0"],
                        segment_duration, fps, output,
                    )
            except Exception as exc:
                if inf_cfg.get("require_lipsync", False):
                    raise RuntimeError(
                        f"look {look_id}: presenter segment {tag}/{index} failed: {exc}"
                    ) from exc
                log(f"look {look_id}: presenter segment {tag}/{index} failed ({exc})")
            cursor += segment_duration

        log(
            f"look {look_id}: {len(group['items'])} presenter intervals "
            f"processed with {backend}"
        )
    return talking

# ---------- 4. full-screen presenter shot ----------
# Preserve the source presenter's real skin tone, texture and lighting.
# Do not apply a cosmetic grade, saturation shift, noise overlay or sharpening here.
_SKIN_GRADE = "format=yuv420p"


def build_aroll(src, look, size, fps, seg_dur, close, out, cfg):
    """Full-screen presenter: cover-crop on the face, handheld drift, slow push-in,
    and wide vs punch-in framing. Landscape cuts put the portrait presenter over a
    blurred fill of the same shot."""
    inf = cfg.get("influencer", {})
    w, h = size["w"], size["h"]
    punch = float(inf.get("punch_in", 1.22)) if close else 1.0
    shake = float(inf.get("handheld_px", 7))
    push = float(inf.get("push_in", 0.045))
    fcx = float(look.get("face_cx", 0.5))
    fcy = float(look.get("face_cy", 0.32))
    frames = max(1, int(seg_dur * fps))
    is_still = str(src).lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    inp = (["-loop", "1", "-framerate", str(fps), "-i", str(src)] if is_still
           else ["-stream_loop", "-1", "-i", str(src)])
    sw, sh = _dims(src)
    # slow push-in (stills get extra zoom + push so they don't read as a photo) plus
    # layered-sine handheld wobble, centred on the pre-cropped frame
    z0, pz = (1.04, push * 2) if is_still else (1.0, push)
    zp = (f"zoompan=z='{z0}+{pz}*on/{frames}':"
          f"x='iw/2-iw/zoom/2+{shake}*sin(on/{fps}*1.3)+{shake * 0.6:.1f}*sin(on/{fps}*3.1)':"
          f"y='ih/2-ih/zoom/2+{shake * 0.8:.1f}*sin(on/{fps}*1.1+1)':"
          f"d=1:s={w}x{h}:fps={fps}")

    if h >= w:
        # cover the vertical frame (x punch, +6% margin for the wobble), crop around
        # the face: wide keeps head-and-torso, punch-in sits the face in the top third
        m = 1.06
        f = max(w / sw, h / sh) * punch * m
        W, H = int(sw * f) // 2 * 2, int(sh * f) // 2 * 2
        cw, ch = int(w * m) // 2 * 2, int(h * m) // 2 * 2
        cx = max(0, min(int(W * fcx - cw / 2), W - cw))
        cy = max(0, min(int(H * fcy - ch * (0.33 if close else 0.30)), H - ch))
        fc = (f"[0:v]scale={W}:{H}:flags=lanczos,crop={cw}:{ch}:{cx}:{cy},{zp},"
              f"{_SKIN_GRADE},format=yuv420p[out]")
    else:
        # landscape: blurred, darkened fill + sharp portrait presenter, centred
        fh = int(h * punch) // 2 * 2
        fw = int(sw * fh / sh) // 2 * 2
        crop_y = f"(ih-{h})*{min(1.0, fcy * 1.4):.3f}" if close else "0"
        fc = (f"[0:v]split[a][b];"
              f"[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"gblur=sigma=28,eq=brightness=-0.12:saturation=0.85[bg];"
              f"[b]scale={fw}:{fh}:flags=lanczos,crop=iw:{h}:0:{crop_y}[fg];"
              f"[bg][fg]overlay=x='(W-w)/2+{shake}*sin(t*1.3)':y='{shake * 0.6}*sin(t*1.1)',"
              f"zoompan=z='1+{push}*on/{frames}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
              f"d=1:s={w}x{h}:fps={fps},{_SKIN_GRADE},format=yuv420p[out]")
    _run(["ffmpeg", "-y", *inp, "-filter_complex", fc, "-map", "[out]", "-an",
          "-t", f"{seg_dur:.3f}", "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
          "-crf", "19", "-pix_fmt", "yuv420p", out.name], cwd=OUT)
    return out


# ---------- 5. final cut ----------
def build_broll_with_presenter(montage, presenter, size, fps, start, seg_dur, out, cfg):
    """Show contextual B-roll with the lip-synced presenter continuously inset.

    The inset is kept above the caption-safe lower third, retains the source
    presenter's portrait aspect ratio, and uses only a light frame/shadow so the
    original face and skin texture are not cosmetically altered.
    """
    inf = cfg.get("influencer", {})
    w, h = int(size["w"]), int(size["h"])
    source_w, source_h = _dims(presenter)
    height_frac = float(inf.get("pip_height_frac", 0.36))
    height_frac = min(0.48, max(0.20, height_frac))
    pip_h = max(120, int(h * height_frac) // 2 * 2)
    aspect = source_w / max(1, source_h)
    pip_w = max(80, int(pip_h * aspect) // 2 * 2)
    border = max(4, int(min(w, h) * 0.006))
    outer_w, outer_h = pip_w + 2 * border, pip_h + 2 * border
    margin_x = max(16, int(w * float(inf.get("pip_margin_x", 0.035))))
    margin_y = max(16, int(h * float(inf.get("pip_margin_y", 0.045))))
    position = str(inf.get("pip_position", "top-right")).lower()
    positions = {
        "top-right": (w - outer_w - margin_x, margin_y),
        "top-left": (margin_x, margin_y),
        "bottom-right": (w - outer_w - margin_x, h - outer_h - margin_y),
        "bottom-left": (margin_x, h - outer_h - margin_y),
    }
    if position not in positions:
        raise ValueError(f"Unsupported influencer PiP position: {position}")
    x, y = positions[position]
    if x < 0 or y < 0 or x + outer_w > w or y + outer_h > h:
        raise ValueError(
            f"Presenter PiP ({outer_w}x{outer_h}) does not fit {w}x{h} at {position}"
        )

    filter_complex = (
        f"[0:v]fps={fps},scale={w}:{h},setsar=1,"
        f"trim=duration={seg_dur:.3f},setpts=PTS-STARTPTS[bg];"
        f"[bg]drawbox=x={x+6}:y={y+7}:w={outer_w}:h={outer_h}:"
        f"color=black@0.42:t=fill[shadow];"
        f"[1:v]fps={fps},scale={pip_w}:{pip_h}:flags=lanczos,"
        f"pad={outer_w}:{outer_h}:{border}:{border}:color=white,"
        f"setsar=1,trim=duration={seg_dur:.3f},setpts=PTS-STARTPTS[pip];"
        f"[shadow][pip]overlay=x={x}:y={y}:shortest=1,format=yuv420p[out]"
    )
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-i", str(montage),
        "-i", str(presenter),
        "-filter_complex", filter_complex,
        "-map", "[out]", "-an", "-t", f"{seg_dur:.3f}",
        "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "19", "-pix_fmt", "yuv420p", out.name,
    ], cwd=OUT)
    return out


def compose(montage, voice, words, total, size, fps, cfg, slug, tag, out):
    """Composite the presenter across the full video timeline.

    A-roll: full-screen, lip-synced presenter.
    B-roll / cards / stills: contextual footage with the same lip-synced presenter
    retained as a compact picture-in-picture. There is no presenter-free interval.
    """
    inf = cfg.get("influencer", {})
    looks = pick_looks(load_looks(cfg), slug, int(inf.get("looks_per_video", 3)))
    if not looks:
        if inf.get("require_lipsync", False):
            raise RuntimeError("Required influencer media is missing; refusing to render a presenter-free video")
        log("influencer enabled but no look media found -> plain montage")
        return None
    if inf.get("require_lipsync", False) and len(looks) < int(inf.get("looks_per_video", 3)):
        raise RuntimeError(
            f"Only {len(looks)} influencer looks are available; "
            f"need {inf.get('looks_per_video', 3)} approved presenter clips"
        )

    segs = plan_timeline(total, looks, cfg, f"{slug}|{tag}", words)
    if inf.get("require_lipsync", False):
        missing = [i for i, segment in enumerate(segs) if not segment.get("look")]
        if missing:
            raise RuntimeError(f"Presenter must be present in every segment; missing indexes: {missing}")

    talking = render_talking({tag: segs}, {tag: voice}, cfg, fps)
    total_frames = int(round(total * fps))
    files = []
    for i, segment in enumerate(segs):
        f0 = int(round(segment["t0"] * fps))
        f1 = total_frames if i == len(segs) - 1 else int(round(segment["t1"] * fps))
        frames = max(1, f1 - f0)
        seg_dur = frames / fps
        dst = OUT / f"_inf_{tag}_{i:02d}.mp4"
        presenter = talking.get((tag, i))
        if segment["kind"] == "A":
            if presenter is None:
                if inf.get("require_lipsync", False):
                    raise RuntimeError(f"Presenter full-screen segment {tag}/{i} has no synchronized clip")
                presenter = segment["look"].get("image")
            if presenter is None:
                raise RuntimeError(f"No presenter source available for A-roll segment {tag}/{i}")
            build_aroll(presenter, segment["look"], size, fps, seg_dur,
                        segment.get("close", False), dst, cfg)
        else:
            if presenter is None:
                if inf.get("require_lipsync", False):
                    raise RuntimeError(f"Presenter PiP segment {tag}/{i} has no synchronized clip")
                presenter = _unsynced(
                    _face_source(segment["look"], fps, cfg),
                    segment["t0"], seg_dur, fps,
                    OUT / f"_inf_{tag}_{i:02d}_unsynced.mp4",
                )
            build_broll_with_presenter(
                montage, presenter, size, fps, segment["t0"], seg_dur, dst, cfg
            )
        if inf.get("require_lipsync", False) and (
            not dst.is_file() or dst.stat().st_size < 1000
        ):
            raise RuntimeError(f"Presenter composition failed for segment {tag}/{i}")
        files.append((dst, frames))

    w, h = size["w"], size["h"]
    inputs, filters = [], []
    for k, (file_path, frames) in enumerate(files):
        inputs += ["-i", file_path.name]
        filters.append(
            f"[{k}:v]scale={w}:{h},setsar=1,fps={fps},trim=end_frame={frames},"
            f"setpts=PTS-STARTPTS[v{k}]"
        )
    filters.append(
        "".join(f"[v{k}]" for k in range(len(files)))
        + f"concat=n={len(files)}:v=1:a=0[out]"
    )
    _run([
        "ffmpeg", "-y", "-v", "error", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[out]", "-r", str(fps), "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", out.name,
    ], cwd=OUT)
    presenter_frames = sum(frames for _, frames in files)
    if inf.get("require_lipsync", False) and presenter_frames != total_frames:
        raise RuntimeError(
            f"Presenter coverage is incomplete: {presenter_frames}/{total_frames} frames"
        )
    n_a = sum(1 for segment in segs if segment["kind"] == "A")
    n_b = len(segs) - n_a
    log(
        f"influencer coverage {w}x{h}: {n_a} full-screen + "
        f"{n_b} PiP segments; {presenter_frames}/{total_frames} frames covered"
    )
    return out

# ---------- one-time setup ----------
def warm_face_cache(cfg):
    """Detect and cache the face boxes of every look's moving clip (committed under
    assets/influencer/facecache), so renders lip-sync without re-running detection.
    Builds each face source exactly as render_talking() does, so the cache keys match."""
    from avatar_lipsync import warm_face_cache as warm
    fps = cfg["video"]["fps"]
    backend = str(cfg.get("influencer", {}).get("lipsync_backend", "wav2lip")).lower()
    if backend == "musetalk":
        log("MuseTalk uses original frames directly; Wav2Lip face-cache warmup is skipped.")
        return
    for lk in load_looks(cfg):
        if lk.get("clip"):
            ok = warm(_face_source(lk, fps, cfg))
            log(f"face-cache {'ready' if ok else 'unavailable'}: {lk['id']}")


if __name__ == "__main__":
    import sys
    from common import load_config
    if sys.argv[1:] == ["--warm-face-cache"]:
        warm_face_cache(load_config())
    else:
        sys.exit("usage: python scripts/influencer.py --warm-face-cache")
