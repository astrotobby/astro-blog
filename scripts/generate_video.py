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

from common import OUT, ROOT, load_config, log, read_json, write_json


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
def fetch_images(script, cfg):
    vz = cfg["visuals"]
    paths = []
    for i, prompt in enumerate(script["scene_prompts"]):
        enc = urllib.parse.quote(prompt, safe="")
        url = (f"https://image.pollinations.ai/prompt/{enc}"
               f"?width={vz['width']}&height={vz['height']}"
               f"&model={vz['model']}&seed={1000 + i}&nologo=true")
        dst = OUT / f"scene_{i:02d}.jpg"
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                dst.write_bytes(r.content)
                break
            except Exception as e:  # noqa
                log(f"image {i} retry {attempt+1}: {e}")
        paths.append(dst)
        log(f"scene {i} -> {dst.name}")
    return paths


# ---------- 3. captions ----------
def make_captions(voice_path):
    try:
        from faster_whisper import WhisperModel
    except Exception as e:  # noqa
        log(f"whisper unavailable, skipping captions: {e}")
        return None
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(voice_path), word_timestamps=True)
    srt = OUT / "captions.srt"
    idx = 1
    with open(srt, "w", encoding="utf-8") as f:
        for seg in segments:
            # break long segments into ~5-word caption chunks for Reels readability
            words = list(seg.words or [])
            if not words:
                continue
            chunk = []
            for w in words:
                chunk.append(w)
                if len(chunk) >= 5:
                    _write_srt(f, idx, chunk[0].start, chunk[-1].end,
                               " ".join(c.word.strip() for c in chunk))
                    idx += 1
                    chunk = []
            if chunk:
                _write_srt(f, idx, chunk[0].start, chunk[-1].end,
                           " ".join(c.word.strip() for c in chunk))
                idx += 1
    log(f"captions -> {srt.name}")
    return srt


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
        # cover-scale then slow ken-burns zoom
        vf = (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
              f"crop={w*2}:{h*2},"
              f"zoompan=z='min(zoom+0.0012,1.18)':d={frames}:s={w}x{h}:fps={fps},"
              f"format=yuv420p")
        run(["ffmpeg", "-y", "-loop", "1", "-i", str(img), "-t", f"{per:.3f}",
             "-vf", vf, "-r", str(fps), str(seg)])
        seg_files.append(seg)
    # concat
    listf = OUT / f"_list_{w}x{h}.txt"
    listf.write_text("".join(f"file '{s.name}'\n" for s in seg_files), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf.name,
         "-c", "copy", str(out_path.name)], cwd=OUT)
    return out_path


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
        style = ("FontName=Arial,FontSize=14,Bold=1,PrimaryColour=&H00FFFFFF,"
                 "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
                 "Alignment=2,MarginV=120")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script_json")
    args = ap.parse_args()
    cfg = load_config()
    script = read_json(args.script_json)

    voice, dur = make_voice(script, cfg)
    images = fetch_images(script, cfg)
    captions = make_captions(voice) if cfg["video"].get("captions") else None
    music = pick_music(cfg)
    if music:
        log(f"music bed: {music.name}")

    fps = cfg["video"]["fps"]
    results = {}

    # vertical (Reels/Shorts/TikTok)
    vsize = cfg["video"]["vertical"]
    vsilent = build_clip(images, dur, vsize, fps, OUT / "silent_9x16.mp4")
    vout = finalize(vsilent, voice, captions, music, vsize, OUT / "video_9x16.mp4", cfg)
    results["vertical"] = str(vout)

    # horizontal (YouTube main)
    if cfg["video"].get("make_horizontal"):
        hsize = cfg["video"]["horizontal"]
        hsilent = build_clip(images, dur, hsize, fps, OUT / "silent_16x9.mp4")
        hout = finalize(hsilent, voice, captions, music, hsize, OUT / "video_16x9.mp4", cfg)
        results["horizontal"] = str(hout)

    out = {
        "post": script["post"],
        "platform": script["platform"],
        "duration": dur,
        "videos": results,
    }
    log(f"rendered: {list(results.keys())}")
    write_json("render.json", out)


if __name__ == "__main__":
    main()
