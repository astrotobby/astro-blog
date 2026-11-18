"""Shared helpers for safe long-form speech synthesis."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


def split_text_chunks(text: str, max_chars: int) -> list[str]:
    """Split normalized narration at sentence/word boundaries under an API cap."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []

    sentences = re.split(r"(?<=[.!?])\\s+", normalized)
    chunks: list[str] = []
    current = ""

    def flush_current() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            candidate = f"{current} {sentence}".strip()
            if len(candidate) <= max_chars:
                current = candidate
            else:
                flush_current()
                current = sentence
            continue

        flush_current()
        piece = ""
        for word in sentence.split():
            # Narration should never contain such long tokens, but handle them safely.
            while len(word) > max_chars:
                if piece:
                    chunks.append(piece)
                    piece = ""
                chunks.append(word[:max_chars])
                word = word[max_chars:]
            candidate = f"{piece} {word}".strip()
            if len(candidate) <= max_chars:
                piece = candidate
            else:
                if piece:
                    chunks.append(piece)
                piece = word
        if piece:
            chunks.append(piece)

    flush_current()
    if any(len(chunk) > max_chars for chunk in chunks):
        raise RuntimeError("Text chunker emitted an oversized chunk")
    return chunks


def audio_duration(path: str | Path) -> float:
    """Return the probed media duration in seconds, or raise on invalid audio."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    try:
        duration = float(result.stdout.strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"ffprobe returned no valid duration for {path}") from exc
    if duration <= 0.25:
        raise RuntimeError(f"Audio chunk is empty or too short: {path}")
    return duration


def concat_audio_files(inputs: list[str | Path], output: str | Path) -> Path:
    """Join same-codec audio parts without re-encoding or changing their sample rate."""
    if not inputs:
        raise ValueError("At least one audio input is required")
    sources = [Path(path).resolve() for path in inputs]
    for source in sources:
        if not source.is_file() or source.stat().st_size < 1024:
            raise RuntimeError(f"Audio chunk is missing or too small: {source}")

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)

    if len(sources) == 1:
        shutil.copyfile(sources[0], destination)
    else:
        list_path = destination.with_name(f"_{destination.stem}_concat.txt")
        rows = []
        for source in sources:
            # These pipeline-generated paths contain no apostrophes.
            rows.append(f"file '{source.as_posix()}'")
        list_path.write_text("\\n".join(rows) + "\\n", encoding="utf-8")
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "concat", "-safe", "0", "-i", str(list_path),
                    "-c:a", "copy", str(destination),
                ],
                capture_output=True,
                text=True,
                timeout=900,
            )
            if result.returncode:
                raise RuntimeError(
                    "FFmpeg could not join speech chunks: "
                    + ((result.stderr or result.stdout or "no details")[-500:])
                )
        finally:
            list_path.unlink(missing_ok=True)

    if not destination.is_file() or destination.stat().st_size < 1024:
        raise RuntimeError("Speech concatenation did not produce a usable audio file")
    return destination
