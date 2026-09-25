"""Text and time helpers that keep card strings inside the contract's limits.

Cards are plain text (no markdown) and every string field has a hard length cap in
`contract/card.schema.json`. The device's default font has no emoji, so they're removed too.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, tzinfo

ELLIPSIS = "…"

_MARKDOWN = re.compile(r"\*\*|__|`|^#+\s*", re.MULTILINE)
_SPACE = re.compile(r"\s+")


def _is_emoji(ch: str) -> bool:
    if ch in "‍︎️":  # joiner and variation selectors
        return True
    cp = ord(ch)
    if cp >= 0x1F000:  # emoji, pictographs, symbols blocks
        return True
    return unicodedata.category(ch) == "So" and cp >= 0x2600


def clean(text: str) -> str:
    """Strip markdown marks and emoji, and collapse whitespace to single spaces."""
    text = _MARKDOWN.sub("", text)
    text = "".join(ch for ch in text if not _is_emoji(ch))
    return _SPACE.sub(" ", text).strip()


def clip(text: str, max_chars: int, max_words: int | None = None) -> str:
    """Clean `text`, then shorten it on a word boundary to fit both limits.

    A shortened result ends with an ellipsis, which counts toward `max_chars`.
    """
    text = clean(text)
    words = text.split(" ") if text else []
    cut = False
    if max_words is not None and len(words) > max_words:
        words = words[:max_words]
        cut = True
    out = " ".join(words)
    if len(out) > max_chars:
        cut = True
        room = max_chars - len(ELLIPSIS)
        head = out[:room]
        # Back up to a word boundary when there is one in the second half.
        space = head.rfind(" ")
        out = head[:space] if space > room // 2 else head
    if cut:
        out = out.rstrip(" ,;:—-.") + ELLIPSIS
    return out


def parse_time(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp that carries an offset. Naive or bad values give None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def iso(moment: datetime) -> str:
    """RFC 3339 with seconds and a numeric offset, as the card schema's date-time wants."""
    return moment.isoformat(timespec="seconds")


def stamp(moment: datetime, tz: tzinfo, now: datetime) -> str:
    """A short local stamp: 'Fri 08:31' within the last week, else '20 Sep 14:02'."""
    local = moment.astimezone(tz)
    age = now - moment
    if abs(age.days) < 6:
        return local.strftime("%a %H:%M")
    return local.strftime("%d %b %H:%M").lstrip("0")


def local_clock(value: object) -> str | None:
    """'2026-09-25T05:45' (a local wall-clock time from a feed) -> '05:45'."""
    if not isinstance(value, str):
        return None
    match = re.search(r"T(\d{2}:\d{2})", value)
    return match.group(1) if match else None
