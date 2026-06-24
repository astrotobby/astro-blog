"""Stage 3: render video(s) from script.json — all free, no paid API.

  edge-tts        -> voiceover.mp3   (free Microsoft neural voices, no key)
  Pollinations    -> scene_*.jpg     (free AI images, no key)
  faster-whisper  -> captions.srt    (local, optional)
  ffmpeg          -> video_9x16.mp4 [+ video_16x9.mp4]

Usage: python scripts/generate_video.py .pipeline/script.json
"""
import argparse
import asyncio
import subprocess
import urllib.parse

import requests

from common import OUT, ROOT, env, load_config, log, read_json, write_json


def run(cmd, **kw):
    log("$ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def ffprobe_duration(path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)]
    )
    return float(out.strip())


# ---------- 1. voiceover ----------
async def _tts(text, voice, rate, pitch, out_path):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await comm.save(str(out_path))


def _gtts_fallback(text, out_path):
    """Robust fallback: gTTS (Google) works from datacenter IPs where Microsoft's
    edge endpoint sometimes 403s. Lower quality, but the pipeline never dies here."""
    from gtts import gTTS
    gTTS(text).save(str(out_path))


def make_voice(script, cfg):
    v = cfg["voice"]
    # Cloned voice (free OpenVoice) when enabled; edge-tts is the automatic fallback
    # so the render never breaks if cloning is unavailable.
    if v.get("clone"):
        try:
            from voice_clone import synthesize
            cw = OUT / "voiceover_clone.wav"
            if cw.exists():
                cw.unlink()
            if synthesize(script["narration"], str(cw), cfg):
                dur = ffprobe_duration(cw)
                log(f"voiceover (CLONED) {dur:.1f}s -> {cw.name}")
                return cw, dur
            log("voice clone unavailable -> edge-tts")
        except Exception as e:  # noqa
            log(f"voice clone errored ({e}) -> edge-tts")
    out = OUT / "voiceover.mp3"
    if out.exists():
        out.unlink()
    try:
        asyncio.run(_tts(script["narration"], v["name"], v["rate"], v["pitch"], out))
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("edge-tts produced no audio")
    except Exception as e:  # noqa
        log(f"edge-tts failed ({e}); falling back to gTTS")
        _gtts_fallback(script["narration"], out)
    dur = ffprobe_duration(out)
    log(f"voiceover {dur:.1f}s -> {out.name}")
    return out, dur


# ---------- 2. images ----------
def _valid_image(path):
    """A real, decodable image of non-trivial size (catches error pages / empties)."""
    try:
        from PIL import Image
        if path.stat().st_size < 2048:
            return False
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:  # noqa
        return False


def _fallback_image(path, w, h, i):
    """Generated gradient so a failed Pollinations fetch still yields a usable scene
    and ffmpeg always has valid input (this is what was killing the render)."""
    from PIL import Image
    base = [(20, 24, 48), (40, 20, 60), (10, 40, 50),
            (50, 30, 20), (25, 25, 25), (15, 35, 35)][i % 6]
    strip = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        strip.putpixel((0, y), tuple(int(base[c] * (1 - t) + min(255, base[c] + 70) * t)
                                     for c in range(3)))
    strip.resize((w, h)).save(path, "JPEG", quality=85)


def _hf_image(prompt, token):
    """Topical AI image via the free Hugging Face Inference API (reuses HF_TOKEN).
    Returns raw image bytes or None."""
    if not token:
        return None
    import time
    models = ["black-forest-labs/FLUX.1-schnell", "stabilityai/sdxl-turbo"]
    headers = {"Authorization": f"Bearer {token}"}
    # portrait dims (multiples of 16); build_clip re-frames to the exact size anyway
    payload = {"inputs": prompt, "parameters": {"width": 768, "height": 1344}}
    for model in models:
        url = f"https://api-inference.huggingface.co/models/{model}"
        for _ in range(3):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=120)
                if r.status_code == 200 and r.content[:2] in (b"\xff\xd8", b"\x89P"):
                    return r.content
                if r.status_code == 503:          # model warming up -> wait & retry
                    time.sleep(10)
                    continue
                break                              # 404/other -> try next model
            except Exception:  # noqa
                break
    return None


def _picsum_image(seed, w, h):
    """Reliable real photo (no key, no payment) when AI generation is unavailable."""
    try:
        r = requests.get(f"https://picsum.photos/seed/{seed}/{w}/{h}", timeout=60)
        if r.status_code == 200 and len(r.content) > 2048:
            return r.content
    except Exception:  # noqa
        pass
    return None


def fetch_images(script, cfg):
    """Tiered, all-free image source (Pollinations dropped — it now returns 402):
      1) Hugging Face Inference API  -> topical AI image (uses HF_TOKEN)
      2) Lorem Picsum                -> reliable real photo, no key
      3) generated gradient          -> last resort so ffmpeg always has input
    """
    vz = cfg["visuals"]
    w, h = vz["width"], vz["height"]
    token = env("HF_TOKEN") or None
    slug = script["post"]["slug"]
    paths = []
    for i, prompt in enumerate(script["scene_prompts"]):
        dst = OUT / f"scene_{i:02d}.jpg"
        content, src = _hf_image(prompt, token), "HF-AI"
        if not content:
            content, src = _picsum_image(f"{slug}-{i}", w, h), "picsum"
        if content:
            dst.write_bytes(content)
        if not _valid_image(dst):
            _fallback_image(dst, w, h, i)
            src = "gradient"
        log(f"scene {i} -> {dst.name} ({src})")
        paths.append(dst)
    return paths


# ---------- 3. captions ----------
def _text_captions(script, dur):
    """Build an SRT from the narration text spread across the audio duration — no
    whisper needed, so on-screen captions ALWAYS appear (timing is approximate)."""
    words = (script.get("narration") or "").split()
    if not words or dur <= 0:
        return None
    srt = OUT / "captions.srt"
    per = dur / max(1, len(words))                 # one word at a time, evenly spread
    with open(srt, "w", encoding="utf-8") as f:
        for i, word in enumerate(words):
            _write_srt(f, i + 1, i * per, min(dur, (i + 1) * per), word)
    log(f"captions (text-timed, word-by-word) -> {srt.name}")
    return srt


def make_captions(voice_path, script, dur):
    """Word-accurate captions via whisper if available; otherwise text-timed
    captions from the narration. Always returns an SRT (captions never vanish)."""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(voice_path), word_timestamps=True)
        srt = OUT / "captions.srt"
        idx = 1
        with open(srt, "w", encoding="utf-8") as f:
            for seg in segments:
                for w in (seg.words or []):          # one word per caption, real timing
                    txt = w.word.strip()
                    if txt:
                        _write_srt(f, idx, w.start, w.end, txt)
                        idx += 1
        if idx > 1:
            log(f"captions (whisper, word-by-word) -> {srt.name}")
            return srt
        log("whisper produced no captions -> text fallback")
    except Exception as e:  # noqa
        log(f"whisper unavailable ({e}) -> text fallback")
    return _text_captions(script, dur)


def _ts(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = int(t % 60); ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(f, idx, start, end, text):
    f.write(f"{idx}\n{_ts(start)} --> {_ts(end)}\n{text.upper()}\n\n")


# ---------- 4. music (optional, file-based) ----------
def pick_music(cfg):
    """Use a royalty-free track from assets/music/ if any exist. Honest: if the
    folder is empty we simply skip music — no fake/placeholder audio."""
    if not cfg["video"].get("music"):
        return None
    mdir = ROOT / "assets" / "music"
    if not mdir.exists():
        return None
    tracks = sorted([p for p in mdir.iterdir()
                     if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")])
    if not tracks:
        log("no tracks in assets/music/ -> rendering without music")
        return None
    # rotate by day so consecutive posts don't all share one track
    import datetime as _dt
    return tracks[_dt.date.today().toordinal() % len(tracks)]


# ---------- 5. assemble ----------
# Varied Ken Burns motion per scene (uses 'on' = output frame index, {F} = total
# frames). Rotating the move keeps a multi-scene montage from feeling static.
# Punchy Ken Burns — fast, deep moves that combine zoom + pan so every scene feels
# alive and in-motion ('on' = output frame index, {F} = total frames per segment).
_KENBURNS = [
    "z='min(1.001+0.0020*on,1.34)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",        # hard punch in
    "z='max(1.34-0.0020*on,1.04)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",         # snap pull out
    "z='min(1.10+0.0012*on,1.30)':x='(iw-iw/zoom)*on/{F}':y='ih/2-(ih/zoom/2)'",      # pan right + zoom
    "z='min(1.10+0.0012*on,1.30)':x='(iw-iw/zoom)*(1-on/{F})':y='ih/2-(ih/zoom/2)'",  # pan left + zoom
    "z='min(1.06+0.0016*on,1.32)':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{F}'",      # zoom + tilt down
    "z='min(1.06+0.0016*on,1.32)':x='(iw-iw/zoom)*on/{F}':y='(ih-ih/zoom)*(1-on/{F})'",  # diagonal push
]
# Cinematic colour grade: punchy contrast/saturation, soft vignette, crisp sharpening.
# Applied per scene so both the montage and the avatar background match.
_GRADE = ("eq=contrast=1.13:saturation=1.24:brightness=0.02:gamma=0.97,"
          "vignette=PI/5,unsharp=5:5:0.6:5:5:0.0")
# Energetic, varied transitions (slides/zoom/wipes) so cuts feel deliberate, not a soft
# crossfade mush. All are valid ffmpeg xfade types.
_TRANSITIONS = ["slideleft", "zoomin", "smoothup", "circleopen",
                "slideright", "wipeleft", "radial", "fadeblack"]


def build_clip(images, total_dur, size, fps, out_path):
    w, h = size["w"], size["h"]
    n = len(images)
    per = max(2.0, total_dur / n)
    xdur = 0.5 if n > 1 else 0.0           # snappy transition length between scenes
    seg_len = per + xdur                    # build a little long so overlaps net to ~total
    frames = max(1, int(seg_len * fps))
    seg_files = []
    for i, img in enumerate(images):
        seg = OUT / f"_seg_{w}x{h}_{i:02d}.mp4"
        kb = _KENBURNS[i % len(_KENBURNS)].replace("{F}", str(frames))
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
              f"zoompan={kb}:d={frames}:s={w}x{h}:fps={fps},{_GRADE},format=yuv420p")
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(fps), "-i", str(img),
             "-t", f"{seg_len:.3f}", "-vf", vf, "-r", str(fps), "-pix_fmt", "yuv420p",
             str(seg)])
        seg_files.append(seg)

    if n == 1:
        run(["ffmpeg", "-y", "-i", seg_files[0].name, "-t", f"{total_dur:.3f}",
             "-c", "copy", str(out_path.name)], cwd=OUT)
        return out_path

    # Smooth crossfade transitions via a chained xfade graph (offset_k = k*per).
    try:
        inputs = []
        for s in seg_files:
            inputs += ["-i", s.name]
        fc, prev = [], "0:v"
        for k in range(1, n):
            lbl = f"x{k}" if k < n - 1 else "vout"
            tr = _TRANSITIONS[(k - 1) % len(_TRANSITIONS)]
            fc.append(f"[{prev}][{k}:v]xfade=transition={tr}:duration={xdur}:"
                      f"offset={k * per:.3f}[{lbl}]")
            prev = lbl
        run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[vout]",
             "-r", str(fps), "-pix_fmt", "yuv420p", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "23", str(out_path.name)], cwd=OUT)
        return out_path
    except Exception as e:  # noqa  transitions must never break the render
        log(f"xfade transitions failed ({e}); falling back to plain concat")
        listf = OUT / f"_list_{w}x{h}.txt"
        listf.write_text("".join(f"file '{s.name}'\n" for s in seg_files), encoding="utf-8")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf.name,
             "-c", "copy", str(out_path.name)], cwd=OUT)
        return out_path


def _video_dims(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)])
    w, h = out.decode().strip().split("x")[:2]
    return int(w), int(h)


def build_seamless_loop(clip_path, fps):
    """Make the avatar motion CONTINUOUS: build a SHORT forward+reverse 'boomerang' of
    the base clip. Wav2Lip cycles these frames internally to cover the whole voiceover,
    so the motion repeats seamlessly (no hard jump back to frame 1) WITHOUT inflating
    the frame count Wav2Lip must face-detect — pre-looping to full length did that and
    blew the CPU timeout. Also downscales the face for faster, reliable inference.
    Returns the boomerang clip, or the original on error (render never breaks)."""
    try:
        src = OUT / "_av_src.mp4"        # normalize fps + width, drop base audio (we use the VO)
        run(["ffmpeg", "-y", "-i", str(clip_path), "-an", "-r", str(fps),
             "-vf", "scale=540:-2", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "20", "-pix_fmt", "yuv420p", src.name], cwd=OUT)
        rev = OUT / "_av_rev.mp4"
        run(["ffmpeg", "-y", "-i", src.name, "-vf", "reverse", "-an", "-r", str(fps),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", rev.name], cwd=OUT)
        bounce = OUT / "_av_bounce.mp4"   # forward then reverse = seamless at both ends
        run(["ffmpeg", "-y", "-i", src.name, "-i", rev.name, "-filter_complex",
             "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-an", "-r", str(fps),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", bounce.name], cwd=OUT)
        log(f"avatar seamless boomerang ({ffprobe_duration(bounce):.1f}s) -> {bounce.name}")
        return bounce
    except Exception as e:  # noqa  looping must never break the render
        log(f"seamless loop failed, using raw clip: {e}")
        return clip_path


def mask_clip_watermark(clip_path, cfg):
    """Overlay the brand logo over the corner where the source clip's tool watermark
    (e.g. Kling) sits, hiding it. Runs on the raw motion clip BEFORE Wav2Lip, so the
    cover-up is part of the footage that gets lip-synced and composited. Returns a new
    clip path, or the original unchanged if no logo is configured/found. Never raises
    fatally — on any error the caller keeps the original clip."""
    av = cfg.get("avatar", {})
    logo_rel = av.get("watermark_logo")
    if not logo_rel:
        return clip_path
    logo = ROOT / logo_rel
    if not logo.exists():
        log(f"watermark mask: logo {logo} missing -> clip left unmasked")
        return clip_path
    cw, _ = _video_dims(clip_path)
    lw = max(8, int(cw * float(av.get("watermark_scale", 0.32))))
    margin = int(cw * float(av.get("watermark_margin", 0.0)))
    pos = str(av.get("watermark_pos", "bottom-right")).lower()
    x = f"W-w-{margin}" if "right" in pos else f"{margin}"
    y = f"H-h-{margin}" if "bottom" in pos else f"{margin}"
    out = OUT / "avatar_masked.mp4"
    if out.exists():
        out.unlink()
    # scale logo to lw wide (height auto, even for yuv420p); overlay flush in the corner
    fc = f"[1:v]scale={lw}:-2[logo];[0:v][logo]overlay={x}:{y}:shortest=1[v]"
    run(["ffmpeg", "-y", "-i", str(clip_path), "-i", str(logo),
         "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", out.name], cwd=OUT)
    log(f"watermark mask: {logo.name} over {pos} ({lw}px wide) -> {out.name}")
    return out


def _feather_mask(bw, bh, feather_frac):
    """Soft-edged alpha mask (rounded rectangle, gaussian-feathered) so the avatar
    blends INTO the scene instead of sitting inside a hard circle or box — the figure
    reads as part of the shot, not a pasted-on bubble."""
    from PIL import Image, ImageDraw, ImageFilter
    m = Image.new("L", (bw, bh), 0)
    short = min(bw, bh)
    inset = max(2, int(short * feather_frac))
    radius = int(short * 0.18)
    ImageDraw.Draw(m).rounded_rectangle(
        (inset, inset, bw - 1 - inset, bh - 1 - inset), radius=radius, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(inset * 0.9))
    mpath = OUT / "_avatar_mask.png"
    m.save(mpath)
    return mpath


def finalize(silent_video, voice_path, captions, music, size, out_path, cfg):
    # inputs: 0=silent video, 1=voiceover, (2=music if present)
    inputs = ["-i", silent_video.name, "-i", str(voice_path.name)]
    has_music = bool(music)
    if has_music:
        # loop the bed so short tracks still cover the whole video
        inputs = ["-i", silent_video.name, "-stream_loop", "-1", "-i", str(music),
                  "-i", str(voice_path.name)]
        voice_idx, music_idx = "2:a", "1:a"
    else:
        voice_idx = "1:a"

    filters = []
    # --- video: subtitles burn-in (run from OUT so no drive-colon path issues) ---
    vlabel = "0:v"
    if captions and cfg["video"].get("captions"):
        mv = cfg["video"].get("caption_margin_v", 70)   # margin from the bottom
        # Alignment=2 = bottom-center: captions sit at the bottom of the frame, below
        # the lower-right avatar figure (which is lifted via avatar.bubble_bottom).
        style = (f"FontName=DejaVu Sans,FontSize=18,Bold=1,PrimaryColour=&H00FFFFFF,"
                 f"OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,"
                 f"Alignment=2,MarginV={mv}")
        filters.append(f"[0:v]subtitles={captions.name}:force_style='{style}'[v]")
        vlabel = "v"

    # --- audio: duck music under voice, then mix ---
    if has_music:
        vol = cfg["video"].get("music_volume", 0.12)
        filters.append(f"[{music_idx}]volume={vol}[bg]")
        filters.append(
            f"[bg][{voice_idx}]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=300[duck]")
        filters.append(f"[{voice_idx}][duck]amix=inputs=2:duration=first:dropout_transition=2[a]")
        alabel = "a"
    else:
        alabel = voice_idx

    cmd = ["ffmpeg", "-y", *inputs]
    if filters:
        cmd += ["-filter_complex", ";".join(filters),
                "-map", f"[{vlabel}]" if vlabel == "v" else vlabel,
                "-map", f"[{alabel}]" if alabel == "a" else alabel]
    else:
        cmd += ["-map", "0:v", "-map", alabel]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "160k", "-shortest", str(out_path.name)]
    run(cmd, cwd=OUT)
    return out_path


def build_with_avatar_overlay(talking, images, total_dur, size, fps, out_path, cfg):
    """Full-duration ken-burns image background + a NON-circular, soft-feathered
    talking-avatar figure (head & shoulders) in the lower-right that lip-syncs the whole
    voiceover and gently bobs so it reads as a LIVE presenter blended into the scene —
    not a pasted-on circle. Captions are burned at the bottom in finalize, below the
    figure. So the avatar, the moving images, and the captions all coexist throughout."""
    w, h = size["w"], size["h"]
    avc = cfg.get("avatar", {})

    # 1) background: ken-burns image montage for the WHOLE duration
    bg = build_clip(images, total_dur, size, fps, OUT / f"_bg_{w}x{h}.mp4")

    # 2) figure box (portrait head-and-shoulders), sized by frame height
    bh = int(h * float(avc.get("bubble_frac", 0.52)))
    bh -= bh % 2
    bw = int(bh * float(avc.get("bubble_aspect", 0.72)))
    bw -= bw % 2

    # 3) crop a portrait region from the talking head matching the box aspect (wider
    #    than a tight face close-up, so shoulders show and it looks inclusive, not boxed)
    tw, th = _video_dims(talking)
    fz = float(avc.get("face_zoom", 0.92))
    fcx, fcy = float(avc.get("face_cx", 0.5)), float(avc.get("face_cy", 0.42))
    cw = max(64, int(min(tw, th) * fz))
    ch = int(cw * bh / bw)
    if ch > th:
        ch, cw = th, int(th * bw / bh)
    cw, ch = min(cw, tw), min(ch, th)        # never crop beyond the source frame
    cx = max(0, min(int(tw * fcx) - cw // 2, tw - cw))
    cy = max(0, min(int(th * fcy) - ch // 2, th - ch))

    # 4) soft-feather alpha so the figure blends into the scene (no circle, no hard box)
    mask = _feather_mask(bw, bh, float(avc.get("feather", 0.10)))

    # 5) lower-right anchor, lifted off the bottom to leave room for bottom captions,
    #    with a subtle time-based bob so the figure feels alive and in-motion.
    margin = int(h * float(avc.get("bubble_margin", 0.04)))
    bottom = int(h * float(avc.get("bubble_bottom", 0.16)))
    ox, oy = w - bw - margin, h - bh - bottom
    bob = int(avc.get("bob_px", 9))
    bobx = int(avc.get("bob_x_px", 5))
    ox_expr = f"{ox}+{bobx}*sin(1.7*t)"
    oy_expr = f"{oy}+{bob}*sin(1.1*t)"

    fc = (
        f"[1:v]crop={cw}:{ch}:{cx}:{cy},scale={bw}:{bh},setsar=1,format=rgba[fig];"
        f"[2:v]scale={bw}:{bh},format=gray[m];"
        f"[fig][m]alphamerge[av];"
        f"[0:v][av]overlay=x='{ox_expr}':y='{oy_expr}':shortest=1,format=yuv420p[out]"
    )
    run(["ffmpeg", "-y",
         "-i", bg.name, "-i", str(talking), "-loop", "1", "-i", mask.name,
         "-filter_complex", fc, "-map", "[out]", "-an",
         "-r", str(fps), "-t", f"{total_dur:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", out_path.name], cwd=OUT)
    log(f"avatar figure {bw}x{bh}px lower-right (feathered, live bob) -> {out_path.name}")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script_json")
    args = ap.parse_args()
    cfg = load_config()
    script = read_json(args.script_json)

    voice, dur = make_voice(script, cfg)
    captions = make_captions(voice, script, dur) if cfg["video"].get("captions") else None
    music = pick_music(cfg)
    if music:
        log(f"music bed: {music.name}")

    fps = cfg["video"]["fps"]

    # Images are always fetched now — used as the full montage, or as b-roll after
    # the avatar intro, so BOTH the avatar and the visuals appear in the video.
    images = fetch_images(script, cfg)

    # ---- talking avatar over the FULL voiceover (Wav2Lip, in-runner) ----
    # The avatar bubble lip-syncs the whole video, so we feed the complete voice.
    talking = None
    av = cfg.get("avatar", {})
    if av.get("enabled"):
        # Prefer a MOVING base clip (real gestures/expressions/body motion) if present;
        # Wav2Lip lip-syncs onto it. Otherwise use the still image (lips-only motion).
        avatar_img = ROOT / av.get("image", "assets/avatar.png")
        motion = av.get("motion_video")
        motion_path = (ROOT / motion) if motion else None
        if motion_path and motion_path.exists():
            face_src = motion_path
            log(f"avatar: using motion clip {face_src.name} (gestures + lip-sync)")
            # cover the source clip's tool watermark with the brand logo before lip-sync
            try:
                face_src = mask_clip_watermark(face_src, cfg)
            except Exception as e:  # noqa  masking must never break the render
                log(f"watermark mask failed (using unmasked clip): {e}")
            # boomerang-loop the short clip so the motion flows continuously (no reset)
            if av.get("seamless_loop", True):
                face_src = build_seamless_loop(face_src, fps)
        else:
            face_src = avatar_img
        if face_src.exists():
            try:
                from avatar_lipsync import generate_talking_head
                talking = generate_talking_head(face_src, voice, cfg)
            except Exception as e:  # noqa
                log(f"avatar generation errored, using motion graphics: {e}")
        else:
            log(f"avatar enabled but {face_src} missing -> motion graphics")

    def silent_for(size, tag):
        out = OUT / f"silent_{tag}.mp4"
        if talking is not None:
            try:
                return build_with_avatar_overlay(talking, images, dur, size, fps, out, cfg)
            except Exception as e:  # noqa  avatar must never break the render
                log(f"avatar overlay failed -> image montage: {e}")
        return build_clip(images, dur, size, fps, out)

    results = {}
    vsize = cfg["video"]["vertical"]
    vout = finalize(silent_for(vsize, "9x16"), voice, captions, music, vsize,
                    OUT / "video_9x16.mp4", cfg)
    results["vertical"] = str(vout)

    if cfg["video"].get("make_horizontal"):
        hsize = cfg["video"]["horizontal"]
        hout = finalize(silent_for(hsize, "16x9"), voice, captions, music, hsize,
                        OUT / "video_16x9.mp4", cfg)
        results["horizontal"] = str(hout)

    out = {
        "post": script["post"],
        "platform": script["platform"],
        "duration": dur,
        "videos": results,
        "avatar": talking is not None,
    }
    log(f"rendered: {list(results.keys())} (avatar={talking is not None})")
    write_json("render.json", out)


if __name__ == "__main__":
    main()
