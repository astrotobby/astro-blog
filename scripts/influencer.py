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

Every step degrades gracefully: no Wav2Lip -> the look's own talking clip is used
unsynced; a still-only look -> animated still. The render never breaks here.
"""
import hashlib
import random
import subprocess

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
    """Alternating A (on camera) / B (b-roll) segments covering [0, dur]. Opens on
    camera (the face is the scroll-stopper) and closes on camera (CTA). Each A
    segment gets the next look in rotation and alternates wide / punch-in framing.
    Cuts snap to the end of a spoken word when word timings are available."""
    inf = cfg.get("influencer", {})
    a_rng = inf.get("aroll_seconds", [4.0, 7.0])
    b_rng = inf.get("broll_seconds", [3.5, 6.0])
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
        if dur - end < min_seg:              # don't leave a sliver at the end
            end = dur
        segs.append({"kind": kind, "t0": t, "t1": end})
        t, kind = end, ("B" if kind == "A" else "A")
    if not looks:
        for s in segs:
            s["kind"] = "B"
        return segs
    if segs[-1]["kind"] == "B":
        if len(segs) > 1 and segs[-1]["t1"] - segs[-1]["t0"] < min_seg * 2:
            segs[-2]["t1"] = segs[-1]["t1"]  # fold a short tail into the previous A
            segs.pop()
        else:
            segs[-1]["kind"] = "A"           # end on camera for the CTA
    seen = {}
    a_idx = 0
    for s in segs:
        if s["kind"] != "A":
            continue
        lk = looks[a_idx % len(looks)]
        a_idx += 1
        s["look"] = lk
        n = seen.get(lk["id"], 0)
        seen[lk["id"]] = n + 1
        s["close"] = n % 2 == 1              # 2nd appearance of a look -> punch-in
    log("timeline: " + " | ".join(
        f"{s['kind']}{'/' + s['look']['id'] + ('*' if s['close'] else '') if s['kind'] == 'A' else ''}"
        f" {s['t1'] - s['t0']:.1f}s" for s in segs))
    return segs


# ---------- 3. lip-sync ----------
def _face_source(lk, fps):
    """What Wav2Lip lip-syncs for a look: a short seamless boomerang of its motion
    clip (gestures keep flowing across loops), or the still image."""
    if lk.get("clip"):
        src = OUT / f"_lk_{lk['id']}_src.mp4"
        bounce = OUT / f"_lk_{lk['id']}_bounce.mp4"
        try:
            _run(["ffmpeg", "-y", "-i", str(lk["clip"]), "-an", "-r", str(fps),
                  "-filter_complex",
                  "[0:v]scale=540:-2,split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1[v]",
                  "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                  "-pix_fmt", "yuv420p", bounce.name], cwd=OUT)
            return bounce
        except Exception as e:  # noqa
            log(f"look {lk['id']}: boomerang failed ({e}); using raw clip")
            _run(["ffmpeg", "-y", "-i", str(lk["clip"]), "-an", "-r", str(fps),
                  "-vf", "scale=540:-2", "-pix_fmt", "yuv420p", src.name], cwd=OUT)
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


def _ltx_segment(client, image, audio, seg_dur, out):
    """One A-roll segment as a real talking video: LTX-2 animates the look's still
    (head, face, hands) and lip-syncs it to this slice of the narration."""
    from gradio_client import handle_file
    try:
        video, _seed = client.predict(handle_file(str(image)), handle_file(str(audio)),
                                      LTX_PROMPT, LTX_NEGATIVE,
                                      min(12.0, max(1.0, round(seg_dur + 0.2, 1))), -1,
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
            audio = OUT / f"_ltx_{tag}_{i:02d}.wav"
            _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s['t0']:.3f}", "-t", f"{seg_dur:.3f}",
                  "-i", str(voices[tag]), "-ac", "1", "-ar", "44100", audio.name], cwd=OUT)
            try:
                done[(tag, i)] = _ltx_segment(client, s["look"]["image"], audio, seg_dur,
                                              OUT / f"_talk_{tag}_{i:02d}.mp4")
                log(f"ltx: {tag}/{i} ({s['look']['id']}, {seg_dur:.1f}s) talking video")
            except _LtxQuotaError as e:
                log(f"ltx: quota reached after {len(done)} segments ({str(e)[:120]})")
                return done
            except Exception as e:  # noqa  one bad segment -> Wav2Lip for that one
                log(f"ltx: {tag}/{i} failed ({str(e)[:160]})")
    return done


def render_talking(plans, voices, cfg, fps):
    """Make every A-roll segment of every cut talk. `plans` = {tag: timeline},
    `voices` = {tag: voiceover path}. LTX-2 (influencer.ltx) animates the whole
    presenter per segment when the free quota allows. Remaining segments are grouped
    by look and Wav2Lip runs ONCE per look over the concatenated audio slices (face
    detection runs once per look, not per segment), then the result is cut back
    apart. Returns {(tag, i): clip}."""
    from avatar_lipsync import generate_talking_head
    talking = _render_ltx(plans, voices, cfg)
    by_look = {}
    for tag, segs in plans.items():
        for i, s in enumerate(segs):
            if s["kind"] == "A" and (tag, i) not in talking:
                by_look.setdefault(s["look"]["id"], (s["look"], []))[1].append((tag, i, s))

    for lid, (lk, items) in by_look.items():
        face_src = _face_source(lk, fps)
        # concat this look's audio slices -> one wav
        parts = []
        for k, (tag, i, s) in enumerate(items):
            p = OUT / f"_lk_{lid}_a{k:02d}.wav"
            _run(["ffmpeg", "-y", "-ss", f"{s['t0']:.3f}", "-t", f"{s['t1'] - s['t0']:.3f}",
                  "-i", str(voices[tag]), "-ac", "1", "-ar", "16000", p.name], cwd=OUT)
            parts.append(p)
        listf = OUT / f"_lk_{lid}_alist.txt"
        listf.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        audio = OUT / f"_lk_{lid}_audio.wav"
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf.name,
              "-c", "copy", audio.name], cwd=OUT)

        synced = None
        try:
            synced = generate_talking_head(face_src, audio, cfg, out_name=f"_lk_{lid}_talk.mp4")
        except Exception as e:  # noqa
            log(f"look {lid}: lip-sync errored ({e})")
        cursor = 0.0
        for k, (tag, i, s) in enumerate(items):
            seg_dur = _dur(parts[k])
            out = OUT / f"_talk_{tag}_{i:02d}.mp4"
            try:
                if synced:
                    _run(["ffmpeg", "-y", "-ss", f"{cursor:.3f}", "-i", str(synced),
                          "-t", f"{seg_dur:.3f}", "-an", "-r", str(fps), "-c:v", "libx264",
                          "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                          out.name], cwd=OUT)
                    talking[(tag, i)] = out
                else:
                    talking[(tag, i)] = _unsynced(face_src, cursor * 1.7 + s["t0"],
                                                  seg_dur, fps, out)
            except Exception as e:  # noqa
                log(f"look {lid}: segment {tag}/{i} cut failed ({e})")
            cursor += seg_dur
        log(f"look {lid}: {len(items)} on-camera segments "
            f"({'lip-synced' if synced else 'UNSYNCED fallback'})")
    return talking


# ---------- 4. full-screen presenter shot ----------
# Subtle, skin-friendly grade for the presenter (the glass grade is for b-roll only:
# its mint tint and lifted blacks would make real skin look plastic).
_SKIN_GRADE = ("eq=contrast=1.05:saturation=1.06:gamma=0.99,"
               "colorbalance=rm=0.02:bm=-0.02:rh=0.02,unsharp=5:5:0.55:5:5:0.0,"
               "noise=alls=3:allf=t")


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
def compose(montage, voice, words, total, size, fps, cfg, slug, tag, out):
    """Cut the presenter into a finished silent montage. B segments are slices of the
    montage at the same timestamps, so the stock footage keeps its word-locked scene
    cuts; A segments are full-screen presenter shots lip-synced to the same voice.
    Segment lengths are frame-exact so the picture stays locked to the voiceover.
    Returns `out`, or None (caller keeps the plain montage) if there are no looks."""
    inf = cfg.get("influencer", {})
    looks = pick_looks(load_looks(cfg), slug, int(inf.get("looks_per_video", 3)))
    if not looks:
        log("influencer enabled but no look media found -> plain montage")
        return None
    segs = plan_timeline(total, looks, cfg, f"{slug}|{tag}", words)
    talking = render_talking({tag: segs}, {tag: voice}, cfg, fps)

    total_frames = int(round(total * fps))
    files = []
    for i, s in enumerate(segs):
        f0 = int(round(s["t0"] * fps))
        f1 = total_frames if i == len(segs) - 1 else int(round(s["t1"] * fps))
        frames = max(1, f1 - f0)
        dst = OUT / f"_inf_{tag}_{i:02d}.mp4"
        src = (talking.get((tag, i)) or s["look"].get("image")) if s["kind"] == "A" else None
        if src is not None:
            build_aroll(src, s["look"], size, fps, frames / fps, s.get("close"), dst, cfg)
        else:
            _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{f0 / fps:.3f}", "-i", str(montage),
                  "-an", "-frames:v", str(frames), "-r", str(fps), "-c:v", "libx264",
                  "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", dst.name], cwd=OUT)
        files.append((dst, frames))

    w, h = size["w"], size["h"]
    inputs, fc = [], []
    for k, (f, frames) in enumerate(files):
        inputs += ["-i", f.name]
        fc.append(f"[{k}:v]scale={w}:{h},setsar=1,fps={fps},trim=end_frame={frames},"
                  f"setpts=PTS-STARTPTS[v{k}]")
    fc.append("".join(f"[v{k}]" for k in range(len(files)))
              + f"concat=n={len(files)}:v=1:a=0[out]")
    _run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(fc),
          "-map", "[out]", "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
          "-crf", "16", "-pix_fmt", "yuv420p", out.name], cwd=OUT)
    n_a = sum(1 for s in segs if s["kind"] == "A")
    log(f"influencer cut {w}x{h}: {n_a} on-camera + {len(segs) - n_a} b-roll -> {out.name}")
    return out
