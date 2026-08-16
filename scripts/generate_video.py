"""Render footage-driven social and YouTube videos from a generated blog script.

Pipeline:
  edge-tts             -> voiceover.mp3 / voiceover_yt.mp3
  Pexels + Pixabay     -> semantically matched scene clips
  faster-whisper       -> word-level timestamps for bottom captions
  FFmpeg               -> finished vertical and horizontal masters

The renderer treats stock-video search as an editorial step.  Every scene carries a
primary concrete B-roll query and a category-safe fallback from build_script.py;
this avoids querying every scene with the article title and filling technical videos
with unrelated landscape footage.

Caption style:
  - Word-by-word display at the BOTTOM of the video (no box, no background bar).
  - Each word appears and disappears in sync with the voice using Whisper's
    word-level timestamps — never a full subtitle segment all at once.
  - No hook card, data lower-third, or end-card overlay dimming the video.
"""
import argparse
import asyncio
import datetime as dt
import hashlib
import json
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

import requests

from common import OUT, ROOT, STATE, env, load_config, log, read_json, write_json


FONT_FILE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MUSIC_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}
FOOTAGE_CACHE_FILE = STATE / "footage_search_cache.json"
FOOTAGE_CACHE_TTL_SECONDS = 24 * 60 * 60
FOOTAGE_HISTORY_FILE = STATE / "footage_history.json"
FOOTAGE_HISTORY_DAYS = 30
FOOTAGE_HISTORY_LIMIT = 240
_search_cache = None


def _load_search_cache():
    """Load a small, non-secret cache shared through the pipeline state directory."""
    global _search_cache
    if _search_cache is not None:
        return _search_cache
    try:
        raw = json.loads(FOOTAGE_CACHE_FILE.read_text(encoding="utf-8"))
        _search_cache = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        _search_cache = {}
    return _search_cache


def _cache_key(provider, query, target_w, target_h):
    raw = f"{provider.lower()}|{query.strip().lower()}|{target_w}x{target_h}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(provider, query, target_w, target_h):
    entry = _load_search_cache().get(_cache_key(provider, query, target_w, target_h))
    if not entry or not isinstance(entry.get("candidates"), list):
        return None
    if time.time() - float(entry.get("cached_at", 0)) > FOOTAGE_CACHE_TTL_SECONDS:
        return None
    return entry["candidates"]


def _cache_put(provider, query, target_w, target_h, candidates):
    cache = _load_search_cache()
    cache[_cache_key(provider, query, target_w, target_h)] = {
        "cached_at": time.time(),
        "candidates": candidates,
    }
    # Retain only recent records so state caching remains compact and reusable.
    cutoff = time.time() - FOOTAGE_CACHE_TTL_SECONDS
    recent = {key: value for key, value in cache.items()
              if isinstance(value, dict) and value.get("cached_at", 0) >= cutoff}
    _search_cache.clear()
    _search_cache.update(recent)
    try:
        FOOTAGE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        FOOTAGE_CACHE_FILE.write_text(json.dumps(_search_cache, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log(f"footage search cache write skipped: {exc}")


def _load_footage_history():
    """Load recent clip IDs used by prior posts; history is non-secret state."""
    try:
        raw = json.loads(FOOTAGE_HISTORY_FILE.read_text(encoding="utf-8"))
        items = raw.get("items", []) if isinstance(raw, dict) else []
    except (OSError, ValueError, json.JSONDecodeError):
        items = []
    cutoff = time.time() - FOOTAGE_HISTORY_DAYS * 24 * 60 * 60
    return [item for item in items
            if isinstance(item, dict) and item.get("id")
            and float(item.get("used_at", 0)) >= cutoff]


def _save_footage_history(items):
    """Persist a bounded recency list so the next post can avoid visual repeats."""
    deduped = []
    seen = set()
    for item in sorted(items, key=lambda value: float(value.get("used_at", 0)), reverse=True):
        clip_id = item.get("id")
        if not clip_id or clip_id in seen:
            continue
        seen.add(clip_id)
        deduped.append(item)
        if len(deduped) >= FOOTAGE_HISTORY_LIMIT:
            break
    try:
        FOOTAGE_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        FOOTAGE_HISTORY_FILE.write_text(
            json.dumps({"items": deduped}, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log(f"footage history write skipped: {exc}")


def run(cmd, **kw):
    log("$ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def ffprobe_duration(path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)]
        )
        return float(out.strip())
    except Exception:
        return 0.0


# ---------- 1. Voiceover ----------

async def _tts(text, voice, rate, pitch, out_path):
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await comm.save(str(out_path))


def _gtts_fallback(text, out_path):
    from gtts import gTTS

    gTTS(text).save(str(out_path))


def make_voice(narration, cfg, tag=""):
    voice_cfg = cfg["voice"]
    if voice_cfg.get("clone"):
        clone_out = OUT / f"voiceover{tag}.wav"
        clone_out.unlink(missing_ok=True)
        try:
            from voice_clone import synthesize
            result = synthesize(narration, str(clone_out), cfg)
            if result and clone_out.exists() and clone_out.stat().st_size > 1024:
                duration = ffprobe_duration(clone_out)
                if duration > 0.25:
                    log(f"authorized cloned voiceover {duration:.1f}s -> {clone_out.name}")
                    return clone_out, duration
            log("voice clone unavailable; falling back to configured TTS voice")
        except Exception as exc:  # noqa
            log(f"voice clone failed ({exc}); falling back to configured TTS voice")

    out = OUT / f"voiceover{tag}.mp3"
    out.unlink(missing_ok=True)
    try:
        asyncio.run(_tts(narration, voice_cfg["name"], voice_cfg["rate"],
                         voice_cfg["pitch"], out))
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("edge-tts produced no audio")
    except Exception as exc:
        log(f"edge-tts failed ({exc}); falling back to gTTS")
        _gtts_fallback(narration, out)
    duration = ffprobe_duration(out)
    log(f"voiceover {duration:.1f}s -> {out.name}")
    return out, duration


# ---------- 2. Footage sourcing ----------

def _is_video_valid(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 10000 and ffprobe_duration(path) > 0.25


def _aspect_score(width, height, target_w, target_h) -> float:
    if not width or not height:
        return 0.0
    target = target_w / target_h
    ratio = width / height
    ratio_error = abs(ratio - target) / max(target, 0.01)
    ratio_score = max(0.0, 1.0 - min(ratio_error, 1.0))
    # A high-resolution file will still crop well, while a tiny file will not.
    resolution_score = min(1.0, min(width / target_w, height / target_h))
    return ratio_score * 0.78 + resolution_score * 0.22


def _best_pexels_file(video, target_w, target_h):
    files = [f for f in video.get("video_files", [])
             if f.get("link") and f.get("width") and f.get("height")
             and f.get("file_type", "video/mp4") == "video/mp4"]
    if not files:
        return None
    # Prefer a usable HD/Full-HD rendition; avoid downloading unnecessary 4K files.
    def key(file_info):
        width = file_info["width"]
        height = file_info["height"]
        aspect = _aspect_score(width, height, target_w, target_h)
        practical = 1.0 if 960 <= width <= 2200 else 0.55
        return aspect + practical * 0.06
    return max(files, key=key)


def _pexels_video_search(query, target_w, target_h):
    """Return ranked Pexels candidates and source metadata; never expose the key."""
    api_key = env("PEXELS_API_KEY")
    if not api_key:
        log("PEXELS_API_KEY not set; skipping Pexels footage search")
        return []
    cached = _cache_get("pexels", query, target_w, target_h)
    if cached is not None:
        log(f"Pexels cache hit for {query!r}")
        return cached
    url = "https://api.pexels.com/v1/videos/search"
    try:
        response = requests.get(
            url,
            headers={"Authorization": api_key},
            params={"query": query, "per_page": 15},
            timeout=30,
        )
        if response.status_code != 200:
            log(f"Pexels search returned HTTP {response.status_code} for {query!r}")
            return []
        candidates = []
        for video in response.json().get("videos", []):
            file_info = _best_pexels_file(video, target_w, target_h)
            if not file_info:
                continue
            creator = (video.get("user") or {}).get("name", "Pexels contributor")
            candidates.append({
                "id": f"pexels:{video.get('id')}",
                "provider": "Pexels",
                "url": file_info["link"],
                "score": _aspect_score(file_info["width"], file_info["height"], target_w, target_h) + 0.03,
                "creator": creator,
                "source_url": video.get("url") or "https://www.pexels.com/",
                "query": query,
            })
        ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
        _cache_put("pexels", query, target_w, target_h, ranked)
        return ranked
    except Exception as exc:
        log(f"Pexels footage search failed: {exc}")
        return []


def _best_pixabay_file(hit, target_w, target_h):
    files = [f for f in (hit.get("videos") or {}).values()
             if isinstance(f, dict) and f.get("url") and f.get("width") and f.get("height")]
    if not files:
        return None
    return max(files, key=lambda f: _aspect_score(f["width"], f["height"], target_w, target_h))


def _pixabay_video_search(query, target_w, target_h):
    """Return ranked Pixabay candidates as a bounded fallback, not random footage."""
    api_key = env("PIXABAY_API_KEY")
    if not api_key:
        log("PIXABAY_API_KEY not set; skipping Pixabay footage search")
        return []
    cached = _cache_get("pixabay", query, target_w, target_h)
    if cached is not None:
        log(f"Pixabay cache hit for {query!r}")
        return cached
    try:
        response = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": api_key, "q": query, "per_page": 15, "safesearch": "true", "order": "popular"},
            timeout=30,
        )
        if response.status_code != 200:
            log(f"Pixabay search returned HTTP {response.status_code} for {query!r}")
            return []
        candidates = []
        for hit in response.json().get("hits", []):
            file_info = _best_pixabay_file(hit, target_w, target_h)
            if not file_info:
                continue
            candidates.append({
                "id": f"pixabay:{hit.get('id')}",
                "provider": "Pixabay",
                "url": file_info["url"],
                "score": _aspect_score(file_info["width"], file_info["height"], target_w, target_h),
                "creator": hit.get("user") or "Pixabay contributor",
                "source_url": hit.get("pageURL") or "https://pixabay.com/",
                "query": query,
            })
        ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
        _cache_put("pixabay", query, target_w, target_h, ranked)
        return ranked
    except Exception as exc:
        log(f"Pixabay footage search failed: {exc}")
        return []


def _parse_scene_meta(prompt: str) -> dict:
    """Read compact metadata appended by build_script.py while retaining safe defaults."""
    meta = {
        "scene_type": "EXPLAIN",
        "kb_preset": "pan_right",
        "dur_mult": 1.0,
        "broll": "",
        "fallback": "",
        "stat": "",
    }
    scene_match = re.search(r"scene_type:(\w+)\|kb:(\w+)\|dur:([\d.]+)", prompt or "")
    if scene_match:
        meta["scene_type"] = scene_match.group(1)
        meta["kb_preset"] = scene_match.group(2)
        try:
            meta["dur_mult"] = float(scene_match.group(3))
        except ValueError:
            pass
    for key in ("broll", "fallback", "stat"):
        match = re.search(rf"(?:^|\|){key}:([^|]+)", prompt or "")
        if match:
            meta[key] = " ".join(match.group(1).split()).strip()
    return meta


def _clean_image_prompt(prompt: str) -> str:
    """Remove renderer metadata before using the rare AI-still fallback."""
    return (prompt or "").split("|scene_type:", 1)[0].strip(" ,")


def _download_candidate(candidate, destination: Path) -> bool:
    try:
        response = requests.get(candidate["url"], stream=True, timeout=75)
        if response.status_code != 200:
            return False
        with open(destination, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    handle.write(chunk)
        return _is_video_valid(destination)
    except Exception as exc:
        log(f"clip download failed for {candidate.get('id')}: {exc}")
        return False


def _fetch_video_asset(index, meta, target_w, target_h, used_clips, used_creators,
                       recent_ids, variant):
    """Download a relevant clip while avoiding exact, contributor, and recent repeats."""
    destination = OUT / f"scene_{index:02d}_{variant}.mp4"
    destination.unlink(missing_ok=True)
    queries = [query for query in (meta.get("broll"), meta.get("fallback")) if query]
    for query in dict.fromkeys(queries):  # preserve order, remove duplicate fallback
        candidates = _pexels_video_search(query, target_w, target_h)
        candidates.extend(_pixabay_video_search(query, target_w, target_h))
        candidates.sort(key=lambda item: item["score"], reverse=True)
        # Prefer a fresh contributor and a clip not used by the last several posts.
        # If the providers return too few candidates, the second pass relaxes only
        # the recency/contributor constraints, while still preventing same-scene reuse.
        fresh = [candidate for candidate in candidates
                 if candidate.get("id") not in used_clips
                 and candidate.get("id") not in recent_ids
                 and candidate.get("creator") not in used_creators]
        relaxed = [candidate for candidate in candidates
                   if candidate.get("id") not in used_clips]
        for candidate in fresh + [item for item in relaxed if item not in fresh]:
            if _download_candidate(candidate, destination):
                clip_id = candidate["id"]
                used_clips.add(clip_id)
                if candidate.get("creator"):
                    used_creators.add(candidate["creator"])
                provenance = {key: candidate[key] for key in ("id", "provider", "creator", "source_url", "query")}
                provenance["scene"] = index
                provenance["variant"] = variant
                log(f"scene {index} [{variant}] -> {candidate['provider']} footage for {query!r}")
                return destination, provenance
    log(f"scene {index}: no suitable stock clip for {queries!r}; using image fallback")
    return None, None


def _fetch_scene(index, prompt, target_w, target_h, slug, image_url, used_clips,
                 used_creators, recent_ids, variant):
    meta = _parse_scene_meta(prompt)
    video_asset, provenance = _fetch_video_asset(
        index, meta, target_w, target_h, used_clips, used_creators, recent_ids, variant)
    if video_asset:
        return video_asset, meta, provenance

    destination = OUT / f"scene_{index:02d}_{variant}.jpg"
    destination.unlink(missing_ok=True)
    if index == 0 and image_url:
        try:
            response = requests.get(image_url, timeout=30)
            if response.status_code == 200:
                destination.write_bytes(response.content)
                return destination, meta, None
        except Exception as exc:
            log(f"hero-image fallback failed: {exc}")

    clean_prompt = _clean_image_prompt(prompt)
    seed = int(hashlib.sha256(f"{slug}:{index}:{variant}".encode()).hexdigest()[:8], 16) % 100000
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(clean_prompt)
           + f"?width={target_w}&height={target_h}&nologo=true&model=flux&seed={seed}")
    try:
        response = requests.get(url, timeout=75)
        if response.status_code == 200:
            destination.write_bytes(response.content)
            return destination, meta, None
    except Exception as exc:
        log(f"image fallback failed: {exc}")

    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={target_w}x{target_h}",
         "-frames:v", "1", "-update", "1", str(destination)])
    return destination, meta, None


def fetch_scene_assets(script, cfg, variant):
    """Fetch format-specific assets while maintaining cross-post visual variety."""
    target_size = cfg["video"][variant]
    target_w, target_h = target_size["w"], target_size["h"]
    post = script["post"]
    used_clips, used_creators = set(), set()
    history = _load_footage_history()
    recent_ids = {item["id"] for item in history}
    assets, provenance = [], []
    for index, prompt in enumerate(script["scene_prompts"]):
        asset, meta, source = _fetch_scene(
            index, prompt, target_w, target_h, post["slug"],
            post.get("image_url") if index == 0 else None, used_clips,
            used_creators, recent_ids, variant,
        )
        assets.append((asset, meta))
        if source:
            provenance.append(source)
            recent_ids.add(source["id"])
            history.append({"id": source["id"], "provider": source.get("provider"),
                            "creator": source.get("creator"), "slug": post["slug"],
                            "used_at": time.time()})
    _save_footage_history(history)
    return assets, provenance


# ---------- 3. Scene assembly ----------

def build_clip(scene_assets, total_duration, size, fps, out_path, grade=None):
    """Create a paced montage, with every scene assigned timestamps for overlays."""
    width, height = size["w"], size["h"]
    count = len(scene_assets)
    if not count:
        raise RuntimeError("No scene assets were created")

    raw_multipliers = [meta.get("dur_mult", 1.0) for _, meta in scene_assets]
    total_multiplier = sum(raw_multipliers) or 1.0
    scene_durations = [max(1.0, total_duration * mult / total_multiplier)
                       for mult in raw_multipliers]
    # Normalise after minimum-duration clamping so the cut tracks the narration.
    duration_scale = total_duration / max(sum(scene_durations), 0.01)
    scene_durations = [duration * duration_scale for duration in scene_durations]

    cursor = 0.0
    for (_, meta), duration in zip(scene_assets, scene_durations):
        meta["start"] = cursor
        meta["end"] = cursor + duration
        cursor += duration

    transition_duration = 0.45 if count > 1 else 0.0
    segment_files = []
    for index, ((asset, _meta), scene_duration) in enumerate(zip(scene_assets, scene_durations)):
        segment = OUT / f"_seg_{width}x{height}_{index:02d}.mp4"
        segment_duration = scene_duration + transition_duration
        if asset.suffix.lower() == ".mp4":
            source_duration = ffprobe_duration(asset)
            video_filter = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
            if grade:
                video_filter += f",{grade}"
            cmd = ["ffmpeg", "-y"]
            if source_duration > segment_duration + 0.3:
                available = max(source_duration - segment_duration, 0.01)
                offset = (index * 1.618) % available
                cmd += ["-ss", f"{offset:.3f}", "-i", str(asset)]
            else:
                cmd += ["-stream_loop", "-1", "-i", str(asset)]
            cmd += ["-t", f"{segment_duration:.3f}", "-vf", video_filter,
                    "-r", str(fps), "-pix_fmt", "yuv420p", "-an", str(segment)]
            run(cmd)
        else:
            frames = max(1, int(segment_duration * fps))
            ken_burns = "z='min(1.05+0.0005*on,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            video_filter = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                            f"crop={width}:{height},setsar=1,zoompan={ken_burns}:"
                            f"d={frames}:s={width}x{height}:fps={fps}")
            if grade:
                video_filter += f",{grade}"
            video_filter += ",format=yuv420p"
            run(["ffmpeg", "-y", "-loop", "1", "-i", str(asset), "-t", f"{segment_duration:.3f}",
                 "-vf", video_filter, "-r", str(fps), "-pix_fmt", "yuv420p", "-an", str(segment)])
        segment_files.append((segment, scene_duration))

    if count == 1:
        run(["ffmpeg", "-y", "-i", str(segment_files[0][0]), "-t", f"{total_duration:.3f}",
             "-c", "copy", str(out_path)])
        return out_path

    inputs = []
    for segment, _ in segment_files:
        inputs += ["-i", str(segment)]
    filter_chain, previous = [], "0:v"
    offset = 0.0
    for index in range(1, count):
        label = f"x{index}" if index < count - 1 else "vout"
        offset += scene_durations[index - 1]
        filter_chain.append(
            f"[{previous}][{index}:v]xfade=transition=fade:duration={transition_duration}:"
            f"offset={offset:.3f}[{label}]"
        )
        previous = label
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filter_chain), "-map", "[vout]",
         "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p", str(out_path)])
    return out_path


# ---------- 4. Captions, music, and overlays ----------

def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def transcribe_words(audio_path):
    """Transcribe the voiceover and return word-level timing data.

    Returns a list of dicts: [{"text": "word", "start": 1.23, "end": 1.45}, ...]
    or None on failure (non-fatal — caller renders without captions).
    """
    try:
        from faster_whisper import WhisperModel

        model_name = env("WHISPER_MODEL") or "base"
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(audio_path), beam_size=4, vad_filter=True,
                                           word_timestamps=True)
        words = []
        for segment in segments:
            if segment.words:
                for w in segment.words:
                    text = w.word.strip()
                    if text:
                        words.append({
                            "text": text,
                            "start": float(w.start),
                            "end": float(w.end),
                        })
        if words:
            log(f"word-level transcription: {len(words)} words")
            return words
        log("caption model returned no speech segments; continuing without captions")
    except Exception as exc:
        log(f"caption generation skipped ({exc})")
    return None


def make_captions(audio_path, tag=""):
    """Backwards-compatible: create an SRT from the rendered voice.

    NOTE: the new pipeline uses `transcribe_words` instead for word-by-word
    captions. This function is kept for any legacy callers.
    """
    output = OUT / f"captions{tag}.srt"
    output.unlink(missing_ok=True)
    try:
        from faster_whisper import WhisperModel

        model_name = env("WHISPER_MODEL") or "base"
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(audio_path), beam_size=4, vad_filter=True)
        rows = []
        for index, segment in enumerate(segments, 1):
            text = " ".join(segment.text.split())
            if text:
                rows.append(f"{index}\n{_srt_timestamp(segment.start)} --> {_srt_timestamp(segment.end)}\n{text}\n")
        if rows:
            output.write_text("\n".join(rows), encoding="utf-8")
            log(f"captions -> {output.name}")
            return output
        log("caption model returned no speech segments; continuing without captions")
    except Exception as exc:
        log(f"caption generation skipped ({exc})")
    return None


def choose_music(script):
    music_dir = ROOT / "assets" / "music"
    tracks = sorted(path for path in music_dir.glob("*")
                    if path.is_file() and path.suffix.lower() in MUSIC_EXTENSIONS)
    if not tracks:
        log("no royalty-free music tracks found; rendering voiceover only")
        return None
    key = f"{script['post'].get('slug', '')}:{dt.date.today().isoformat()}"
    index = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % len(tracks)
    log(f"music bed -> {tracks[index].name}")
    return tracks[index]


def _ffmpeg_text(text: str) -> str:
    """Escape text for the drawtext filter while preserving explicit line breaks.

    Every special character that FFmpeg's ``-filter_complex`` parser treats
    as a structural delimiter must be escaped:

    * ``\`` → ``\\``  (backslash itself, first)
    * ``'`` → ``\x27`` (apostrophe — \' breaks out of single-quote context)
    * ``:`` → ``\:``  (option separator)
    * ``,`` → ``\,``  (filter-chain separator inside -filter_complex)
    * ``\n`` → ``\n`` (literal newline in the rendered caption)

    The order matters: backslash must be escaped first, otherwise the
    inserted ``\`` characters from later replacements would themselves be
    re-escaped.
    """
    return (text.replace("\\", r"\\").replace("'", r"\x27").replace(":", r"\:")
                .replace(",", r"\,").replace("\n", r"\n"))


def _ffmpeg_path(path: Path) -> str:
    return str(path).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")


def _wrap_text(text: str, limit: int) -> str:
    words, lines, line = (text or "").split(), [], ""
    for word in words:
        proposed = f"{line} {word}".strip()
        if line and len(proposed) > limit:
            lines.append(line)
            line = word
        else:
            line = proposed
    if line:
        lines.append(line)
    return "\n".join(lines[:3])


def _append_filter(filters, source_label, filter_body, target_label):
    filters.append(f"[{source_label}]{filter_body}[{target_label}]")
    return target_label


def _source_credits(sources):
    seen, credits = set(), []
    for source in sources:
        source_id = source.get("id")
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        provider = source.get("provider", "Stock footage")
        creator = source.get("creator", "contributor")
        source_url = source.get("source_url") or ("https://www.pexels.com/" if provider == "Pexels" else "https://pixabay.com/")
        credits.append(f"{provider}: {creator} — {source_url}")
    return credits


def _with_attribution(platform, sources):
    """Preserve asset provenance and add a compact Pexels/Pixabay credit block to YouTube."""
    output = dict(platform)
    credits = _source_credits(sources)
    output["footage_credits"] = credits
    if credits:
        block = "\n\nFootage credits:\n" + "\n".join(f"• {credit}" for credit in credits)
        output["yt_desc"] = (output.get("yt_desc", "") + block)[:4900]
    return output


def _build_word_caption_filters(words, size):
    """Build FFmpeg drawtext filters for word-by-word bottom captions.

    Each word is displayed individually at the bottom of the screen, timed
    to its Whisper word-level start/end.  No background box — just clean
    white text with a black shadow/outline for readability over any footage.
    """
    width, height = size["w"], size["h"]
    if not words:
        return []

    # Font size: larger for vertical (9:16) videos, smaller for horizontal
    font_size = 56 if height > width else 40

    # Position: bottom of the screen with a small margin.
    # We use an absolute Y position so the caption stays locked at the bottom
    # regardless of aspect ratio.
    margin_from_bottom = int(max(60, height * 0.05))
    y_expr = f"h-{margin_from_bottom}"

    filters = []
    for i, word_info in enumerate(words):
        text = word_info["text"]
        start = word_info["start"]
        end = word_info["end"]

        safe_text = _ffmpeg_text(text)
        # Escape commas in the enable expression — FFmpeg treats commas as
        # filter-chain separators inside -filter_complex, so ``between(t,1.0,2.0)``
        # without escaping is parsed as three separate arguments.
        enable_expr = f"between(t\\,{start:.3f}\\,{end:.3f})"

        filter_opts = [
            f"fontfile={FONT_FILE}",
            f"text={safe_text}",
            "expansion=none",
            "fontcolor=white",
            f"fontsize={font_size}",
            "x=(w-text_w)/2",
            f"y={y_expr}",
            "shadowcolor=black@0.85",
            "shadowx=2",
            "shadowy=2",
            f"enable={enable_expr}",
        ]
        filters.append("drawtext=" + ":".join(filter_opts))

    return filters


def finalize(video_path, voice_path, word_timings, music, size, out_path, cfg, scene_assets, hook_text, total_duration):
    """Burn word-by-word captions at the bottom of the video, then mix a ducked music bed.

    No text overlays cover the video: no hook card, no data lower-third, no end card.
    Captions are the ONLY on-screen text and they appear word-by-word at the bottom.
    """
    inputs = ["-i", str(video_path), "-i", str(voice_path)]
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]

    filters, video_label, label_count = [], "0:v", 0

    def add_video_filter(body):
        nonlocal video_label, label_count
        label_count += 1
        target = f"v{label_count}"
        video_label = _append_filter(filters, video_label, body, target)

    # Word-by-word bottom captions (no box, no background, just clean text)
    if word_timings:
        word_filters = _build_word_caption_filters(word_timings, size)
        for wf in word_filters:
            add_video_filter(wf)

    audio_label = "1:a"
    if music:
        volume = cfg.get("video", {}).get("music_volume", 0.1)
        filters.append(f"[2:a]volume={volume}[bg]")
        filters.append("[bg][1:a]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=300[duck]")
        filters.append("[1:a][duck]amix=inputs=2:duration=first:dropout_transition=2[aout]")
        audio_label = "aout"

    cmd = ["ffmpeg", "-y", *inputs]
    if filters:
        video_map = f"[{video_label}]" if video_label != "0:v" else "0:v"
        audio_map = f"[{audio_label}]" if audio_label != "1:a" else "1:a"
        cmd += ["-filter_complex", ";".join(filters), "-map", video_map, "-map", audio_map]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "22", "-c:a", "aac",
            "-movflags", "+faststart", "-shortest", str(out_path)]
    run(cmd)
    return out_path


# ---------- 5. Master variants ----------

def render_variant(name, narration, script, cfg, scene_assets, music):
    tag = "" if name == "vertical" else "_yt"
    voice, duration = make_voice(narration, cfg, tag)
    # Use word-level transcription instead of SRT-based captions
    word_timings = transcribe_words(voice) if cfg["video"].get("captions") else None
    size = cfg["video"][name]
    montage = OUT / f"montage_{name}.mp4"
    final_path = OUT / ("video_9x16.mp4" if name == "vertical" else "video_16x9.mp4")
    build_clip(scene_assets, duration, size, cfg["video"]["fps"], montage)
    finalize(montage, voice, word_timings, music, size, final_path, cfg, scene_assets,
             script.get("hook"), duration)
    return final_path, duration, word_timings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("script_json")
    args = parser.parse_args()
    cfg = load_config()
    script = read_json(args.script_json)

    vertical_assets, vertical_sources = fetch_scene_assets(script, cfg, "vertical")
    music = choose_music(script) if cfg["video"].get("music") else None

    vertical, vertical_duration, _vertical_words = render_variant(
        "vertical", script["narration"], script, cfg, vertical_assets, music)
    videos = {"vertical": str(vertical)}
    asset_sources = {"vertical": vertical_sources}
    youtube_sources = vertical_sources

    if cfg["video"].get("make_horizontal"):
        horizontal_assets, horizontal_sources = fetch_scene_assets(script, cfg, "horizontal")
        horizontal, horizontal_duration, _horizontal_words = render_variant(
            "horizontal", script.get("narration_yt") or script["narration"], script,
            cfg, horizontal_assets, music)
        videos["horizontal"] = str(horizontal)
        asset_sources["horizontal"] = horizontal_sources
        youtube_sources = horizontal_sources
    else:
        horizontal_duration = None

    output = {
        "post": script["post"],
        "platform": _with_attribution(script["platform"], youtube_sources),
        "videos": videos,
        "duration": vertical_duration,
        "horizontal_duration": horizontal_duration,
        "assets": asset_sources,
    }
    write_json("render.json", output)
    log("Render complete.")


if __name__ == "__main__":
    main()
