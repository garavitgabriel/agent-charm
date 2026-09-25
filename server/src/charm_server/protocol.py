"""Wire constants and frame builders for docs/PROTOCOL.md (proto v0)."""

from __future__ import annotations

import json
from typing import Any

SAMPLE_RATE = 16_000
SAMPLE_FORMAT = "s16le"
CHANNELS = 1
BYTES_PER_SECOND = SAMPLE_RATE * 2
MAX_BINARY_FRAME = 4096
MAX_TEXT_FRAME = 8192
PATH = "/charm"
AUTH_CLOSE_CODE = 4401

MIN_AUDIO_SECONDS = 0.5
TALK_LIMIT_SECONDS = 25.0
# Accept a little past the device's 25 s limit so a late `audio_end{limit}` isn't cut short.
MAX_AUDIO_BYTES = int(BYTES_PER_SECOND * (TALK_LIMIT_SECONDS + 2))
AGENT_TIMEOUT_SECONDS = 120.0

STATES = (
    "idle",
    "listening",
    "transcribing",
    "working",
    "speaking",
    "attention",
    "done",
    "error",
    "offline",
)
ERROR_CODES = (
    "auth",
    "audio_format",
    "too_short",
    "no_speech",
    "agent_timeout",
    "agent_error",
    "busy",
    "stale",
)
EDITION_SECTIONS = ("masthead", "one_thing", "sports", "almanac", "waiting", "wire")
AUDIO_END_REASONS = ("released", "limit", "cancel")
REQUEST_WHATS = ("edition", "pending", "status")


class FrameTooLarge(ValueError):
    pass


def encode(message: dict[str, Any]) -> str:
    """Serialize one server text frame, enforcing the 8192-byte UTF-8 limit."""
    text = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode()) > MAX_TEXT_FRAME:
        raise FrameTooLarge(f"{message.get('type')} frame exceeds {MAX_TEXT_FRAME} bytes")
    return text


def state(value: str, label: str | None = None, agent: str | None = None) -> dict[str, Any]:
    if value not in STATES or value == "offline":
        raise ValueError(f"server cannot send state {value!r}")
    message: dict[str, Any] = {"type": "state", "value": value}
    if label:
        message["label"] = label
    if agent:
        message["agent"] = agent
    return message


def error(code: str, text: str) -> dict[str, Any]:
    if code not in ERROR_CODES:
        raise ValueError(f"unknown error code {code!r}")
    return {"type": "error", "code": code, "text": text}


def chunk_pcm(pcm: bytes, size: int = MAX_BINARY_FRAME) -> list[bytes]:
    """Split PCM into binary frames of at most `size` bytes, never splitting a sample."""
    size -= size % 2
    return [pcm[i : i + size] for i in range(0, len(pcm), size)]
