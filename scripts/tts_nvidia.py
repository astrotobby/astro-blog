"""Optional NVIDIA Magpie TTS adapter for manual, non-production dry-runs.

NVIDIA's hosted Magpie endpoint accepts at most 2,000 normalized characters per
request and returns WAV audio. We stay under that cap, join the WAV parts, and let
the renderer transcribe the joined narration for word-level captions.
"""

import time
from pathlib import Path

import requests

from common import env, log
from tts_helpers import audio_duration, concat_audio_files, split_text_chunks

API = (
    "https://877104f7-e885-42b9-8de8-f6e4c6303969."
    "invocation.api.nvcf.nvidia.com/v1/audio/synthesize"
)
MAX_CHUNK_CHARS = 1800
DEFAULT_VOICE = "Magpie-Multilingual.EN-US.Jason"


def _retry_delay(response, attempt):
    try:
        value = float((response.headers or {}).get("Retry-After", 4 * (attempt + 1)))
        return min(30.0, max(1.0, value))
    except (TypeError, ValueError):
        return 4.0 * (attempt + 1)


def _synthesize_chunk(text, api_key, voice, index, total):
    data = {
        "text": text,
        "language": "en-US",
        "voice": voice,
        "encoding": "LINEAR_PCM",
        "sample_rate_hz": "44100",
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    for attempt in range(3):
        try:
            response = requests.post(API, headers=headers, data=data, timeout=(15, 240))
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    delay = _retry_delay(response, attempt)
                    log(
                        f"NVIDIA Magpie chunk {index}/{total} temporarily unavailable "
                        f"(HTTP {response.status_code}); retrying in {delay:.0f}s"
                    )
                    time.sleep(delay)
                    continue
                log(
                    f"NVIDIA Magpie chunk {index}/{total} failed after retries "
                    f"(HTTP {response.status_code})"
                )
                return None
            if response.status_code != 200:
                log(
                    f"NVIDIA Magpie chunk {index}/{total} rejected "
                    f"(HTTP {response.status_code}): {(response.text or '')[:180]}"
                )
                return None
            audio = response.content or b""
            if len(audio) < 1024 or not audio.startswith(b"RIFF") or b"WAVE" not in audio[:16]:
                raise RuntimeError("NVIDIA Magpie returned an invalid WAV response")
            return audio
        except requests.RequestException as exc:
            if attempt < 2:
                delay = 3.0 * (attempt + 1)
                log(
                    f"NVIDIA Magpie chunk {index}/{total} network error; "
                    f"retrying in {delay:.0f}s ({type(exc).__name__})"
                )
                time.sleep(delay)
                continue
            log(
                f"NVIDIA Magpie chunk {index}/{total} request failed: "
                f"{type(exc).__name__}: {str(exc)[:180]}"
            )
            return None
        except Exception as exc:
            log(
                f"NVIDIA Magpie chunk {index}/{total} failed validation: "
                f"{type(exc).__name__}: {str(exc)[:180]}"
            )
            return None
    return None


def synthesize(text, out_path):
    """Return a joined WAV path or None. Enabled only for manual dry-runs."""
    enabled = (env("NVIDIA_TTS_ENABLED", "false") or "false").strip().lower()
    if enabled not in ("1", "true", "yes"):
        return None
    api_key = env("NVIDIA_API_KEY")
    if not api_key:
        log("NVIDIA_TTS_ENABLED is true but NVIDIA_API_KEY is not set; skipping Magpie TTS")
        return None

    chunks = split_text_chunks(text, MAX_CHUNK_CHARS)
    if not chunks:
        log("NVIDIA Magpie TTS skipped: narration is empty")
        return None

    voice = env("NVIDIA_TTS_VOICE", DEFAULT_VOICE) or DEFAULT_VOICE
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    part_files = []
    log(
        f"NVIDIA Magpie splitting {len(text)} narration characters into "
        f"{len(chunks)} request(s) (max {MAX_CHUNK_CHARS} each)"
    )
    try:
        for index, chunk in enumerate(chunks, 1):
            audio = _synthesize_chunk(chunk, api_key, voice, index, len(chunks))
            if audio is None:
                raise RuntimeError(f"NVIDIA Magpie chunk {index}/{len(chunks)} failed")
            part = output.with_name(f"{output.stem}_part_{index:02d}.wav")
            part.write_bytes(audio)
            duration = audio_duration(part)
            part_files.append(part)
            log(f"NVIDIA Magpie chunk {index}/{len(chunks)}: {duration:.1f}s audio")

        concat_audio_files(part_files, output)
        duration = audio_duration(output)
        log(f"NVIDIA Magpie TTS complete: {duration:.1f}s WAV using {voice}")
        return output
    except Exception as exc:
        output.unlink(missing_ok=True)
        log(f"NVIDIA Magpie TTS unavailable: {type(exc).__name__}: {str(exc)[:220]}")
        return None
    finally:
        for part in part_files:
            part.unlink(missing_ok=True)
