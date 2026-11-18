"""ElevenLabs long-form narration with native per-word timestamps.

The API has a 10,000-character limit for the configured multilingual-v2 model.
Long narration is therefore split at sentence boundaries, synthesized using the
same voice settings, and joined while preserving each chunk's native alignment.
"""

import base64
import time
from pathlib import Path

import requests

from common import env, log
from tts_helpers import audio_duration, concat_audio_files, split_text_chunks

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
MAX_CHUNK_CHARS = 9000
DEFAULTS = {
    "voice_id": "bIHbv24MWmeRgasZH58o",   # Will — young American male narrator
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


def _retry_delay(response, attempt):
    value = (response.headers or {}).get("Retry-After")
    try:
        return min(30.0, max(1.0, float(value))) if value else 4.0 * (attempt + 1)
    except (TypeError, ValueError):
        return 4.0 * (attempt + 1)


def _synthesize_chunk(chunk_text, url, settings, api_key, chunk_number, total_chunks):
    body = {
        "text": chunk_text,
        "model_id": settings["model_id"],
        "voice_settings": {
            "stability": settings["stability"],
            "similarity_boost": settings["similarity_boost"],
            "style": settings["style"],
            "use_speaker_boost": settings["use_speaker_boost"],
            "speed": settings["speed"],
        },
    }
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            response = requests.post(
                url,
                params={"output_format": settings["output_format"]},
                headers=headers,
                json=body,
                timeout=180,
            )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    delay = _retry_delay(response, attempt)
                    log(
                        f"ElevenLabs chunk {chunk_number}/{total_chunks} temporarily "
                        f"unavailable (HTTP {response.status_code}); retrying in {delay:.0f}s"
                    )
                    time.sleep(delay)
                    continue
                log(
                    f"ElevenLabs chunk {chunk_number}/{total_chunks} failed after retries "
                    f"(HTTP {response.status_code})"
                )
                return None
            if response.status_code != 200:
                log(
                    f"ElevenLabs chunk {chunk_number}/{total_chunks} rejected "
                    f"(HTTP {response.status_code}): {(response.text or '')[:180]}"
                )
                return None

            payload = response.json()
            audio = base64.b64decode(payload.get("audio_base64") or "")
            if len(audio) < 1024:
                raise RuntimeError("ElevenLabs returned no usable audio")
            alignment = payload.get("alignment") or payload.get("normalized_alignment") or {}
            return audio, alignment_to_words(alignment)
        except requests.RequestException as exc:
            if attempt < 2:
                delay = 3.0 * (attempt + 1)
                log(
                    f"ElevenLabs chunk {chunk_number}/{total_chunks} network error; "
                    f"retrying in {delay:.0f}s ({type(exc).__name__})"
                )
                time.sleep(delay)
                continue
            log(
                f"ElevenLabs chunk {chunk_number}/{total_chunks} network request failed: "
                f"{type(exc).__name__}: {str(exc)[:180]}"
            )
            return None
        except Exception as exc:
            log(
                f"ElevenLabs chunk {chunk_number}/{total_chunks} could not be decoded: "
                f"{type(exc).__name__}: {str(exc)[:180]}"
            )
            return None
    return None


def synthesize(text, out_path, cfg=None):
    """Return (joined_audio_path, word_timings) or None when any chunk fails."""
    api_key = env("ELEVENLABS_API_KEY")
    if not api_key:
        log("ELEVENLABS_API_KEY not set; skipping ElevenLabs voice")
        return None

    chunks = split_text_chunks(text, MAX_CHUNK_CHARS)
    if not chunks:
        log("ElevenLabs skipped: narration is empty")
        return None

    settings = _settings(cfg)
    url = API.format(voice_id=settings["voice_id"])
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    part_files = []
    all_words = []
    time_offset = 0.0
    log(
        f"ElevenLabs splitting {len(text)} narration characters into "
        f"{len(chunks)} sentence-safe request(s) (max {MAX_CHUNK_CHARS} each)"
    )

    try:
        for index, chunk in enumerate(chunks, 1):
            result = _synthesize_chunk(chunk, url, settings, api_key, index, len(chunks))
            if result is None:
                raise RuntimeError(f"ElevenLabs chunk {index}/{len(chunks)} failed")

            audio, words = result
            part = output.with_name(f"{output.stem}_part_{index:02d}{output.suffix}")
            part.write_bytes(audio)
            part_files.append(part)

            duration = audio_duration(part)
            for word in words:
                all_words.append({
                    "text": word["text"],
                    "start": float(word["start"]) + time_offset,
                    "end": float(word["end"]) + time_offset,
                })
            time_offset += duration
            log(
                f"ElevenLabs chunk {index}/{len(chunks)}: {duration:.1f}s audio, "
                f"{len(words)} aligned words"
            )

        concat_audio_files(part_files, output)
        log(
            f"ElevenLabs voice {settings['voice_id']} ({settings['model_id']}): "
            f"{len(all_words)} aligned words across {len(chunks)} chunk(s)"
        )
        return output, all_words
    except Exception as exc:
        output.unlink(missing_ok=True)
        log(f"ElevenLabs long-form synthesis aborted: {type(exc).__name__}: {str(exc)[:220]}")
        return None
    finally:
        for part in part_files:
            part.unlink(missing_ok=True)
