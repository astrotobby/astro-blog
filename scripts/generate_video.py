"""Stage 3: render video(s) from script.json — all free, no paid API.

  edge-tts        -> voiceover.mp3   (free Microsoft neural voices, no key)
  Pollinations    -> scene_*.jpg     (free AI images, no key)
  faster-whisper  -> captions.srt    (local, optional)
  ffmpeg          -> video_9x16.mp4 [+ video_16x9.mp4]

CINEMATIC VISUAL LOGIC (redesigned):
  - Scene 0 uses the post's own hero image (Pexels) for brand continuity
  - Each scene has a semantic TYPE (HOOK/ESTABLISH/EXPLAIN/TENSION/DATA/PAYOFF/CTA)
    embedded in its prompt by build_script.py
  - Ken Burns motion is driven by scene TYPE, not scene index
  - Per-scene duration is weighted by scene type energy level
  - Topic-aware colour grading (security/healthcare/finance/general_ai etc.)
  - DATA scenes get a lower-third stat bar overlay

Usage: python scripts/generate_video.py .pipeline/script.json
"""
import argparse
import asyncio
import re
import subprocess
import time
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


def make_voice(narration, cfg, tag=""):
    """Synthesize one voiceover for the given narration text. `tag` keeps the per-cut
    files distinct (e.g. "" for the vertical/follow cut, "_yt" for the horizontal/
    subscribe cut), so both narrations can coexist in one render."""
    v = cfg["voice"]
    # Cloned voice (free OpenVoice) when enabled; edge-tts is the automatic fallback
    # so the render never breaks if cloning is unavailable.
    if v.get("clone"):
        try:
            from voice_clone import synthesize
            cw = OUT / f"voiceover_clone{tag}.wav"
            if cw.exists():
                cw.unlink()
            if synthesize(narration, str(cw), cfg):
                dur = ffprobe_duration(cw)
                log(f"voiceover (CLONED) {dur:.1f}s -> {cw.name}")
                return cw, dur
            log("voice clone unavailable -> edge-tts")
        except Exception as e:  # noqa
            log(f"voice clone errored ({e}) -> edge-tts")
    out = OUT / f"voiceover{tag}.mp3"
    if out.exists():
        out.unlink()
    try:
        asyncio.run(_tts(narration, v["name"], v["rate"], v["pitch"], out))
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("edge-tts produced no audio")
    except Exception as e:  # noqa
        log(f"edge-tts failed ({e}); falling back to gTTS")
        _gtts_fallback(narration, out)
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


def _is_image_bytes(b):
    """True if the bytes look like a real JPEG/PNG/WEBP (catches HTML error pages)."""
    return bool(b) and len(b) > 2048 and (
        b[:2] == b"\xff\xd8" or b[:8] == b"\x89PNG\r\n\x1a\n" or b[8:12] == b"WEBP")


def _pollinations_image(prompt, w, h, seed):
    """Free AI text-to-image (no key) — generates an image FROM the scene prompt, so it
    matches the article topic. https://image.pollinations.ai/prompt/<prompt>"""
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
           + f"?width={w}&height={h}&nologo=true&model=flux&seed={seed}")
    for _ in range(3):
        try:
            r = requests.get(url, timeout=120)
            if r.status_code == 200 and _is_image_bytes(r.content):
                return r.content
            if r.status_code in (429, 500, 502, 503):   # busy/throttled -> wait & retry
                time.sleep(14)
                continue
            break
        except Exception:  # noqa
            break
    return None


def _openverse_image(query, w, h):
    """Free topical photo search (Openverse) — real photos that match the article's
    keywords. Uses API key from OPENVERSE_TOKEN env var if available (recommended;
    unauthenticated requests are rate-limited to 5/day). Picks the first usable result."""
    try:
        headers = {"User-Agent": "astro-blog-video/1.0"}
        api_key = env("OPENVERSE_TOKEN") or None
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        r = requests.get("https://api.openverse.org/v1/images/",
                         params={"q": query, "page_size": 8, "mature": "false"},
                         headers=headers, timeout=30)
        if r.status_code not in (200, 301, 302):
            return None
        data = r.json()
        results = data.get("results", []) if isinstance(data, dict) else []
        for item in results:
            u = item.get("url") or item.get("thumbnail")
            if not u:
                continue
            try:
                ir = requests.get(u, headers={"User-Agent": "astro-blog-video/1.0"}, timeout=30)
                if ir.status_code == 200 and _is_image_bytes(ir.content):
                    return ir.content
            except Exception:  # noqa
                continue
    except Exception:  # noqa
        pass
    return None


def _picsum_image(seed, w, h):
    """Reliable real photo (no key, no payment) — last resort before a gradient. NOT
    topical, so it sits below the topical sources in the tier list."""
    try:
        r = requests.get(f"https://picsum.photos/seed/{seed}/{w}/{h}", timeout=60)
        if r.status_code == 200 and len(r.content) > 2048:
            return r.content
    except Exception:  # noqa
        pass
    return None


def _fetch_hero_image(image_url, w, h):
    """Fetch the post's own hero image (from frontmatter) and resize/crop it to the
    target dimensions. Returns image bytes or None. This is used for scene 0 to anchor
    the video to the blog post's visual identity."""
    if not image_url:
        return None
    try:
        # Rewrite Pexels URLs to request the exact dimensions we need
        url = image_url
        if "pexels.com" in url:
            # Pexels supports fit=crop&w=W&h=H for exact crops
            url = re.sub(r"[?&](w|h|fit|auto|cs)=[^&]*", "", url)
            url = url.rstrip("?&")
            url += f"?auto=compress&cs=tinysrgb&fit=crop&w={w}&h={h}"
        r = requests.get(url, timeout=60, headers={"User-Agent": "astro-blog-video/1.0"})
        if r.status_code == 200 and _is_image_bytes(r.content):
            log(f"hero image fetched from {url[:60]}...")
            return r.content
    except Exception as e:  # noqa
        log(f"hero image fetch failed ({e})")
    return None


# ---------- Scene metadata parsing ----------

def _parse_scene_meta(prompt: str) -> dict:
    """Extract scene_type, kb_preset, and dur_mult from the embedded metadata tag
    appended by build_script.py. Returns defaults if the tag is absent (backward compat)."""
    meta = {"scene_type": "EXPLAIN", "kb_preset": "pan_right", "dur_mult": 1.0}
    m = re.search(r"scene_type:(\w+)\|kb:(\w+)\|dur:([\d.]+)", prompt)
    if m:
        meta["scene_type"] = m.group(1)
        meta["kb_preset"] = m.group(2)
        try:
            meta["dur_mult"] = float(m.group(3))
        except ValueError:
            pass
    return meta


def _clean_prompt(prompt: str) -> str:
    """Strip the metadata tag from the prompt before sending to the image API."""
    return re.sub(r",?\s*scene_type:\w+\|kb:\w+\|dur:[\d.]+", "", prompt).strip()


# ---------- Ken Burns presets (semantic, not index-based) ----------
# Each preset is a zoompan expression for ffmpeg.
# {F} is replaced with the total frame count for that segment.
_KENBURNS_PRESETS = {
    # HOOK: hard fast punch-in — maximum energy, scroll-stopping
    "punch_in":   "z='min(1.001+0.0035*on,1.45)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    # ESTABLISH: slow pull-out — reveals the world, sets context
    "pull_out":   "z='max(1.40-0.0018*on,1.05)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    # EXPLAIN: steady pan right — clarity, forward motion
    "pan_right":  "z='min(1.08+0.0010*on,1.22)':x='(iw-iw/zoom)*on/{F}':y='ih/2-(ih/zoom/2)'",
    # TENSION: fast diagonal push — pattern interrupt, visceral energy
    "diagonal":   "z='min(1.06+0.0022*on,1.35)':x='(iw-iw/zoom)*on/{F}':y='(ih-ih/zoom)*(1-on/{F})'",
    # DATA: near-static with very subtle zoom — let the stat breathe
    "static":     "z='min(1.02+0.0004*on,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    # PAYOFF: slow pull-back — resolution, breathing room
    "pull_back":  "z='max(1.30-0.0012*on,1.04)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    # CTA: gentle zoom in — inviting, warm
    "gentle_zoom":"z='min(1.04+0.0008*on,1.18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    # Legacy fallbacks (keep for backward compat with any cached prompts)
    "pan_left":   "z='min(1.10+0.0012*on,1.30)':x='(iw-iw/zoom)*(1-on/{F})':y='ih/2-(ih/zoom/2)'",
    "tilt_down":  "z='min(1.06+0.0016*on,1.32)':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{F}'",
}

# Fallback list for any unrecognised preset key
_KENBURNS_FALLBACK = list(_KENBURNS_PRESETS.values())

# ---------- Topic-aware colour grades ----------
# Imported from build_script.py's TOPIC_VISUAL_PROFILES at runtime.
# Default (teal-orange tech-documentary) used when topic is undetected.
_GRADE_DEFAULT = (
    "eq=contrast=1.13:saturation=1.24:brightness=0.02:gamma=0.97,"
    "colorbalance=rs=-0.04:bs=0.05:rh=0.05:bh=-0.06,"
    "vignette=PI/5,unsharp=5:5:0.6:5:5:0.0,"
    "noise=alls=5:allf=t"
)

_GRADE_BY_CATEGORY = {
    "security": (
        "eq=contrast=1.18:saturation=1.10:brightness=-0.02:gamma=0.95,"
        "colorbalance=rs=0.06:bs=-0.04:rh=0.04:bh=-0.05,"
        "vignette=PI/4,unsharp=5:5:0.7:5:5:0.0,noise=alls=4:allf=t"
    ),
    "healthcare": (
        "eq=contrast=1.10:saturation=0.95:brightness=0.03:gamma=1.02,"
        "colorbalance=rs=-0.05:bs=0.07:rh=-0.03:bh=0.04,"
        "vignette=PI/6,unsharp=5:5:0.5:5:5:0.0,noise=alls=3:allf=t"
    ),
    "finance": (
        "eq=contrast=1.15:saturation=1.20:brightness=0.01:gamma=0.98,"
        "colorbalance=rs=0.05:bs=-0.06:rh=0.07:bh=-0.04,"
        "vignette=PI/5,unsharp=5:5:0.6:5:5:0.0,noise=alls=4:allf=t"
    ),
    "automation": (
        "eq=contrast=1.12:saturation=1.18:brightness=0.02:gamma=0.97,"
        "colorbalance=rs=-0.03:bs=0.04:rh=0.04:bh=-0.05,"
        "vignette=PI/5,unsharp=5:5:0.6:5:5:0.0,noise=alls=5:allf=t"
    ),
    "llm_model": _GRADE_DEFAULT,
    "general_ai": _GRADE_DEFAULT,
}

# Cinematic transitions — varied so cuts feel deliberate
_TRANSITIONS = ["slideleft", "zoomin", "smoothup", "circleopen",
                "slideright", "wipeleft", "radial", "fadeblack"]


def _detect_topic_from_script(script) -> str:
    """Detect topic category from the script post data. Mirrors build_script.detect_topic_category
    but works on the already-rendered script.json (avoids re-importing build_script)."""
    from build_script import TOPIC_VISUAL_PROFILES, detect_topic_category
    return detect_topic_category(script["post"])


def _get_grade(script) -> str:
    """Return the colour grade filter string for this post's topic category."""
    try:
        cat = _detect_topic_from_script(script)
        return _GRADE_BY_CATEGORY.get(cat, _GRADE_DEFAULT)
    except Exception:  # noqa — never break the render over a grade lookup
        return _GRADE_DEFAULT


def _fetch_scene(i, prompt, w, h, token, slug, title, base_seed, image_url=None):
    """One scene through the tiered source chain.

    Scene 0 gets special treatment: we try the post's own hero image first (Pexels),
    which creates visual continuity between the blog post and the video. If the hero
    image fetch fails, we fall through to the normal AI-generation chain.

    All other scenes use the cinematic prompt built by build_script.make_scenes(),
    which encodes topic-specific visual language + scene type modifiers.
    """
    dst = OUT / f"scene_{i:02d}.jpg"

    # Parse scene metadata from the prompt
    meta = _parse_scene_meta(prompt)
    clean = _clean_prompt(prompt)
    scene_type = meta["scene_type"]

    # Scene 0: try the post's hero image first for brand continuity
    if i == 0 and image_url:
        content = _fetch_hero_image(image_url, w, h)
        if content:
            dst.write_bytes(content)
            if _valid_image(dst):
                log(f"scene 0 [HOOK] -> {dst.name} (hero-image) [post's own Pexels photo]")
                return dst, meta

    # Topical keyword query for the photo-search fallback
    m = re.search(r"theme:\s*([^,]+)", clean)
    focus = m.group(1).strip() if m else ""
    query = (f"{title} {focus}".strip() or title or "technology news")

    content, src = _pollinations_image(clean, w, h, base_seed + i), "pollinations-AI"
    if not content:
        content, src = _hf_image(clean, token), "HF-AI"
    if not content:
        content, src = _openverse_image(query, w, h), "openverse"
    if not content:
        content, src = _picsum_image(f"{slug}-{i}", w, h), "picsum(random)"
    if content:
        dst.write_bytes(content)
    if not _valid_image(dst):
        _fallback_image(dst, w, h, i)
        src = "gradient"
    log(f"scene {i} [{scene_type}] -> {dst.name} ({src}) [q: {query[:48]}]")
    return dst, meta


def fetch_images(script, cfg):
    """Tiered, all-free image source — TOPICAL first so visuals match the article.

    Returns a list of (image_path, scene_meta) tuples so the renderer can apply
    the correct Ken Burns motion and duration weighting per scene.

    Source priority:
      0) Post hero image (scene 0 only) — blog's own Pexels photo
      1) Pollinations  -> free AI image generated from the cinematic scene prompt
      2) Hugging Face  -> AI image from the prompt (uses HF_TOKEN if set)
      3) Openverse     -> free keyword photo search (real photos matching the title)
      4) Lorem Picsum  -> reliable but RANDOM photo (only if all topical sources fail)
      5) gradient      -> last resort so ffmpeg always has valid input
    """
    vz = cfg["visuals"]
    w, h = vz["width"], vz["height"]
    token = env("HF_TOKEN") or None
    slug = script["post"]["slug"]
    title = (script["post"].get("title") or "").strip()
    image_url = script["post"].get("image_url") or ""
    base_seed = abs(hash(slug)) % 100000
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_fetch_scene, i, p, w, h, token, slug, title, base_seed,
                          image_url if i == 0 else None)
                for i, p in enumerate(script["scene_prompts"])]
        return [f.result() for f in futs]


# ---------- 3. captions ----------
def _text_captions(narration, dur, tag=""):
    """Build an SRT from the narration text spread across the audio duration — no
    whisper needed, so on-screen captions ALWAYS appear (timing is approximate)."""
    words = (narration or "").split()
    if not words or dur <= 0:
        return None
    srt = OUT / f"captions{tag}.srt"
    per = dur / max(1, len(words))                 # one word at a time, evenly spread
    with open(srt, "w", encoding="utf-8") as f:
        for i, word in enumerate(words):
            _write_srt(f, i + 1, i * per, min(dur, (i + 1) * per), word)
    log(f"captions (text-timed, word-by-word) -> {srt.name}")
    return srt


def make_captions(voice_path, narration, dur, tag=""):
    """Word-accurate captions via whisper if available; otherwise text-timed
    captions from the narration. Always returns an SRT (captions never vanish).
    `tag` keeps each cut's captions in a distinct file (vertical vs horizontal)."""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(voice_path), word_timestamps=True)
        srt = OUT / f"captions{tag}.srt"
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
    return _text_captions(narration, dur, tag)


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

def build_clip(image_results, total_dur, size, fps, out_path, grade=None):
    """Build the image montage with SEMANTIC Ken Burns motion and scene-type-weighted
    per-scene durations.

    `image_results` is a list of (image_path, scene_meta) tuples produced by
    fetch_images(). Each scene_meta contains:
      - scene_type: HOOK/ESTABLISH/EXPLAIN/TENSION/DATA/PAYOFF/CTA
      - kb_preset:  Ken Burns preset name (semantic, not index-based)
      - dur_mult:   duration multiplier relative to the base per-scene duration

    The total duration is preserved: individual scene durations are weighted by
    dur_mult and then normalised so they sum to total_dur.
    """
    # Unpack image results — support both old (path-only) and new (path, meta) formats
    images = []
    metas = []
    for item in image_results:
        if isinstance(item, tuple):
            images.append(item[0])
            metas.append(item[1])
        else:
            images.append(item)
            metas.append({"scene_type": "EXPLAIN", "kb_preset": "pan_right", "dur_mult": 1.0})

    n = len(images)
    w, h = size["w"], size["h"]
    _grade = grade or _GRADE_DEFAULT

    # Compute per-scene durations weighted by dur_mult, normalised to total_dur
    raw_mults = [m.get("dur_mult", 1.0) for m in metas]
    total_mult = sum(raw_mults)
    base_per = max(1.5, total_dur / n)
    # Weighted durations, then normalise so sum == total_dur
    raw_durs = [base_per * mult for mult in raw_mults]
    scale = total_dur / sum(raw_durs)
    scene_durs = [max(1.2, d * scale) for d in raw_durs]

    xdur = 0.5 if n > 1 else 0.0
    seg_files = []
    for i, (img, meta, sdur) in enumerate(zip(images, metas, scene_durs)):
        seg = OUT / f"_seg_{w}x{h}_{i:02d}.mp4"
        seg_len = sdur + xdur
        frames = max(1, int(seg_len * fps))

        # Semantic Ken Burns: look up by preset name, fall back to index-based
        kb_key = meta.get("kb_preset", "pan_right")
        kb_expr = _KENBURNS_PRESETS.get(kb_key, _KENBURNS_FALLBACK[i % len(_KENBURNS_FALLBACK)])
        kb = kb_expr.replace("{F}", str(frames))

        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
              f"zoompan={kb}:d={frames}:s={w}x{h}:fps={fps},{_grade},format=yuv420p")
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(fps), "-i", str(img),
             "-t", f"{seg_len:.3f}", "-vf", vf, "-r", str(fps), "-pix_fmt", "yuv420p",
             str(seg)])
        seg_files.append((seg, sdur))
        log(f"  segment {i} [{meta.get('scene_type','?')}] kb={kb_key} dur={sdur:.2f}s")

    if n == 1:
        run(["ffmpeg", "-y", "-i", seg_files[0][0].name, "-t", f"{total_dur:.3f}",
             "-c", "copy", str(out_path.name)], cwd=OUT)
        return out_path

    # Smooth crossfade transitions via a chained xfade graph
    try:
        inputs = []
        for s, _ in seg_files:
            inputs += ["-i", s.name]
        fc, prev = [], "0:v"
        offset = 0.0
        for k in range(1, n):
            lbl = f"x{k}" if k < n - 1 else "vout"
            tr = _TRANSITIONS[(k - 1) % len(_TRANSITIONS)]
            offset += scene_durs[k - 1]
            fc.append(f"[{prev}][{k}:v]xfade=transition={tr}:duration={xdur}:"
                      f"offset={offset:.3f}[{lbl}]")
            prev = lbl
        run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[vout]",
             "-r", str(fps), "-pix_fmt", "yuv420p", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "23", str(out_path.name)], cwd=OUT)
        return out_path
    except Exception as e:  # noqa  transitions must never break the render
        log(f"xfade transitions failed ({e}); falling back to plain concat")
        listf = OUT / f"_list_{w}x{h}.txt"
        listf.write_text("".join(f"file '{s.name}'\n" for s, _ in seg_files), encoding="utf-8")
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


def _font_file():
    """Bold system font for the drawtext cards (Linux paths only — a Windows path
    contains a drive-letter colon, which ffmpeg's filter parser treats as an option
    separator). Returns None if not found: cards are then skipped rather than
    breaking the render. CI renders on ubuntu-latest, which ships DejaVu."""
    import os
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if os.path.exists(p):
            return p
    return None


def _wrap(text, max_chars):
    """Greedy word-wrap for drawtext (which does not wrap on its own)."""
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines[:4])


def _extract_stat(text: str) -> str:
    """Extract the first meaningful number/stat from a text string for the DATA
    lower-third overlay. Returns empty string if nothing found."""
    m = re.search(r"(\d[\d,.]*\s*(?:%|percent|million|billion|trillion|x faster|x cheaper|\$[\d,.]+))",
                  text, re.I)
    if m:
        return m.group(1).strip()
    # Fallback: any standalone number with context
    m = re.search(r"(\d[\d,.]+(?:\s+\w+){0,3})", text)
    return m.group(1).strip() if m else ""


def _overlay_cards(cfg, size, hook_text, total_dur, tag, scene_metas=None, narration_segments=None):
    """drawtext filter snippets for cinematic overlays:

    (a) HOOK TITLE CARD: bold title over the first ~2.8s — the scroll-stopper
    (b) DATA LOWER-THIRDS: a subtle stat bar shown during DATA-type scenes
    (c) END CARD: dimmed CTA card over the last ~3.4s

    Pure ffmpeg, zero cost. Returns [] if disabled or no usable font.
    """
    font = _font_file()
    if not font:
        return []
    vc = cfg["video"]
    w = size["w"]
    chain = []

    # (a) Hook title card
    if vc.get("hook_card") and hook_text:
        hk = OUT / f"_hook_{tag}.txt"
        hk.write_text(_wrap(hook_text.upper(), 20 if w < 1500 else 34),
                      encoding="utf-8", newline="\n")
        fs = int(w / 13) if w < 1500 else int(w / 22)
        chain.append(
            f"drawtext=textfile={hk.name}:fontfile={font}:fontsize={fs}:"
            f"fontcolor=white:borderw=3:bordercolor=black:box=1:"
            f"boxcolor=black@0.45:boxborderw=28:line_spacing=14:"
            f"x=(w-text_w)/2:y=h*0.14:"
            f"alpha='if(lt(t,2.3),1,max(0,(2.8-t)/0.5))':enable='lt(t,2.8)'")

    # (b) DATA lower-thirds: show the stat being spoken during DATA scenes
    if scene_metas and narration_segments and vc.get("data_lower_third", True):
        # Compute scene start times from scene durations
        # (approximate: use uniform distribution if dur_mult not available)
        n = len(scene_metas)
        if total_dur and n > 0:
            raw_mults = [m.get("dur_mult", 1.0) for m in scene_metas]
            total_mult = sum(raw_mults)
            scene_start = 0.0
            for idx, (meta, seg_text) in enumerate(zip(scene_metas, narration_segments)):
                sdur = total_dur * (raw_mults[idx] / total_mult)
                if meta.get("scene_type") == "DATA":
                    stat = _extract_stat(seg_text)
                    if stat and len(stat) < 40:
                        lf = OUT / f"_stat_{tag}_{idx}.txt"
                        lf.write_text(stat.upper(), encoding="utf-8", newline="\n")
                        fs_stat = int(w / 18) if w < 1500 else int(w / 30)
                        t_start = max(0.0, scene_start + 0.3)
                        t_end = scene_start + sdur - 0.3
                        en = f"enable='between(t,{t_start:.2f},{t_end:.2f})'"
                        # Subtle lower-third bar: dark background + white stat text
                        chain.append(
                            f"drawbox=x=0:y=h*0.82:w=w:h=h*0.10:"
                            f"color=black@0.60:t=fill:{en}")
                        chain.append(
                            f"drawtext=textfile={lf.name}:fontfile={font}:fontsize={fs_stat}:"
                            f"fontcolor=white:borderw=2:bordercolor=black:"
                            f"x=(w-text_w)/2:y=h*0.845:{en}")
                scene_start += sdur

    # (c) End card
    lines = vc.get("end_card_lines") or []
    if vc.get("end_card") and lines and total_dur and total_dur > 12:
        start = max(0.0, total_dur - 3.4)
        en = f"enable='gte(t,{start:.2f})'"
        chain.append(f"drawbox=color=black@0.55:t=fill:{en}")
        # (y-fraction, width-divisor, colour) per line: headline, domain, offer
        layout = [(0.38, 17, "white"), (0.47, 12, "white"), (0.57, 22, "0xFFD166")]
        for i, line in enumerate(lines[:3]):
            lf = OUT / f"_end_{tag}_{i}.txt"
            lf.write_text(str(line), encoding="utf-8", newline="\n")
            frac, div, col = layout[i]
            fs = int(w / div) if w < 1500 else int(w / (div * 1.7))
            chain.append(
                f"drawtext=textfile={lf.name}:fontfile={font}:fontsize={fs}:"
                f"fontcolor={col}:borderw=2:bordercolor=black:"
                f"x=(w-text_w)/2:y=h*{frac}:{en}")
    return chain


def finalize(silent_video, voice_path, captions, music, size, out_path, cfg,
             hook_text=None, total_dur=None, scene_metas=None, narration_segments=None):
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
    # --- video: subtitles burn-in + hook/end cards, chained on one video path ---
    vchain = []
    if captions and cfg["video"].get("captions"):
        mv = cfg["video"].get("caption_margin_v", 70)   # margin from the bottom
        style = (f"FontName=DejaVu Sans,FontSize=20,Bold=1,PrimaryColour=&H00FFFFFF,"
                 f"OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,"
                 f"Alignment=2,MarginV={mv}")
        vchain.append(f"subtitles={captions.name}:force_style='{style}'")
    vchain += _overlay_cards(cfg, size, hook_text, total_dur, out_path.stem,
                             scene_metas=scene_metas, narration_segments=narration_segments)
    vlabel = "0:v"
    if vchain:
        filters.append(f"[0:v]{','.join(vchain)}[v]")
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
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "26",
            "-c:a", "aac", "-b:a", "128k", "-shortest",
            "-movflags", "+faststart", str(out_path.name)]
    run(cmd, cwd=OUT)
    return out_path


def build_with_avatar_overlay(talking, image_results, total_dur, size, fps, out_path, cfg, grade=None):
    """Full-duration ken-burns image background + a NON-circular, soft-feathered
    talking-avatar figure (head & shoulders) in the lower-right that lip-syncs the whole
    voiceover and gently bobs so it reads as a LIVE presenter blended into the scene —
    not a pasted-on circle. Captions are burned at the bottom in finalize, below the
    figure. So the avatar, the moving images, and the captions all coexist throughout."""
    w, h = size["w"], size["h"]
    avc = cfg.get("avatar", {})

    # 1) background: ken-burns image montage for the WHOLE duration
    bg = build_clip(image_results, total_dur, size, fps, OUT / f"_bg_{w}x{h}.mp4", grade=grade)

    # 2) figure box (portrait head-and-shoulders), sized by frame height
    bh = int(h * float(avc.get("bubble_frac", 0.52)))
    bh -= bh % 2
    bw = int(bh * float(avc.get("bubble_aspect", 0.72)))
    bw -= bw % 2

    # 3) crop a portrait region from the talking head matching the box aspect
    tw, th = _video_dims(talking)
    fz = float(avc.get("face_zoom", 0.92))
    fcx, fcy = float(avc.get("face_cx", 0.5)), float(avc.get("face_cy", 0.42))
    cw = max(64, int(min(tw, th) * fz))
    ch = int(cw * bh / bw)
    if ch > th:
        ch, cw = th, int(th * bw / bh)
    cw, ch = min(cw, tw), min(ch, th)
    cx = max(0, min(int(tw * fcx) - cw // 2, tw - cw))
    cy = max(0, min(int(th * fcy) - ch // 2, th - ch))

    # 4) soft-feather alpha so the figure blends into the scene
    mask = _feather_mask(bw, bh, float(avc.get("feather", 0.10)))

    # 5) lower-right anchor with subtle sinusoidal bob
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


def make_story_cut(vertical_path, max_seconds=58):
    """Trim the finished vertical down to <=max_seconds for Instagram/Facebook Stories,
    whose publish APIs reject clips longer than ~60s. Re-encodes (fast) with +faststart
    so the hosted URL streams cleanly. A shorter video is simply re-wrapped at full length.
    TikTok has no Stories API, so this cut is for IG/FB only."""
    keep = min(max_seconds, ffprobe_duration(vertical_path))
    out = OUT / "video_story.mp4"
    run(["ffmpeg", "-y", "-i", vertical_path.name, "-t", f"{keep:.3f}",
         "-c:v", "libx264", "-preset", "fast", "-crf", "26",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out.name], cwd=OUT)
    log(f"story cut {keep:.1f}s -> {out.name}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script_json")
    args = ap.parse_args()
    cfg = load_config()
    script = read_json(args.script_json)

    captions_on = cfg["video"].get("captions")
    # Vertical cut (TikTok/IG/FB/X/Threads + Stories) speaks the "follow" CTA.
    narr_v = script["narration"]
    voice, dur = make_voice(narr_v, cfg, tag="")
    captions = make_captions(voice, narr_v, dur) if captions_on else None
    music = pick_music(cfg)
    if music:
        log(f"music bed: {music.name}")

    fps = cfg["video"]["fps"]

    # Detect topic-aware colour grade for this post
    grade = _get_grade(script)
    log(f"colour grade: {'topic-specific' if grade != _GRADE_DEFAULT else 'default'}")

    # Single-image mode: when visuals.single_image is set, the whole video is just that
    # one image (gentle Ken Burns) + captions + voiceover — no AI scene montage at all.
    single = (cfg.get("visuals", {}) or {}).get("single_image")
    single_path = (ROOT / single) if single else None
    if single_path and single_path.exists():
        # Wrap in the (path, meta) tuple format expected by build_clip
        image_results = [(single_path, {"scene_type": "ESTABLISH", "kb_preset": "pull_out", "dur_mult": 1.0})]
        log(f"single-image mode: {single_path.name} only (no scene montage)")
    else:
        # Fetch the cinematic scene montage with hero image + semantic scene types
        image_results = fetch_images(script, cfg)

    # Extract scene metas and narration segments for DATA lower-thirds overlay
    scene_metas = [m for _, m in image_results] if image_results and isinstance(image_results[0], tuple) else []
    # Segment the narration to match scenes (for DATA lower-third stat extraction)
    from build_script import _segment_narration
    narration_segments = _segment_narration(narr_v, len(scene_metas)) if scene_metas else []

    # ---- talking avatar over the FULL voiceover (Wav2Lip, in-runner) ----
    talking = None
    av = cfg.get("avatar", {})
    if av.get("enabled"):
        avatar_img = ROOT / av.get("image", "assets/avatar.png")
        motion = av.get("motion_video")
        motion_path = (ROOT / motion) if motion else None
        if motion_path and motion_path.exists():
            face_src = motion_path
            log(f"avatar: using motion clip {face_src.name} (gestures + lip-sync)")
            try:
                face_src = mask_clip_watermark(face_src, cfg)
            except Exception as e:  # noqa
                log(f"watermark mask failed (using unmasked clip): {e}")
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

    def silent_for(size, tag, seg_dur):
        out = OUT / f"silent_{tag}.mp4"
        if talking is not None:
            try:
                return build_with_avatar_overlay(talking, image_results, seg_dur, size, fps, out, cfg, grade=grade)
            except Exception as e:  # noqa  avatar must never break the render
                log(f"avatar overlay failed -> image montage: {e}")
        return build_clip(image_results, seg_dur, size, fps, out, grade=grade)

    results = {}
    hook = script.get("hook") or ""
    vsize = cfg["video"]["vertical"]
    vout = finalize(
        silent_for(vsize, "9x16", dur), voice, captions, music, vsize,
        OUT / "video_9x16.mp4", cfg,
        hook_text=hook, total_dur=dur,
        scene_metas=scene_metas, narration_segments=narration_segments
    )
    results["vertical"] = str(vout)

    # Story cut: a <=58s trim of the vertical for IG/FB Stories
    if cfg.get("platforms", {}).get("also_story", True):
        try:
            results["story"] = str(make_story_cut(vout))
        except Exception as e:  # noqa
            log(f"story cut failed (no story video this run): {e}")

    if cfg["video"].get("make_horizontal"):
        hsize = cfg["video"]["horizontal"]
        narr_h = script.get("narration_yt") or narr_v
        voice_h, dur_h = make_voice(narr_h, cfg, tag="_yt")
        captions_h = make_captions(voice_h, narr_h, dur_h, tag="_yt") if captions_on else None
        narration_segments_h = _segment_narration(narr_h, len(scene_metas)) if scene_metas else []
        hout = finalize(
            silent_for(hsize, "16x9", dur_h), voice_h, captions_h, music, hsize,
            OUT / "video_16x9.mp4", cfg,
            hook_text=hook, total_dur=dur_h,
            scene_metas=scene_metas, narration_segments=narration_segments_h
        )
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
