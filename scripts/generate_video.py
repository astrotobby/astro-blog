"""Stage 3: render video(s) from script.json — all free, no paid API.

  edge-tts        -> voiceover.mp3   (free Microsoft neural voices, no key)
  Pexels/Pixabay  -> scene_*.mp4     (free stock videos, no key)
  faster-whisper  -> captions.srt    (local, optional)
  ffmpeg          -> video_9x16.mp4 [+ video_16x9.mp4]

CINEMATIC VISUAL LOGIC (redesigned):
  - Scene 0 uses the post's own hero image (Pexels) for brand continuity
  - Each scene has a semantic TYPE (HOOK/ESTABLISH/EXPLAIN/TENSION/DATA/PAYOFF/CTA)
    embedded in its prompt by build_script.py
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
import random
from pathlib import Path

import requests

from common import OUT, ROOT, env, load_config, log, read_json, write_json


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
    except:
        return 0.0

def _video_dims(path):
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)])
        w, h = out.decode().strip().split("x")[:2]
        return int(w), int(h)
    except:
        return 1280, 720

# ---------- 1. voiceover ----------
async def _tts(text, voice, rate, pitch, out_path):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await comm.save(str(out_path))


def _gtts_fallback(text, out_path):
    from gtts import gTTS
    gTTS(text).save(str(out_path))


def make_voice(narration, cfg, tag=""):
    v = cfg["voice"]
    out = OUT / f"voiceover{tag}.mp3"
    if out.exists():
        out.unlink()
    try:
        asyncio.run(_tts(narration, v["name"], v["rate"], v["pitch"], out))
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("edge-tts produced no audio")
    except Exception as e:
        log(f"edge-tts failed ({e}); falling back to gTTS")
        _gtts_fallback(narration, out)
    dur = ffprobe_duration(out)
    log(f"voiceover {dur:.1f}s -> {out.name}")
    return out, dur


# ---------- 2. Video Sourcing ----------

def _is_video_valid(path):
    return path.exists() and path.stat().st_size > 10000

def _pexels_video_search(query, w, h):
    api_key = env("PEXELS_API_KEY") or "YOUR_API_KEY"
    url = f"https://api.pexels.com/v1/videos/search?query={urllib.parse.quote(query)}&per_page=10"
    headers = {"Authorization": api_key}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if data.get('videos'):
                target_ratio = w / h
                videos = data['videos']
                videos.sort(key=lambda v: abs((v['width']/v['height']) - target_ratio))
                video = videos[0]
                video_files = video.get('video_files', [])
                best_file = None
                for f in video_files:
                    if f.get('width') and 1000 <= f['width'] <= 2000:
                        best_file = f
                        break
                if not best_file and video_files:
                    best_file = video_files[0]
                return best_file['link'] if best_file else None
    except Exception as e:
        log(f"Pexels search failed: {e}")
    return None

def _pixabay_video_search(query):
    api_key = env("PIXABAY_API_KEY")
    if not api_key:
        return None
    url = f"https://pixabay.com/api/videos/?key={api_key}&q={urllib.parse.quote(query)}&per_page=5"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if data.get('hits'):
                video_hit = random.choice(data['hits'])
                v = video_hit.get('videos', {})
                best = v.get('medium') or v.get('small') or v.get('large') or v.get('tiny')
                return best['url'] if best else None
    except Exception as e:
        log(f"Pixabay search failed: {e}")
    return None

def _fetch_video_asset(i, prompt, w, h, title):
    dst = OUT / f"scene_{i:02d}.mp4"
    clean_prompt = re.sub(r",?\s*scene_type:\w+\|kb:\w+\|dur:[\d.]+", "", prompt).strip()
    m = re.search(r"theme:\s*([^,]+)", clean_prompt)
    theme = m.group(1).strip() if m else ""
    query = f"{theme} {title}".strip()[:80]
    
    video_url = _pexels_video_search(query, w, h)
    if not video_url:
        video_url = _pixabay_video_search(query)
    
    if video_url:
        try:
            r = requests.get(video_url, stream=True, timeout=60)
            if r.status_code == 200:
                with open(dst, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                if _is_video_valid(dst):
                    log(f"scene {i} video downloaded -> {dst.name}")
                    return dst
        except Exception as e:
            log(f"Failed to download video for scene {i}: {e}")
    return None

def _fetch_scene(i, prompt, w, h, token, slug, title, base_seed, image_url=None):
    meta = _parse_scene_meta(prompt)
    video_asset = _fetch_video_asset(i, prompt, w, h, title)
    if video_asset:
        return video_asset, meta
        
    dst = OUT / f"scene_{i:02d}.jpg"
    clean = re.sub(r",?\s*scene_type:\w+\|kb:\w+\|dur:[\d.]+", "", prompt).strip()
    
    if i == 0 and image_url:
        try:
            r = requests.get(image_url, timeout=30)
            if r.status_code == 200:
                dst.write_bytes(r.content)
                return dst, meta
        except: pass

    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(clean)
           + f"?width={w}&height={h}&nologo=true&model=flux&seed={base_seed+i}")
    try:
        r = requests.get(url, timeout=60)
        if r.status_code == 200:
            dst.write_bytes(r.content)
            return dst, meta
    except: pass
    
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}", "-frames:v", "1", "-update", "1", str(dst)])
    return dst, meta

def fetch_images(script, cfg):
    vz = cfg["visuals"]
    w, h = vz["width"], vz["height"]
    token = env("HF_TOKEN") or None
    slug = script["post"]["slug"]
    title = (script["post"].get("title") or "").strip()
    image_url = script["post"].get("image_url") or ""
    base_seed = abs(hash(slug)) % 100000
    
    results = []
    for i, p in enumerate(script["scene_prompts"]):
        results.append(_fetch_scene(i, p, w, h, token, slug, title, base_seed, image_url if i == 0 else None))
    return results

# ---------- 3. Scene Processing ----------

def _parse_scene_meta(prompt: str) -> dict:
    meta = {"scene_type": "EXPLAIN", "kb_preset": "pan_right", "dur_mult": 1.0}
    m = re.search(r"scene_type:(\w+)\|kb:(\w+)\|dur:([\d.]+)", prompt)
    if m:
        meta["scene_type"] = m.group(1)
        meta["kb_preset"] = m.group(2)
        try: meta["dur_mult"] = float(m.group(3))
        except: pass
    return meta

def build_clip(scene_assets, total_dur, size, fps, out_path, grade=None):
    w, h = size["w"], size["h"]
    n = len(scene_assets)
    
    raw_mults = [m.get("dur_mult", 1.0) for _, m in scene_assets]
    total_mult = sum(raw_mults)
    base_per = total_dur / n
    raw_durs = [base_per * mult for mult in raw_mults]
    scale = total_dur / sum(raw_durs)
    scene_durs = [max(1.0, d * scale) for d in raw_durs]
    
    xdur = 0.5 if n > 1 else 0.0
    seg_files = []
    
    for i, (asset, meta) in enumerate(scene_assets):
        sdur = scene_durs[i]
        seg = OUT / f"_seg_{w}x{h}_{i:02d}.mp4"
        seg_len = sdur + xdur
        
        if asset.suffix.lower() == ".mp4":
            asset_dur = ffprobe_duration(asset)
            vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
            if grade: vf += f",{grade}"
            
            if asset_dur < seg_len:
                cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(asset), "-t", f"{seg_len:.3f}", 
                       "-vf", vf, "-r", str(fps), "-pix_fmt", "yuv420p", "-an", str(seg)]
            else:
                cmd = ["ffmpeg", "-y", "-i", str(asset), "-t", f"{seg_len:.3f}", 
                       "-vf", vf, "-r", str(fps), "-pix_fmt", "yuv420p", "-an", str(seg)]
            run(cmd)
        else:
            frames = max(1, int(seg_len * fps))
            kb = "z='min(1.05+0.0005*on,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,zoompan={kb}:d={frames}:s={w}x{h}:fps={fps}"
            if grade: vf += f",{grade}"
            vf += ",format=yuv420p"
            run(["ffmpeg", "-y", "-loop", "1", "-i", str(asset), "-t", f"{seg_len:.3f}", 
                 "-vf", vf, "-r", str(fps), "-pix_fmt", "yuv420p", str(seg)])
        
        seg_files.append((seg, sdur))

    if n == 1:
        run(["ffmpeg", "-y", "-i", str(seg_files[0][0]), "-t", f"{total_dur:.3f}", "-c", "copy", str(out_path)])
        return out_path

    inputs = []
    for s, _ in seg_files: inputs += ["-i", str(s)]
    fc, prev = [], "0:v"
    offset = 0.0
    for k in range(1, n):
        lbl = f"x{k}" if k < n - 1 else "vout"
        offset += scene_durs[k-1]
        fc.append(f"[{prev}][{k}:v]xfade=transition=fade:duration={xdur}:offset={offset:.3f}[{lbl}]")
        prev = lbl
    
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[vout]", 
         "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", str(out_path)])
    return out_path

# ---------- 4. Finalize ----------

def finalize(video_path, voice_path, captions, music, size, out_path, cfg, hook_text=None, total_dur=None):
    inputs = ["-i", str(video_path), "-i", str(voice_path)]
    if music: inputs += ["-i", str(music)]
    
    filters = []
    vlabel = "0:v"
    
    if captions:
        style = "FontName=Arial,FontSize=20,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2"
        filters.append(f"[{vlabel}]subtitles={captions.name}:force_style='{style}'[vcap]")
        vlabel = "vcap"
    
    if music:
        vol = cfg["video"].get("music_volume", 0.1)
        filters.append(f"[1:a]volume={vol}[bg]")
        filters.append(f"[bg][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=300[duck]")
        filters.append(f"[0:a][duck]amix=inputs=2:duration=first[aout]")
        alabel = "aout"
    else:
        alabel = "1:a"
        
    cmd = ["ffmpeg", "-y", *inputs]
    if filters:
        cmd += ["-filter_complex", ";".join(filters), "-map", f"[{vlabel}]", "-map", f"[{alabel}]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
        
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "24", "-c:a", "aac", "-shortest", str(out_path)]
    run(cmd)
    return out_path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script_json")
    args = ap.parse_args()
    cfg = load_config()
    script = read_json(args.script_json)
    
    voice, dur = make_voice(script["narration"], cfg)
    scene_assets = fetch_images(script, cfg)
    montage = build_clip(scene_assets, dur, cfg["video"]["vertical"], cfg["video"]["fps"], OUT / "montage.mp4")
    finalize(montage, voice, None, None, cfg["video"]["vertical"], OUT / "video_9x16.mp4", cfg, total_dur=dur)
    
    out = {
        "post": script["post"],
        "videos": {"vertical": str(OUT / "video_9x16.mp4")},
        "duration": dur
    }
    write_json("render.json", out)
    log("Render complete.")

if __name__ == "__main__":
    main()
