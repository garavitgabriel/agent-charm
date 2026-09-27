"""Reading notes store: the contract between the charm server and wherever notes persist.

CONTRACT (chief-owned): `Book`, `Note`, `SaveReceipt`, `NoteStore` and `FakeNoteStore` keep these
names and signatures. The notes batch adds real stores in other modules; the server batch depends
only on what is defined here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

__all__ = ["Book", "FakeNoteStore", "Note", "NoteStore", "SaveReceipt"]


@dataclass(frozen=True)
class Book:
    title: str
    author: str | None = None
    chapter: str | None = None


@dataclass(frozen=True)
class Note:
    text: str  # the owner's exact words, never paraphrased
    captured_at: datetime  # timezone-aware
    language: str  # "en" | "es" | ...
    book: Book | None = None


@dataclass(frozen=True)
class SaveReceipt:
    ok: bool  # True only when the store confirmed persistence
    where: str | None = None  # e.g. the vault path the store reported
    error: str | None = None  # human-readable reason when ok is False


class NoteStore(Protocol):
    async def save(self, note: Note) -> SaveReceipt: ...


@dataclass
class FakeNoteStore:
    """In-memory store for tests. Set `fail` to simulate an unconfirmed save."""

    fail: str | None = None
    saved: list[Note] = field(default_factory=list)

    async def save(self, note: Note) -> SaveReceipt:
        if self.fail is not None:
            return SaveReceipt(ok=False, error=self.fail)
        self.saved.append(note)
        return SaveReceipt(ok=True, where=f"fake/{len(self.saved)}")
