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
def build_clip(images, total_dur, size, fps, out_path):
    w, h = size["w"], size["h"]
    per = max(2.0, total_dur / len(images))
    frames = int(per * fps)
    seg_files = []
    for i, img in enumerate(images):
        seg = OUT / f"_seg_{w}x{h}_{i:02d}.mp4"
        # cover-scale to target size (light, no 4K upscale) then slow ken-burns zoom
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},setsar=1,"
              f"zoompan=z='min(zoom+0.0010,1.15)':d={frames}:s={w}x{h}:fps={fps},"
              f"format=yuv420p")
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(fps), "-i", str(img),
             "-t", f"{per:.3f}", "-vf", vf, "-r", str(fps), "-pix_fmt", "yuv420p",
             str(seg)])
        seg_files.append(seg)
    # concat
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


def _circle_assets(diameter, ring_color):
    """A circular alpha mask + a thin ring, for the corner avatar bubble."""
    from PIL import Image, ImageDraw
    d = diameter
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
    mpath = OUT / "_circle_mask.png"
    mask.save(mpath)
    ring = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    bw = max(4, d // 40)
    ImageDraw.Draw(ring).ellipse((bw // 2, bw // 2, d - 1 - bw // 2, d - 1 - bw // 2),
                                 outline=tuple(ring_color), width=bw)
    rpath = OUT / "_circle_ring.png"
    ring.save(rpath)
    return mpath, rpath


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
        mv = cfg["video"].get("caption_margin_v", 90)   # margin from the top
        # Alignment=8 = top-center: always on-screen and clear of the bottom-right bubble.
        style = (f"FontName=DejaVu Sans,FontSize=16,Bold=1,PrimaryColour=&H00FFFFFF,"
                 f"OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,"
                 f"Alignment=8,MarginV={mv}")
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
    """Full-duration ken-burns image background + a circular talking-avatar bubble in
    the bottom-right that lip-syncs the whole voiceover. Captions are added in finalize.
    So the avatar, the moving images, and (later) the captions all coexist throughout."""
    w, h = size["w"], size["h"]
    avc = cfg.get("avatar", {})

    # 1) background: ken-burns image montage for the WHOLE duration
    bg = build_clip(images, total_dur, size, fps, OUT / f"_bg_{w}x{h}.mp4")

    # 2) face close-up crop (the source frame is wider than the face) from real dims
    tw, th = _video_dims(talking)
    fz = float(avc.get("face_zoom", 0.62))
    fcx, fcy = float(avc.get("face_cx", 0.5)), float(avc.get("face_cy", 0.40))
    side = max(64, int(min(tw, th) * fz))
    cx = max(0, min(int(tw * fcx) - side // 2, tw - side))
    cy = max(0, min(int(th * fcy) - side // 2, th - side))

    # 3) circle bubble size (fraction of height) + bottom-right position
    d = int(h * float(avc.get("bubble_frac", 0.20)))
    d -= d % 2
    margin = int(h * float(avc.get("bubble_margin", 0.03)))
    ox, oy = w - d - margin, h - d - margin
    mask, ring = _circle_assets(d, avc.get("ring_color", [255, 255, 255, 235]))

    fc = (
        f"[1:v]crop={side}:{side}:{cx}:{cy},scale={d}:{d},setsar=1,format=rgba[face];"
        f"[2:v]scale={d}:{d},format=gray[m];"
        f"[face][m]alphamerge[circ];"
        f"[0:v][circ]overlay={ox}:{oy}:shortest=1[t];"
        f"[t][3:v]overlay={ox}:{oy},format=yuv420p[out]"
    )
    run(["ffmpeg", "-y",
         "-i", bg.name, "-i", str(talking),
         "-loop", "1", "-i", mask.name, "-loop", "1", "-i", ring.name,
         "-filter_complex", fc, "-map", "[out]", "-an",
         "-r", str(fps), "-t", f"{total_dur:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", out_path.name], cwd=OUT)
    log(f"avatar bubble {d}px bottom-right over full montage -> {out_path.name}")
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
        avatar_img = ROOT / av.get("image", "assets/avatar.png")
        if avatar_img.exists():
            try:
                from avatar_lipsync import generate_talking_head
                talking = generate_talking_head(avatar_img, voice, cfg)
            except Exception as e:  # noqa
                log(f"avatar generation errored, using motion graphics: {e}")
        else:
            log(f"avatar enabled but {avatar_img} missing -> motion graphics")

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
