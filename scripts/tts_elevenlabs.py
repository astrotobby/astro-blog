"""ElevenLabs narration with exact word timings.

synthesize(text, out_path, cfg) -> (out_path, words) on success, else None.

Uses the /with-timestamps endpoint, so the same request returns the audio AND a
per-character alignment. That alignment becomes word-level timings for the
captions and scene cuts, which is both faster and more accurate than running
Whisper over the rendered voice afterwards.

Needs the ELEVENLABS_API_KEY secret. Any failure returns None so the caller can
fall back to the free voice and the pipeline never breaks over TTS.
"""
import base64
import time

import requests

from common import env, log

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
DEFAULTS = {
    "voice_id": "nPczCjzI2devNBz1zQrb",   # "Brian" — deep, confident narrator
    "model_id": "eleven_multilingual_v2",
    "stability": 0.42,
    "similarity_boost": 0.80,
    "style": 0.30,
    "use_speaker_boost": True,
    "speed": 1.05,
    "output_format": "mp3_44100_128",
}


def _settings(cfg):
    out = dict(DEFAULTS)
    out.update(((cfg or {}).get("voice") or {}).get("elevenlabs") or {})
    voice_override = env("ELEVENLABS_VOICE_ID")
    if voice_override:
        out["voice_id"] = voice_override
    return out


def alignment_to_words(alignment):
    """Group ElevenLabs character timings into [{text, start, end}] words."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    words, current, w_start, w_end = [], "", None, None
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if current:
                words.append({"text": current, "start": float(w_start), "end": float(w_end)})
            current, w_start, w_end = "", None, None
            continue
        if not current:
            w_start = st
        current += ch
        w_end = en
    if current:
        words.append({"text": current, "start": float(w_start), "end": float(w_end)})
    return words


def synthesize(text, out_path, cfg=None):
    api_key = env("ELEVENLABS_API_KEY")
    if not api_key:
        log("ELEVENLABS_API_KEY not set; skipping ElevenLabs voice")
        return None
    s = _settings(cfg)
    body = {
        "text": text,
        "model_id": s["model_id"],
        "voice_settings": {
            "stability": s["stability"],
            "similarity_boost": s["similarity_boost"],
            "style": s["style"],
            "use_speaker_boost": s["use_speaker_boost"],
            "speed": s["speed"],
        },
    }
    url = API.format(voice_id=s["voice_id"])
    for attempt in range(3):
        try:
            r = requests.post(url, params={"output_format": s["output_format"]},
                              headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                              json=body, timeout=180)
            if r.status_code == 429 or r.status_code >= 500:
                wait = int(r.headers.get("Retry-After", 5 * (attempt + 1)))
                log(f"ElevenLabs HTTP {r.status_code}; retrying in {wait}s")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                log(f"ElevenLabs HTTP {r.status_code}: {r.text[:200]}")
                return None
            data = r.json()
            audio = base64.b64decode(data.get("audio_base64") or "")
            if len(audio) < 1024:
                log("ElevenLabs returned no audio")
                return None
            with open(out_path, "wb") as fh:
                fh.write(audio)
            words = alignment_to_words(data.get("alignment") or data.get("normalized_alignment") or {})
            log(f"ElevenLabs voice {s['voice_id']} ({s['model_id']}): {len(words)} timed words")
            return out_path, words
        except Exception as exc:  # noqa
            log(f"ElevenLabs request failed ({exc})")
            time.sleep(3)
    return None
