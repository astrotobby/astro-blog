"""Optional NVIDIA Magpie TTS via NVIDIA NIM / Riva gRPC.

The model returns synthesized PCM and per-word offsets in the same response.
This keeps captions tied to the generated voice instead of estimating timings
from a second transcription model.

Requires NVIDIA_API_KEY in the runner environment. No key or API response is
ever printed. When unavailable or failing, callers should continue to the next
configured speech provider.
"""
from __future__ import annotations

import re
import wave
from pathlib import Path

from common import env, log

DEFAULT_FUNCTION_ID = "877104f7-e885-42b9-8de8-f6e4c6303969"
DEFAULT_VOICE = "Magpie-Multilingual.EN-US.Jason"
LANGUAGE = "en-US"
SAMPLE_RATE_HZ = 22050
MAX_CHARS_PER_REQUEST = 1800
INTER_CHUNK_PAUSE_SECONDS = 0.18


def split_text(text: str, max_chars: int = MAX_CHARS_PER_REQUEST) -> list[str]:
    """Split narration at sentence/word boundaries without dropping punctuation."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for sentence in sentences:
        if len(sentence) <= max_chars:
            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > max_chars:
                flush()
            current = f"{current} {sentence}".strip()
            continue

        flush()
        for word in sentence.split():
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > max_chars:
                flush()
            if len(word) > max_chars:
                # Preserve an unusually long unbroken token rather than truncating it.
                current = word
            else:
                current = f"{current} {word}".strip()
    flush()
    return chunks


def response_word_timings(response, offset_seconds: float = 0.0) -> list[dict]:
    """Convert Riva millisecond offsets into the renderer's seconds-based schema."""
    meta = getattr(response, "meta", None)
    rows = getattr(meta, "words", None) or []
    output = []
    for row in rows:
        word = str(getattr(row, "word", "") or "").strip()
        start_ms = getattr(row, "start_time", None)
        end_ms = getattr(row, "end_time", None)
        if not word or start_ms is None or end_ms is None:
            continue
        start = offset_seconds + max(0.0, float(start_ms) / 1000.0)
        end = offset_seconds + max(0.0, float(end_ms) / 1000.0)
        if end <= start:
            continue
        output.append({"text": word, "start": start, "end": end})
    return output


def synthesize(text: str, output_path: str | Path, cfg=None):
    """Return (WAV path, word timings) or None when this optional provider fails."""
    api_key = env("NVIDIA_API_KEY")
    if not api_key:
        return None

    chunks = split_text(text)
    if not chunks:
        log("NVIDIA Magpie skipped: narration is empty")
        return None

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = int(env("NVIDIA_TTS_SAMPLE_RATE_HZ", str(SAMPLE_RATE_HZ)))
    voice = env("NVIDIA_TTS_VOICE", DEFAULT_VOICE)
    function_id = env("NVIDIA_TTS_FUNCTION_ID", DEFAULT_FUNCTION_ID)
    bytes_per_second = sample_rate * 2  # mono, signed 16-bit PCM
    silence = b"\x00" * int(round(sample_rate * INTER_CHUNK_PAUSE_SECONDS) * 2)

    try:
        import riva.client
        from riva.client.proto.riva_audio_pb2 import AudioEncoding

        auth = riva.client.Auth(
            uri="grpc.nvcf.nvidia.com:443",
            use_ssl=True,
            metadata_args=[
                ("function-id", function_id),
                ("authorization", f"Bearer {api_key}"),
            ],
            options=[
                ("grpc.max_receive_message_length", 64 * 1024 * 1024),
                ("grpc.max_send_message_length", 64 * 1024 * 1024),
            ],
        )
        service = riva.client.SpeechSynthesisService(auth)

        pcm_parts: list[bytes] = []
        word_timings: list[dict] = []
        cursor_seconds = 0.0
        for index, chunk in enumerate(chunks):
            response = service.synthesize(
                chunk,
                voice,
                LANGUAGE,
                sample_rate_hz=sample_rate,
                encoding=AudioEncoding.LINEAR_PCM,
                enable_word_time_offsets=True,
            )
            pcm = bytes(getattr(response, "audio", b"") or b"")
            if len(pcm) < 1024:
                raise RuntimeError(f"NVIDIA Magpie returned empty/short PCM for chunk {index + 1}")

            word_timings.extend(response_word_timings(response, cursor_seconds))
            pcm_parts.append(pcm)
            cursor_seconds += len(pcm) / bytes_per_second

            if index < len(chunks) - 1:
                pcm_parts.append(silence)
                cursor_seconds += len(silence) / bytes_per_second

        with wave.open(str(output_path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(sample_rate)
            audio_file.writeframes(b"".join(pcm_parts))

        if not output_path.exists() or output_path.stat().st_size < 1024:
            raise RuntimeError("NVIDIA Magpie did not create a valid WAV file")
        if not word_timings:
            log("NVIDIA Magpie produced audio but no native word offsets; captions will use ASR fallback")
        else:
            log(f"NVIDIA Magpie returned {len(word_timings)} native word offsets across {len(chunks)} text chunks")
        return output_path, word_timings

    except Exception as exc:
        output_path.unlink(missing_ok=True)
        log(f"NVIDIA Magpie unavailable ({type(exc).__name__}: {str(exc)[:220]}); continuing with existing TTS fallback")
        return None
