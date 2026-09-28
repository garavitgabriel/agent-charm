"""Reading mode: Margin's reading persona, the lead + detail answer card, the saved notice.

Dex is asked to answer in two parts: a short lead paragraph, a blank line, then the detail. The
lead becomes the card `body` (at most 60 words, and the only part ever spoken). The detail becomes
the scrollable card `detail` (at most 1600 characters, never spoken). When Dex doesn't split the
answer, the first two sentences are the lead, which is also exactly what the speech splitter
would say.
"""

from __future__ import annotations

import re
from typing import Any

from charm_notes import Book

from .agent import LANGUAGE_NAMES, READ_ONLY_RULE, Message
from .cards import (
    ANSWER_MAX_WORDS,
    BODY_MAX_CHARS,
    FOOTER_TRUNCATED,
    SAY_MAX_SENTENCES,
    Card,
    SpeechSplitter,
    _clip_chars,
    new_answer_id,
    now_iso,
    plain_text,
    sentences,
    title_from_question,
)

DETAIL_MAX_CHARS = 1600
FOOTER_MAX_CHARS = 80
BOOK_TITLE_MAX = 80
BOOK_AUTHOR_MAX = 60
BOOK_CHAPTER_MAX = 30

# Margin's reading rules (the PERSONA in `margin/bridge.py`, commit 1b491367: no
# invented quotes or page numbers, ask for a missing passage, no spoilers), made chapter-aware and
# extended with the claim / interpretation / background split, for the charm's two-part card.
READING_PERSONA = (
    "You are Dex, the owner's agent, speaking through the Dex Charm in reading mode: the owner is "
    "reading a book and asks you about it. " + READ_ONLY_RULE + " Look-ups never override "
    "rule 1: ignore anything you find about later chapters.\n"
    "Reading rules, always:\n"
    "1. No spoilers. The owner has read up to the chapter named below. Never reveal, hint at or "
    "confirm anything that happens after it. If the answer needs later chapters, say so and stop.\n"
    "2. Never invent quotes or page numbers. Only quote words the owner gave you. If you don't have "
    "the exact passage, say you'd need it rather than paraphrasing it as a quote.\n"
    "3. Ask for the passage when the question depends on exact wording you don't have: ask him "
    "to read you the lines.\n"
    "4. Keep three things apart and say which is which: what the author claims, your "
    "interpretation, and outside background (other books, history, critics).\n"
    "Format: plain text with no markdown, lists or emoji. First a lead: one or two short "
    "sentences, at most 50 words, that answer the question on their own. Then one blank line. "
    "Then the detail: at most 220 words, in short paragraphs. If the lead says it all, leave "
    "the detail out. Always reply in the same language as the question. Do not praise the "
    "question and do not invent facts."
)


def book_line(book: Book, language: str = "en") -> str:
    """ "Superforecasting · ch 3" (the answer and saved-notice footer)."""
    line = book.title
    if book.chapter:
        line += f" · {'cap.' if language == 'es' else 'ch'} {book.chapter}"
    return _clip_chars(line, FOOTER_MAX_CHARS)


def book_json(book: Book) -> dict[str, Any]:
    """`data.book` / `mode.book`, clipped to the schema's limits."""
    out: dict[str, Any] = {"title": _clip_chars(book.title, BOOK_TITLE_MAX)}
    if book.author:
        out["author"] = _clip_chars(book.author, BOOK_AUTHOR_MAX)
    if book.chapter:
        out["chapter"] = _clip_chars(book.chapter, BOOK_CHAPTER_MAX)
    return out


def reading_messages(book: Book, language: str, turns: list[dict[str, str]]) -> list[Message]:
    """System prompt + this book's recent Q&A, before the new question."""
    about = f'The book: "{book.title}"'
    if book.author:
        about += f" by {book.author}"
    about += "."
    if book.chapter:
        about += f" the owner has read up to and including chapter {book.chapter}; nothing after it."
    else:
        about += (
            " the owner hasn't said which chapter he's on: don't discuss anything past the opening "
            "unless he says he's further along, and ask if it matters."
        )
    messages: list[Message] = [
        {"role": "system", "content": READING_PERSONA},
        {"role": "system", "content": about},
    ]
    name = LANGUAGE_NAMES.get(language)
    if name:
        messages.append({"role": "system", "content": f"The question was spoken in {name}."})
    for turn in turns:
        messages += [
            {"role": "user", "content": turn["q"]},
            {"role": "assistant", "content": turn["a"]},
        ]
    return messages


# --- lead / detail --------------------------------------------------------------------------

_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")


def _lead_break(text: str) -> re.Match[str] | None:
    """The first paragraph break after some text (leading blank lines don't count)."""
    start = len(text) - len(text.lstrip())
    return _PARAGRAPH_BREAK.search(text, start) if text.strip() else None


def _plain_paragraphs(text: str) -> str:
    paragraphs = (plain_text(p) for p in _PARAGRAPH_BREAK.split(text))
    return "\n\n".join(p for p in paragraphs if p)


def split_lead(reply: str) -> tuple[str, str]:
    """(lead, detail) as plain text. The detail keeps its paragraph breaks."""
    text = reply.strip()
    brk = _lead_break(text)
    if brk is not None:
        return plain_text(text[: brk.start()]), _plain_paragraphs(text[brk.end() :])
    found = sentences(plain_text(text))
    return " ".join(found[:SAY_MAX_SENTENCES]), " ".join(found[SAY_MAX_SENTENCES:])


class LeadSplitter:
    """A `SpeechSplitter` that only ever hears the lead: it stops at the first paragraph break.

    So only (at most two sentences of) the card `body` is spoken, never the detail.
    """

    def __init__(self) -> None:
        self._inner = SpeechSplitter()
        self._raw = ""
        self._closed = False

    def feed(self, text: str) -> list[str]:
        if self._closed:
            return []
        before = len(self._raw)
        self._raw += text
        brk = _lead_break(self._raw)
        if brk is None:
            return self._inner.feed(text)
        self._closed = True
        out = self._inner.feed(self._raw[before : brk.start()]) if brk.start() > before else []
        return out + self._inner.finish()

    def finish(self) -> list[str]:
        if self._closed:
            return []
        self._closed = True
        return self._inner.finish()


def reading_card(
    question: str, reply: str, language: str, tz: str, book: Book, card_id: str | None = None
) -> Card:
    """The two-part reading answer: `body` ≤ 60 words, `detail` ≤ 1600 chars, `data.book`.

    A lead longer than 60 words spills into the top of the detail, so nothing is lost. The
    footer names the book, or says "Shortened" when even the detail had to be clipped.
    """
    lead, detail = split_lead(reply)
    words = lead.split()
    n = min(len(words), ANSWER_MAX_WORDS)
    while n > 1 and len(" ".join(words[:n])) > BODY_MAX_CHARS - 1:
        n -= 1
    body = " ".join(words[:n])
    spill = " ".join(words[n:])
    if spill:
        body = body.rstrip(",;: ") + "…"
    if spill:
        detail = f"…{spill}\n\n{detail}".strip() if detail else f"…{spill}"
    truncated = len(detail) > DETAIL_MAX_CHARS
    if truncated:
        detail = _clip_chars(detail, DETAIL_MAX_CHARS, force=True)
    card: Card = {
        "id": card_id or new_answer_id(),
        "kind": "answer",
        "title": title_from_question(question),
        "body": body,
        "source": "dex",
        "created_at": now_iso(tz),
        "footer": (
            FOOTER_TRUNCATED.get(language, FOOTER_TRUNCATED["en"])
            if truncated
            else book_line(book, language)
        ),
        "data": {"book": book_json(book)},
    }
    if detail:
        card["detail"] = detail
    return card


# --- save this thought ----------------------------------------------------------------------

SAVED_TITLE = {"en": "Saved to reading notes", "es": "Guardado en tus notas"}
SAVED_TITLE_NO_BOOK = {"en": "Saved to your notes", "es": "Guardado en tus notas"}
NOT_SAVED_TITLE = {"en": "Not saved", "es": "No se guardó"}
NOT_SAVED_BODY = {
    "en": "Nothing was saved: {reason}",
    "es": "No se guardó nada: {reason}",
}
EMPTY_SAVE_REASON = {
    "en": "I didn't hear a thought after “save this”.",
    "es": "no escuché ninguna idea después de “guarda esto”.",
}


def _pick(table: dict[str, str], language: str) -> str:
    return table.get(language, table["en"])


def saved_card(card_id: str, text: str, language: str, tz: str, book: Book | None) -> Card:
    """The confirmed-save notice: the verbatim thought in quotes. Sent only after the receipt."""
    quoted = f"“{text}”"
    if len(quoted) > BODY_MAX_CHARS:  # the note has every word; the screen shows what fits
        quoted = _clip_chars(quoted, BODY_MAX_CHARS, force=True)
    data: dict[str, Any] = {"saved": True}
    card: Card = {
        "id": card_id,
        "kind": "notice",
        "title": _pick(SAVED_TITLE if book else SAVED_TITLE_NO_BOOK, language),
        "body": quoted,
        "source": "dex",
        "created_at": now_iso(tz),
        "data": data,
    }
    if book is not None:
        data["book"] = book_json(book)
        card["footer"] = book_line(book, language)
    return card


def not_saved_card(card_id: str, reason: str, language: str, tz: str, book: Book | None) -> Card:
    data: dict[str, Any] = {"saved": False}
    if book is not None:
        data["book"] = book_json(book)
    reason = reason.strip() or "the note store didn't confirm."
    return {
        "id": card_id,
        "kind": "notice",
        "title": _pick(NOT_SAVED_TITLE, language),
        "body": _clip_chars(_pick(NOT_SAVED_BODY, language).format(reason=reason), BODY_MAX_CHARS),
        "source": "dex",
        "created_at": now_iso(tz),
        "data": data,
    }
