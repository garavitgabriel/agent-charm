"""The per-book reading session, kept in a gitignored JSON file (`server/.local/books.json`).

One file per server. It remembers which book the owner is reading, the chapter he's on, the last
`TURNS_PER_BOOK` questions and answers for each book, and the speech toggle, so reading mode
survives reconnects and server restarts. Switching books switches the context: each book keeps
its own chapter and turns.

The file holds the owner's own questions about his books, so it lives under `.local/` (gitignored),
never in the repo.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from charm_notes import Book

log = logging.getLogger(__name__)

TURNS_PER_BOOK = 8  # question/answer pairs kept per book
STATE_VERSION = 1


def book_key(title: str) -> str:
    """Case-, accent- and punctuation-insensitive: "Cien años" and "cien anos" are one book."""
    text = unicodedata.normalize("NFKD", title)
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^\w]+", " ", text).strip()


@dataclass
class BookEntry:
    title: str
    author: str | None = None
    chapter: str | None = None
    turns: list[dict[str, str]] = field(default_factory=list)  # {"q", "a", "at"}

    @property
    def book(self) -> Book:
        return Book(self.title, self.author, self.chapter)

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "author": self.author,
            "chapter": self.chapter,
            "turns": self.turns,
        }

    @classmethod
    def from_json(cls, raw: Any) -> BookEntry | None:
        if not isinstance(raw, dict) or not isinstance(raw.get("title"), str) or not raw["title"]:
            return None
        author = raw.get("author")
        chapter = raw.get("chapter")
        turns = [
            {"q": t["q"], "a": t["a"], "at": str(t.get("at", ""))}
            for t in raw.get("turns") or []
            if isinstance(t, dict) and isinstance(t.get("q"), str) and isinstance(t.get("a"), str)
        ]
        return cls(
            title=raw["title"],
            author=author if isinstance(author, str) and author else None,
            chapter=chapter if isinstance(chapter, str) and chapter else None,
            turns=turns[-TURNS_PER_BOOK:],
        )


class BookStore:
    """Reading state shared by every connection. `path=None` keeps it in memory only."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.books: dict[str, BookEntry] = {}
        self.current: str | None = None  # the most recent book, even after leaving reading
        self.active = False  # in reading mode right now
        self.speech: str | None = None  # "on" | "off" when toggled; None = the mode's default
        self._load()

    @classmethod
    def memory(cls) -> BookStore:
        return cls(None)

    # --- reading state -----------------------------------------------------------------------

    @property
    def reading(self) -> BookEntry | None:
        """The book being read, or None outside reading mode."""
        if not self.active or self.current is None:
            return None
        return self.books.get(self.current)

    @property
    def last_book(self) -> BookEntry | None:
        return self.books.get(self.current) if self.current else None

    @property
    def mode(self) -> str:
        return "reading" if self.reading is not None else "default"

    @property
    def speech_value(self) -> str:
        """The effective speech setting: reading defaults to off, everything else to on."""
        if self.speech in ("on", "off"):
            return self.speech
        return "off" if self.mode == "reading" else "on"

    def enter(self, title: str, author: str | None = None, chapter: str | None = None) -> Book:
        """Start (or return to) a book. A known book keeps its author/chapter unless given."""
        key = book_key(title)
        entry = self.books.get(key)
        if entry is None:
            entry = BookEntry(title=title, author=author, chapter=chapter)
            self.books[key] = entry
        else:
            entry.title = title
            entry.author = author or entry.author
            entry.chapter = chapter or entry.chapter
        was_reading = self.mode == "reading"
        self.current = key
        self.active = True
        if not was_reading:
            self.speech = None  # entering reading: back to its quiet default
        self._save()
        return entry.book

    def resume(self) -> Book | None:
        """Re-enter reading with the last book (a device `setting{mode:"reading"}`)."""
        entry = self.last_book
        if entry is None:
            return None
        if not self.active:
            self.active = True
            self.speech = None
            self._save()
        return entry.book

    def set_chapter(self, chapter: str) -> Book | None:
        entry = self.reading
        if entry is None:
            return None
        entry.chapter = chapter
        self._save()
        return entry.book

    def leave(self) -> None:
        if self.active:
            self.active = False
            self.speech = None  # back to the default mode's speech (on)
            self._save()

    def set_speech(self, value: str) -> None:
        if value not in ("on", "off"):
            raise ValueError(f"speech must be on or off, not {value!r}")
        self.speech = value
        self._save()

    def turns(self) -> list[dict[str, str]]:
        entry = self.reading
        return list(entry.turns) if entry else []

    def add_turn(self, title: str, question: str, answer: str) -> None:
        """Remember a Q&A for `title` (the book the question was asked about)."""
        entry = self.books.get(book_key(title))
        if entry is None:
            return
        at = datetime.now(UTC).isoformat(timespec="seconds")
        entry.turns.append({"q": question, "a": answer, "at": at})
        entry.turns = entry.turns[-TURNS_PER_BOOK:]
        self._save()

    # --- persistence -------------------------------------------------------------------------

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text())
            if not isinstance(raw, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as exc:
            log.warning("books file %s unreadable (%s); starting fresh", self.path, exc)
            return
        for key, value in (raw.get("books") or {}).items():
            entry = BookEntry.from_json(value)
            if entry is not None:
                self.books[book_key(entry.title) or str(key)] = entry
        current = raw.get("current")
        self.current = current if isinstance(current, str) and current in self.books else None
        self.active = bool(raw.get("active")) and self.current is not None
        speech = raw.get("speech")
        self.speech = speech if speech in ("on", "off") else None

    def _save(self) -> None:
        if self.path is None:
            return
        state = {
            "version": STATE_VERSION,
            "current": self.current,
            "active": self.active,
            "speech": self.speech,
            "books": {key: entry.to_json() for key, entry in self.books.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename, so a crash mid-write never leaves a half file.
        fd, tmp = tempfile.mkstemp(prefix=".books-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
