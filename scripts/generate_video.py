"""Render footage-driven social and YouTube videos from a generated blog script.

Pipeline:
  ElevenLabs           -> voiceover + exact word timings (edge-tts / clone fallback)
  Pexels + Pixabay     -> semantically matched scene clips (two angles per scene)
  faster-whisper       -> word timings only when the voice provider gives none
  FFmpeg               -> finished vertical and horizontal masters

The renderer treats stock-video search as an editorial step.  Every scene carries a
primary concrete B-roll query and a category-safe fallback from build_script.py;
this avoids querying every scene with the article title and filling technical videos
with unrelated landscape footage.

Edit:
  - Scene cuts land on the word where each scene's narration begins, and long
    scenes are broken into ~2.6s shots with camera moves (push, pull, pan, rise).
  - One colour grade per post (topic-specific from build_script.py), film grain
    and vignette, applied once over the whole montage.
  - Captions are animated 1-3 word karaoke punches (Anton, active word in yellow),
    burned in with libass. No hook card, lower third, or end card.
  - Audio: mastered voice, EQ-scooped music bed ducked under it, -14 LUFS output.
"""
import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

import requests

from common import OUT, ROOT, STATE, env, load_config, log, read_json, write_json


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
    """Return (audio_path, duration, word_timings_or_None, provider)."""
    voice_cfg = cfg["voice"]
    if voice_cfg.get("provider", "elevenlabs") == "elevenlabs":
        eleven_out = OUT / f"voiceover{tag}_11labs.mp3"
        eleven_out.unlink(missing_ok=True)
        try:
            from tts_elevenlabs import synthesize as eleven_synthesize
            result = eleven_synthesize(narration, str(eleven_out), cfg)
        except Exception as exc:  # noqa
            log(f"ElevenLabs voice failed ({exc})")
            result = None
        if result:
            duration = ffprobe_duration(eleven_out)
            if duration > 0.25:
                log(f"ElevenLabs voiceover {duration:.1f}s -> {eleven_out.name}")
                return eleven_out, duration, result[1] or None, "elevenlabs"
        log("ElevenLabs unavailable; falling back to the next configured voice")
    if (voice_cfg.get("kokoro") or {}).get("enabled"):
        # Free, no-quota neural voice; captions get word timings from transcription.
        try:
            from tts_kokoro import synthesize as kokoro_synthesize
            kokoro_out = kokoro_synthesize(narration, OUT / f"voiceover{tag}_kokoro.wav", cfg)
        except Exception as exc:  # noqa
            log(f"Kokoro voice failed ({exc})")
            kokoro_out = None
        if kokoro_out:
            duration = ffprobe_duration(kokoro_out)
            if duration > 0.25:
                log(f"Kokoro voiceover {duration:.1f}s -> {kokoro_out.name}")
                return kokoro_out, duration, None, "kokoro"
        log("Kokoro unavailable; falling back to edge-tts")
    path, duration, provider = _make_voice_fallback(narration, cfg, tag)
    return path, duration, None, provider


def _make_voice_fallback(narration, cfg, tag=""):
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
                    return clone_out, duration, "clone"
            if voice_cfg.get("clone_required", True):
                raise RuntimeError(
                    "cloned voice synthesis did not produce valid audio; "
                    "refusing to use a different accent"
                )
            log("voice clone unavailable; falling back to configured TTS voice")
        except Exception as exc:  # noqa
            if voice_cfg.get("clone_required", True):
                raise RuntimeError(
                    f"cloned voice synthesis failed; refusing stock-voice fallback: {exc}"
                ) from exc
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
    return out, duration, "edge-tts"


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
        ordered = fresh + [item for item in relaxed if item not in fresh]
        for position, candidate in enumerate(ordered):
            if _download_candidate(candidate, destination):
                clip_id = candidate["id"]
                used_clips.add(clip_id)
                if candidate.get("creator"):
                    used_creators.add(candidate["creator"])
                provenance = {key: candidate[key] for key in ("id", "provider", "creator", "source_url", "query")}
                provenance["scene"] = index
                provenance["variant"] = variant
                log(f"scene {index} [{variant}] -> {candidate['provider']} footage for {query!r}")
                # A second angle on the same idea lets long scenes cut between shots
                # instead of sitting on one clip for 6+ seconds.
                meta["alt"], meta["alt_source"] = None, None
                alt_destination = OUT / f"scene_{index:02d}_{variant}_b.mp4"
                alt_destination.unlink(missing_ok=True)
                for alt in ordered[position + 1:position + 4]:
                    if alt["id"] in used_clips:
                        continue
                    if _download_candidate(alt, alt_destination):
                        used_clips.add(alt["id"])
                        alt_prov = {key: alt[key] for key in ("id", "provider", "creator", "source_url", "query")}
                        alt_prov["scene"] = index
                        alt_prov["variant"] = variant
                        meta["alt"], meta["alt_source"] = alt_destination, alt_prov
                        break
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
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=75)
            if response.status_code == 200 and len(response.content) > 20000:
                destination.write_bytes(response.content)
                return destination, meta, None
            log(f"image fallback HTTP {response.status_code} (attempt {attempt + 1})")
        except Exception as exc:
            log(f"image fallback failed: {exc}")
        time.sleep(6 * (attempt + 1))  # the free endpoint rate-limits bursts

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
        for item in (source, (meta or {}).get("alt_source")):
            if not item:
                continue
            provenance.append(item)
            recent_ids.add(item["id"])
            history.append({"id": item["id"], "provider": item.get("provider"),
                            "creator": item.get("creator"), "slug": post["slug"],
                            "used_at": time.time()})
    _save_footage_history(history)
    return assets, provenance


# ---------- 3. Scene assembly ----------

def scene_windows(words, narration, count, total_duration):
    """Start/end seconds for each scene, locked to when its words are spoken.

    build_script.py splits the narration into `count` equal word-count segments and
    writes one footage brief per segment. Cutting at the moment the first word of
    each segment is voiced keeps every clip on screen while its idea is being said.
    Without timings (rare) the cuts fall back to an even split.
    """
    if count <= 0:
        return []
    script_words = (narration or "").split()
    total_words = len(script_words)
    if not words or not total_words:
        step = total_duration / count
        return [(i * step, (i + 1) * step) for i in range(count)]
    base, remainder = divmod(total_words, count)
    starts, index = [], 0
    for i in range(count):
        starts.append(index)
        index += base + (1 if i < remainder else 0)
    times = [0.0]
    for k in starts[1:]:
        mapped = min(len(words) - 1, int(round(k * len(words) / total_words)))
        # Cut a beat before the word lands; it reads as intentional editing.
        times.append(max(times[-1] + 0.8, words[mapped]["start"] - 0.08))
    times.append(total_duration)
    windows = []
    for i in range(count):
        start, end = times[i], max(times[i + 1], times[i] + 0.5)
        windows.append((start, min(end, total_duration)))
    return windows


MOTIONS = ("push_in", "pan_right", "pull_out", "pan_left", "rise", "push_in_slow")


def _motion_filter(kind, width, height, duration):
    """Camera move for one shot: smooth push/pull via per-frame scale, or a pan."""
    d = max(duration, 0.2)
    p = f"min(t/{d:.3f}\\,1)"
    if kind in ("push_in", "pull_out", "punch", "push_in_slow"):
        z0, z1 = {"push_in": (1.04, 1.14), "pull_out": (1.16, 1.04),
                  "punch": (1.24, 1.08), "push_in_slow": (1.02, 1.08)}[kind]
        zoom = f"({z0}+({z1 - z0:.3f})*{p})"
        return (f"scale=w='trunc({width}*{zoom}/2)*2':h='trunc({height}*{zoom}/2)*2':"
                f"force_original_aspect_ratio=increase:eval=frame:flags=bicubic,"
                f"crop={width}:{height}")
    over_w, over_h = int(width * 1.12) // 2 * 2, int(height * 1.12) // 2 * 2
    x, y = "(in_w-out_w)/2", "(in_h-out_h)/2"
    if kind == "pan_right":
        x = f"(in_w-out_w)*{p}"
    elif kind == "pan_left":
        x = f"(in_w-out_w)*(1-{p})"
    elif kind == "rise":
        y = f"(in_h-out_h)*(1-{p})"
    return (f"scale={over_w}:{over_h}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={width}:{height}:x='{x}':y='{y}'")


def _plan_shots(scene_assets, windows, fps, cfg, total_frames):
    """Break each scene into ~1.7-3s shots so the edit never stalls on one clip."""
    shot_seconds = float(cfg.get("video", {}).get("shot_seconds", 2.6))
    shots = []
    for index, ((asset, meta), (start, end)) in enumerate(zip(scene_assets, windows)):
        target = 1.7 if meta.get("scene_type") == "HOOK" else shot_seconds
        pieces = max(1, int(round((end - start) / target)))
        if meta.get("card"):
            # A motion card is one continuous animation: never split, offset or swapped.
            shots.append({"scene": index, "shot": 0, "asset": asset, "motion": "push_in_slow",
                          "card": True, "start": start, "end": end})
            continue
        step = (end - start) / pieces
        for j in range(pieces):
            source = asset
            if j % 2 == 1 and meta.get("alt") and Path(meta["alt"]).exists():
                source = Path(meta["alt"])
            if index == 0 and j == 0:
                motion = "punch"
            else:
                motion = MOTIONS[(index * 2 + j) % len(MOTIONS)]
            shots.append({"scene": index, "shot": j, "asset": source, "motion": motion,
                          "start": start + j * step, "end": start + (j + 1) * step})
    # Frame-exact boundaries so the montage length never drifts from the voice.
    for shot in shots:
        shot["f0"] = int(round(shot["start"] * fps))
    for current, following in zip(shots, shots[1:]):
        current["frames"] = max(1, following["f0"] - current["f0"])
    if shots:
        shots[-1]["frames"] = max(1, total_frames - shots[-1]["f0"])
    return shots


def _encode_args(fps):
    return ["-r", str(fps), "-pix_fmt", "yuv420p", "-an", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "16"]


def build_clip(scene_assets, windows, size, fps, out_path, cfg=None, total_duration=None):
    """Cut a montage whose shots change on the beat of the narration."""
    width, height = size["w"], size["h"]
    if not scene_assets:
        raise RuntimeError("No scene assets were created")
    total_duration = total_duration or windows[-1][1]
    total_frames = int(round(total_duration * fps))
    shots = _plan_shots(scene_assets, windows, fps, cfg or {}, total_frames)

    segment_files = []
    for number, shot in enumerate(shots):
        asset, frames = shot["asset"], shot["frames"]
        seconds = frames / fps
        segment = OUT / f"_shot_{width}x{height}_{number:03d}.mp4"
        if asset.suffix.lower() == ".mp4":
            source_duration = ffprobe_duration(asset)
            cmd = ["ffmpeg", "-y", "-v", "error"]
            if shot.get("card"):
                cmd += ["-i", str(asset)]          # play from frame 0; tpad holds the end
            elif source_duration > seconds + 0.3:
                available = max(source_duration - seconds - 0.1, 0.01)
                offset = (shot["scene"] * 1.618 + shot["shot"] * 2.35) % available
                cmd += ["-ss", f"{offset:.3f}", "-i", str(asset)]
            else:
                cmd += ["-stream_loop", "-1", "-i", str(asset)]
            hold = "tpad=stop_mode=clone:stop_duration=30," if shot.get("card") else ""
            video_filter = (f"{hold}fps={fps},{_motion_filter(shot['motion'], width, height, seconds)},"
                            f"setsar=1,format=yuv420p")
            run(cmd + ["-vf", video_filter, "-frames:v", str(frames), *_encode_args(fps), str(segment)])
        else:
            zoom = ("z='min(1.04+0.0009*on,1.18)'" if shot["shot"] % 2 == 0
                    else "z='max(1.18-0.0009*on,1.04)'")
            video_filter = (f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
                            f"crop={width * 2}:{height * 2},setsar=1,zoompan={zoom}:"
                            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:"
                            f"s={width}x{height}:fps={fps},format=yuv420p")
            run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(asset), "-vf", video_filter,
                 "-frames:v", str(frames), *_encode_args(fps), str(segment)])
        segment_files.append(segment)

    concat_list = OUT / f"_concat_{width}x{height}.txt"
    concat_list.write_text("".join(f"file '{seg.resolve().as_posix()}'\n" for seg in segment_files),
                           encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(out_path)])
    log(f"montage {width}x{height}: {len(shots)} shots over {len(scene_assets)} scenes")
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
        import numpy as np

        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        # Decode with the system FFmpeg rather than PyAV so a PyAV/FFmpeg version
        # mismatch can't silently drop the captions.
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio_path), "-f", "s16le",
                              "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = model.transcribe(audio, beam_size=4, vad_filter=True,
                                           word_timestamps=True)
        words = []
        for segment in segments:
            if segment.words:
                for w in segment.words:
                    text = w.word.strip()
                    # Whisper splits "GPT-5.5" / "80%" into "GPT-5" + ".5" / "80" + "%".
                    if words and text and text[0] in ".%," and w.start - words[-1]["end"] < 0.15:
                        words[-1]["text"] += text
                        words[-1]["end"] = float(w.end)
                        continue
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
    """Preserve asset provenance without exposing footage credits in published copy."""
    output = dict(platform)
    output["footage_credits"] = _source_credits(sources)
    return output


FONT_DIR = ROOT / "assets" / "fonts"
DEFAULT_GRADE = ("eq=contrast=1.08:saturation=1.06:gamma=0.98,"
                 "colorbalance=rs=-0.03:bs=0.04:rh=0.04:bh=-0.03,"
                 "vignette=PI/5")


def _ass_time(seconds: float) -> str:
    centis = max(0, int(round(seconds * 100)))
    hours, centis = divmod(centis, 360000)
    minutes, centis = divmod(centis, 6000)
    secs, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centis:02}"


def _ass_clean(text: str) -> str:
    return re.sub(r"[{}\\]", "", text or "").strip()


def _caption_chunks(words, max_words, max_chars):
    """Group words into 1-3 word punches that break on punctuation and pauses."""
    chunks, current = [], []
    for i, word in enumerate(words):
        current.append(word)
        text_len = len(" ".join(w["text"] for w in current))
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = nxt is not None and nxt["start"] - word["end"] > 0.35
        punct = word["text"][-1:] in ".,!?;:"
        too_long = nxt is not None and text_len + 1 + len(nxt["text"]) > max_chars
        if len(current) >= max_words or pause or punct or too_long or nxt is None:
            chunks.append(current)
            current = []
    return chunks


def write_ass_captions(words, size, out_path, cfg=None):
    """Animated karaoke captions: bold condensed type, the spoken word lights up."""
    width, height = size["w"], size["h"]
    vertical = height > width
    video_cfg = (cfg or {}).get("video", {})
    font = video_cfg.get("caption_font", "Anton")
    font_size = int(video_cfg.get("caption_size_v" if vertical else "caption_size_h",
                                  104 if vertical else 78))
    margin_v = int(video_cfg.get("caption_margin_v" if vertical else "caption_margin_h",
                                 560 if vertical else 110))
    highlight = video_cfg.get("caption_highlight", "&H0035E1FF")  # ASS is BGR: #FFE135
    outline = 6 if vertical else 4.5
    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{font},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,"
        f"0,0,0,0,100,100,1,0,1,{outline},3,2,60,60,{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    clean = [dict(w, text=_ass_clean(w["text"]).upper()) for w in words if _ass_clean(w["text"])]
    chunks = _caption_chunks(clean, 3, 18 if vertical else 28)
    for c_index, chunk in enumerate(chunks):
        next_start = chunks[c_index + 1][0]["start"] if c_index + 1 < len(chunks) else None
        chunk_end = chunk[-1]["end"] + 0.35
        if next_start is not None:
            chunk_end = min(chunk_end, next_start)
        for w_index, word in enumerate(chunk):
            start = word["start"] if w_index else chunk[0]["start"]
            end = chunk[w_index + 1]["start"] if w_index + 1 < len(chunk) else chunk_end
            if end <= start:
                continue
            parts = []
            for k, other in enumerate(chunk):
                if k == w_index:
                    parts.append(f"{{\\c{highlight}&\\fscx108\\fscy108}}{other['text']}"
                                 f"{{\\c&H00FFFFFF&\\fscx100\\fscy100}}")
                else:
                    parts.append(other["text"])
            pop = "{\\fscx82\\fscy82\\t(0,90,\\fscx100\\fscy100)}" if w_index == 0 else ""
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,"
                         f"{pop}{' '.join(parts)}")
    out_path = Path(out_path)
    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def master_voice(voice_path, tag=""):
    """Broadcast-style voice chain: rumble cut, de-ess, glue compression, -16 LUFS."""
    out = OUT / f"voice_master{tag}.wav"
    chain = ("highpass=f=80,deesser=i=0.35,"
             "acompressor=threshold=-18dB:ratio=3:attack=8:release=160:makeup=2,"
             "equalizer=f=3200:t=q:w=1.2:g=2,"
             "loudnorm=I=-16:TP=-1.5:LRA=9,aresample=48000")
    try:
        run(["ffmpeg", "-y", "-v", "error", "-i", str(voice_path), "-af", chain,
             "-ac", "1", str(out)])
        if out.exists() and out.stat().st_size > 1024:
            return out
    except subprocess.CalledProcessError as exc:
        log(f"voice mastering skipped ({exc})")
    return voice_path


def finalize(video_path, voice_path, word_timings, music, size, out_path, cfg, scene_assets,
             hook_text, total_duration, grade=None):
    """Grade the montage, burn animated captions, then mix and master the audio."""
    fps = cfg.get("video", {}).get("fps", 30)
    inputs = ["-i", str(Path(video_path).resolve()), "-i", str(Path(voice_path).resolve())]
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(Path(music).resolve())]

    video_chain = [grade or DEFAULT_GRADE]
    if word_timings:
        ass = write_ass_captions(word_timings, size, OUT / f"captions_{size['w']}x{size['h']}.ass", cfg)
        fonts = Path(os.path.relpath(FONT_DIR, OUT)).as_posix()
        video_chain.append(f"subtitles={ass.name}:fontsdir={fonts}")
    filters = [f"[0:v]{','.join(video_chain)},format=yuv420p[vout]"]

    total = f"{total_duration:.3f}"
    if music:
        volume = cfg.get("video", {}).get("music_volume", 0.12)
        fade_out = max(total_duration - 2.5, 0)
        filters += [
            f"[1:a]aresample=48000,apad,atrim=0:{total},asplit=2[vmain][vkey]",
            f"[2:a]aresample=48000,atrim=0:{total},highpass=f=50,"
            f"equalizer=f=3000:t=q:w=1.5:g=-5,volume={volume},"
            f"afade=t=in:d=1.2,afade=t=out:st={fade_out:.3f}:d=2.5[bg]",
            "[bg][vkey]sidechaincompress=threshold=0.02:ratio=6:attack=20:release=400[duck]",
            "[vmain][duck]amix=inputs=2:duration=first:normalize=0,"
            "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]",
        ]
    else:
        filters.append(f"[1:a]aresample=48000,apad,atrim=0:{total},"
                       "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")

    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters),
           "-map", "[vout]", "-map", "[aout]",
           # Capped bitrate: platforms re-encode anyway, and a lean master uploads fast.
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-maxrate", "12M",
           "-bufsize", "24M", "-profile:v", "high",
           "-pix_fmt", "yuv420p", "-r", str(fps), "-g", str(fps * 2),
           "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart", "-t", total, str(Path(out_path).resolve())]
    # libass resolves the caption file and font folder relative to OUT.
    run(cmd, cwd=str(OUT))
    return out_path


# ---------- 5. Master variants ----------

def render_variant(name, narration, script, cfg, scene_assets, music):
    tag = "" if name == "vertical" else "_yt"
    voice, duration, word_timings, provider = make_voice(narration, cfg, tag)
    if word_timings is None and cfg["video"].get("captions"):
        word_timings = transcribe_words(voice)
    voiced = master_voice(voice, tag)
    total = duration + float(cfg["video"].get("tail_seconds", 0.6))
    size = cfg["video"][name]
    montage = OUT / f"montage_{name}.mp4"
    final_path = OUT / ("video_9x16.mp4" if name == "vertical" else "video_16x9.mp4")
    windows = scene_windows(word_timings, narration, len(scene_assets), total)
    build_clip(scene_assets, windows, size, cfg["video"]["fps"], montage, cfg, total)
    if cfg.get("influencer", {}).get("enabled"):
        # The AI presenter cuts in over the montage; the stock footage stays as B-roll.
        try:
            from influencer import compose
            presented = compose(montage, voice, word_timings, total, size, cfg["video"]["fps"],
                                cfg, script["post"]["slug"], name,
                                OUT / f"presented_{name}.mp4")
            montage = presented or montage
        except Exception as exc:  # noqa  the presenter must never break the render
            log(f"influencer cut failed -> plain montage: {exc}")
    captions = word_timings if cfg["video"].get("captions") else None
    finalize(montage, voiced, captions, music, size, final_path, cfg, scene_assets,
             script.get("hook"), total, grade=script.get("grade"))
    return final_path, total, word_timings, provider


STORY_MAX_SECONDS = 58.0


def make_story_cut(vertical, duration):
    """Instagram/Facebook Stories reject clips over 60s; trim the vertical master
    to 58s with a short picture and sound fade so the cut doesn't end mid-word abruptly."""
    if duration <= STORY_MAX_SECONDS:
        return vertical
    out = OUT / "video_story.mp4"
    fade_start = STORY_MAX_SECONDS - 1.2
    run(["ffmpeg", "-y", "-v", "error", "-i", str(vertical), "-t", f"{STORY_MAX_SECONDS}",
         "-vf", f"fade=t=out:st={fade_start}:d=1.2",
         "-af", f"afade=t=out:st={fade_start}:d=1.2",
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-maxrate", "12M",
         "-bufsize", "24M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(out)])
    log(f"story cut {STORY_MAX_SECONDS:.0f}s -> {out.name}")
    return out


def _with_motion_cards(script, cfg, assets, variant):
    """Swap a few scenes for HyperFrames stat/key-point cards (motion_cards.py)."""
    if not cfg.get("motion_cards", {}).get("enabled"):
        return assets
    try:
        from motion_cards import apply_cards
        return apply_cards(script, cfg, assets, variant)
    except Exception as exc:  # noqa  cards must never break the render
        log(f"motion cards skipped ({exc})")
        return assets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("script_json")
    args = parser.parse_args()
    cfg = load_config()
    script = read_json(args.script_json)

    vertical_assets, vertical_sources = fetch_scene_assets(script, cfg, "vertical")
    vertical_assets = _with_motion_cards(script, cfg, vertical_assets, "vertical")
    music = choose_music(script) if cfg["video"].get("music") else None

    vertical, vertical_duration, _vertical_words, provider = render_variant(
        "vertical", script["narration"], script, cfg, vertical_assets, music)
    videos = {"vertical": str(vertical), "story": str(make_story_cut(vertical, vertical_duration))}
    asset_sources = {"vertical": vertical_sources}
    youtube_sources = vertical_sources

    if cfg["video"].get("make_horizontal"):
        horizontal_assets, horizontal_sources = fetch_scene_assets(script, cfg, "horizontal")
        horizontal_assets = _with_motion_cards(script, cfg, horizontal_assets, "horizontal")
        horizontal, horizontal_duration, _horizontal_words, _ = render_variant(
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
        "voice_provider": provider,
    }
    write_json("render.json", output)
    log(f"Render complete (voice: {provider}).")


if __name__ == "__main__":
    main()
