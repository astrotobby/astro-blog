"""ElevenLabs long-form narration with exact word timings.

The endpoint has a 10,000-character request limit. Long narration is split at
sentence/word boundaries, synthesized chunk by chunk, concatenated losslessly
with FFmpeg, and the native word timings are offset by each chunk's measured
audio duration. This avoids falling back to lower-quality TTS/ASR for episodes
that exceed the endpoint's single-request limit.
"""
from __future__ import annotations

import base64
import re
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from common import env, log

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
DEFAULTS = {
    "voice_id": "bIHbv24MWmeRgasZH58o",
    "model_id": "eleven_multilingual_v2",
    "stability": 0.42,
    "similarity_boost": 0.80,
    "style": 0.30,
    "use_speaker_boost": True,
    "speed": 1.05,
    "output_format": "mp3_44100_128",
}
MAX_CHARS_PER_REQUEST = 9000


def _settings(cfg):
    out = dict(DEFAULTS)
    out.update(((cfg or {}).get("voice") or {}).get("elevenlabs") or {})
    voice_override = env("ELEVENLABS_VOICE_ID")
    if voice_override:
        out["voice_id"] = voice_override
    return out


def split_text(text: str, max_chars: int = MAX_CHARS_PER_REQUEST) -> list[str]:
    """Split normalized narration under the API limit without dropping words.

    Prefer sentence boundaries. A very long sentence is split at word boundaries.
    The returned chunks rejoin to the normalized input with one space.
    """
    normalized = " ".join((text or "").split())
    if not normalized:
        return []
    if max_chars < 32:
        raise ValueError("max_chars must be at least 32")
    if len(normalized) <= max_chars:
        return [normalized]

    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for sentence in sentences:
        if len(sentence) > max_chars:
            flush()
            words = sentence.split()
            part: list[str] = []
            part_chars = 0
            for word in words:
                if len(word) > max_chars:
                    raise ValueError("A single unbroken narration token exceeds the TTS request limit")
                addition = len(word) + (1 if part else 0)
                if part and part_chars + addition > max_chars:
                    chunks.append(" ".join(part))
                    part = []
                    part_chars = 0
                    addition = len(word)
                part.append(word)
                part_chars += addition
            if part:
                current = " ".join(part)
            continue

        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            flush()
        current = f"{current} {sentence}".strip()

    flush()
    if any(len(chunk) > max_chars for chunk in chunks):
        raise RuntimeError("ElevenLabs text chunk exceeded the configured character limit")
    if " ".join(chunks) != normalized:
        raise RuntimeError("ElevenLabs text chunking changed the narration text")
    return chunks


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


def _post_chunk(chunk: str, url: str, settings: dict, api_key: str):
    body = {
        "text": chunk,
        "model_id": settings["model_id"],
        "voice_settings": {
            "stability": settings["stability"],
            "similarity_boost": settings["similarity_boost"],
            "style": settings["style"],
            "use_speaker_boost": settings["use_speaker_boost"],
            "speed": settings["speed"],
        },
    }
    for attempt in range(3):
        try:
            response = requests.post(
                url,
                params={"output_format": settings["output_format"]},
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json=body,
                timeout=180,
            )
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = (response.headers or {}).get("Retry-After")
                try:
                    wait = min(30, max(1, int(float(retry_after)))) if retry_after else 5 * (attempt + 1)
                except (TypeError, ValueError):
                    wait = 5 * (attempt + 1)
                if attempt < 2:
                    log(f"ElevenLabs HTTP {response.status_code}; retrying chunk in {wait}s")
                    time.sleep(wait)
                    continue
                log(f"ElevenLabs HTTP {response.status_code}; chunk retries exhausted")
                return None
            if response.status_code != 200:
                # Do not print the response body: it can echo user narration.
                log(f"ElevenLabs HTTP {response.status_code}; chunk rejected")
                return None
            data = response.json()
            audio = base64.b64decode(data.get("audio_base64") or "")
            if len(audio) < 1024:
                log("ElevenLabs returned no usable audio for a narration chunk")
                return None
            alignment = data.get("alignment") or data.get("normalized_alignment") or {}
            return audio, alignment_to_words(alignment)
        except Exception as exc:  # noqa
            if attempt < 2:
                log(f"ElevenLabs chunk request failed ({type(exc).__name__}); retrying")
                time.sleep(3)
            else:
                log(f"ElevenLabs chunk request failed ({type(exc).__name__}); retries exhausted")
    return None


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    duration = float((result.stdout or "").strip())
    if duration <= 0.25:
        raise RuntimeError("ElevenLabs chunk did not contain valid audio")
    return duration


def _concat_mp3(chunks: list[Path], output_path: Path, work_dir: Path) -> None:
    """Join same-format MP3 chunks without re-encoding or quality loss."""
    manifest = work_dir / "concat.txt"
    lines = []
    for path in chunks:
        # FFmpeg concat demuxer requires single-quote escaping in file paths.
        escaped = path.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
            "-i", str(manifest), "-c", "copy", str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    if not output_path.exists() or output_path.stat().st_size < 1024:
        raise RuntimeError("FFmpeg did not create a valid concatenated ElevenLabs audio file")


def synthesize(text, out_path, cfg=None):
    """Return (MP3 path, complete word timings) or None on provider failure."""
    api_key = env("ELEVENLABS_API_KEY")
    if not api_key:
        log("ELEVENLABS_API_KEY not set; skipping ElevenLabs voice")
        return None

    settings = _settings(cfg)
    chunks = split_text(text)
    if not chunks:
        log("ElevenLabs skipped: narration is empty")
        return None

    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    url = API.format(voice_id=settings["voice_id"])
    chunk_paths: list[Path] = []
    combined_words: list[dict] = []
    cursor_seconds = 0.0

    try:
        with tempfile.TemporaryDirectory(prefix="elevenlabs-", dir=output_path.parent) as temp:
            work_dir = Path(temp)
            for index, chunk in enumerate(chunks, 1):
                result = _post_chunk(chunk, url, settings, api_key)
                if result is None:
                    return None
                audio, words = result
                if not words:
                    # Partial alignment is not safe for karaoke captions. Let the
                    # caller transcribe the complete generated recording instead.
                    log(f"ElevenLabs chunk {index}/{len(chunks)} returned no word alignment")
                    return None

                chunk_path = work_dir / f"chunk-{index:03d}.mp3"
                chunk_path.write_bytes(audio)
                duration = _probe_duration(chunk_path)
                for word in words:
                    combined_words.append({
                        "text": word["text"],
                        "start": cursor_seconds + float(word["start"]),
                        "end": cursor_seconds + float(word["end"]),
                    })
                cursor_seconds += duration
                chunk_paths.append(chunk_path)

            _concat_mp3(chunk_paths, output_path, work_dir)

        log(
            f"ElevenLabs voice {settings['voice_id']} ({settings['model_id']}): "
            f"{len(chunks)} chunks, {len(combined_words)} natively timed words"
        )
        return output_path, combined_words
    except Exception as exc:  # noqa
        output_path.unlink(missing_ok=True)
        log(f"ElevenLabs long-form synthesis failed ({type(exc).__name__}: {str(exc)[:180]})")
        return None
