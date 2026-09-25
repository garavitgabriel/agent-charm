"""Cards: schema validation, the edition/pending sources, and Dex's answer card."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker

from .protocol import EDITION_SECTIONS

log = logging.getLogger(__name__)

Card = dict[str, Any]

ANSWER_MAX_WORDS = 60
BODY_MAX_CHARS = 420
TITLE_MAX_CHARS = 60
SAY_MAX_SENTENCES = 2
SAY_MAX_CHARS = 320
PENDING_KINDS = ("decision", "money", "tracker", "job", "notice")

FOOTER_TRUNCATED = {
    "en": "Shortened. Ask Dex for the rest.",
    "es": "Resumida. Pídele a Dex el resto.",
}


class CardInvalid(ValueError):
    pass


_formats = FormatChecker()


@_formats.checks("date-time", raises=ValueError)
def _is_datetime(value: object) -> bool:
    # RFC 3339 needs a time and an offset; fromisoformat alone accepts bare dates.
    if not isinstance(value, str):
        return True
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return "T" in value.upper() and parsed.tzinfo is not None


class CardValidator:
    def __init__(self, schema_path: Path) -> None:
        schema = json.loads(schema_path.read_text())
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema, format_checker=_formats)

    def errors(self, card: Card) -> list[str]:
        return [
            f"{'/'.join(str(p) for p in e.absolute_path) or '<card>'}: {e.message}"
            for e in self._validator.iter_errors(card)
        ]

    def check(self, card: Card) -> Card:
        problems = self.errors(card)
        if problems:
            raise CardInvalid("; ".join(problems))
        return card


@dataclass
class CardSet:
    edition: list[Card]
    pending: list[Card]
    rejected: list[str]


def load_cards(cards_dir: Path, validator: CardValidator) -> CardSet:
    """Read `*.json` cards from `cards_dir`. Invalid cards are dropped and reported, never sent."""
    edition: list[Card] = []
    pending: list[Card] = []
    rejected: list[str] = []
    paths = sorted(cards_dir.glob("*.json")) if cards_dir.is_dir() else []
    for path in paths:
        try:
            card = validator.check(json.loads(path.read_text()))
        except (ValueError, CardInvalid) as exc:
            rejected.append(f"{path.name}: {exc}")
            log.warning("card %s rejected: %s", path.name, exc)
            continue
        if card["kind"] == "edition":
            edition.append(card)
        elif card["kind"] in PENDING_KINDS:
            pending.append(card)
    order = {section: i for i, section in enumerate(EDITION_SECTIONS)}
    edition.sort(key=lambda c: order[c["data"]["section"]])
    return CardSet(edition=edition, pending=pending, rejected=rejected)


def now_iso(tz: str) -> str:
    return datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds")


def notice_card(card_id: str, title: str, body: str, tz: str, stale: bool = False) -> Card:
    card: Card = {
        "id": card_id[:64],
        "kind": "notice",
        "title": title[:TITLE_MAX_CHARS],
        "body": body[:BODY_MAX_CHARS],
        "source": "system",
        "created_at": now_iso(tz),
    }
    if stale:
        card["stale"] = True
    return card


# --- Dex's reply -> say + answer card ---------------------------------------------------------

_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_MARKS = re.compile(r"(\*\*|__|\*|`+|~~)")
_MD_LINE_PREFIX = re.compile(r"^\s*(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)", re.MULTILINE)
# A sentence ends at . ! ? or … (plus closing quotes/brackets) followed by whitespace, unless the
# next word starts lowercase, or the period closes an abbreviation or an initial ("Dr.", "EE.",
# "J."). Decimals ("3.5") never match: there's no whitespace after their period.
_BOUNDARY = re.compile("[.!?\u2026]+[\"'\u201d\u2019)\u00bb]*\\s+")
_ABBREVIATIONS_EN = (
    "mr mrs ms dr prof jr sr st vs e.g i.e a.m p.m approx dept inc ltd co mt ft u.s u.k"
)
_ABBREVIATIONS_ES = "sra srta dra ud uds ee uu pág págs aprox núm av ej lic ing dto"
ABBREVIATIONS = frozenset(f"{_ABBREVIATIONS_EN} {_ABBREVIATIONS_ES}".split())


def plain_text(text: str) -> str:
    """Strip markdown so the card and the voice get plain text."""
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_LINE_PREFIX.sub("", text)
    text = _MD_MARKS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_boundary(text: str, match: re.Match[str]) -> bool:
    after = text[match.end() : match.end() + 1]
    if after[:1].islower():
        return False  # "the U.S. economy", "etc. and so on", "3 p.m. today"
    punct = match.group().rstrip()
    if punct.rstrip("\"'\u201d\u2019)\u00bb") != ".":
        return True  # ! ? … and "..." always end a sentence
    before = text[: match.start()].rsplit(None, 1)
    word = before[-1].lstrip("([{\"'\u201c\u2018\u00ab¿¡") if before else ""
    if len(word) == 1 and word.isalpha() and word.isupper():
        return False  # an initial: "J. R. R. Tolkien"
    return word.lower() not in ABBREVIATIONS


def sentences(text: str, final: bool = True) -> list[str]:
    """Split plain text into sentences (EN/ES aware: abbreviations, initials, decimals).

    With `final=False` the text is still streaming in, so the last piece (which may be half a
    sentence, or a full stop whose next word hasn't arrived) is left out.
    """
    out: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        if match.end() >= len(text):
            break  # nothing after the whitespace yet: can't tell whether it's a boundary
        if _is_boundary(text, match):
            out.append(text[start : match.end()].strip())
            start = match.end()
    if final:
        out.append(text[start:].strip())
    return [s for s in out if s]


class SpeechSplitter:
    """Turns a streamed answer into the spoken sentences as soon as each one is complete.

    Yields at most `SAY_MAX_SENTENCES` sentences within `SAY_MAX_CHARS`; joined, they equal
    `say_text(full_answer)`.
    """

    def __init__(self) -> None:
        self._raw = ""
        self._spoken: list[str] = []
        self._full = False

    def feed(self, text: str) -> list[str]:
        self._raw += text
        return self._take(final=False)

    def finish(self) -> list[str]:
        return self._take(final=True)

    def _take(self, final: bool) -> list[str]:
        if self._full:
            return []
        found = sentences(plain_text(self._raw), final=final)
        out: list[str] = []
        for sentence in found[len(self._spoken) : SAY_MAX_SENTENCES]:
            spoken = " ".join(self._spoken)
            joined = f"{spoken} {sentence}" if spoken else sentence
            clipped = _clip_chars(joined, SAY_MAX_CHARS)
            out.append(clipped[len(spoken) + 1 :] if spoken else clipped)
            self._spoken.append(sentence)
            if clipped != joined or len(self._spoken) >= SAY_MAX_SENTENCES:
                self._full = True
                break
        return out


def _clip_chars(text: str, limit: int, force: bool = False) -> str:
    """Clip to `limit` chars at a word boundary, ending in an ellipsis. `force` always marks it."""
    if len(text) <= limit and not force:
        return text
    cut = text if len(text) < limit else text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",;: ") + "…"


def say_text(reply: str) -> str:
    """The spoken part: at most two sentences."""
    text = plain_text(reply)
    return _clip_chars(" ".join(sentences(text)[:SAY_MAX_SENTENCES]), SAY_MAX_CHARS)


def title_from_question(question: str) -> str:
    text = plain_text(question) or "Dex"
    text = text[0].upper() + text[1:]
    return _clip_chars(text, TITLE_MAX_CHARS)


def new_answer_id() -> str:
    return f"ans-{uuid.uuid4().hex[:10]}"


def answer_card(
    question: str, reply: str, language: str, tz: str, card_id: str | None = None
) -> Card:
    """Body at most 60 words (and 420 chars); a footer says when it was shortened."""
    text = plain_text(reply)
    words = text.split()
    body = " ".join(words[:ANSWER_MAX_WORDS])
    truncated = len(words) > ANSWER_MAX_WORDS or len(body) > BODY_MAX_CHARS
    if truncated:
        body = _clip_chars(body, BODY_MAX_CHARS, force=True)
    card: Card = {
        "id": card_id or new_answer_id(),
        "kind": "answer",
        "title": title_from_question(question),
        "body": body,
        "source": "dex",
        "created_at": now_iso(tz),
    }
    if truncated:
        card["footer"] = FOOTER_TRUNCATED.get(language, FOOTER_TRUNCATED["en"])
    return card
