"""Which note store "save this" goes to: `CHARM_NOTES=file|osapi|fake|off` (default `file`).

- `file`: `FileNoteStore`, one new Markdown file per note in `CHARM_NOTES_DIR` (default
  `server/.local/notes/`, gitignored). Saved means written and flushed to disk.
- `osapi`: `charm_notes.osapi.OsApiStore`, the OS knowledge service's `POST /submit` (vault inbox
  only). It's imported lazily on the first save. Until that module exists (the notes batch), or
  while it can't be set up, every save fails honestly with the reason. Never a fake success.
- `fake`: `charm_notes.FakeNoteStore`, in memory. For tests and live checks without vault writes.
- `off`: saving is disabled; every save fails and says so.

The server never writes the vault itself: only a `NoteStore` persists notes, and only its
`SaveReceipt(ok=True)` counts as saved.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
from pathlib import Path

from charm_notes import FakeNoteStore, Note, NoteStore, SaveReceipt

log = logging.getLogger(__name__)

NOTES_BACKENDS = ("file", "osapi", "fake", "off")
NOT_INSTALLED = "note store not installed"


class UnavailableStore:
    """A store that can't save. Every receipt says why."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def save(self, note: Note) -> SaveReceipt:
        return SaveReceipt(ok=False, error=self.reason)


class LazyOsApiStore:
    """Imports and builds `charm_notes.osapi.OsApiStore` on the first save.

    A missing module means "note store not installed". A store that fails to build (no config
    yet, say) fails this save with its reason and is tried again on the next one.
    """

    MODULE = "charm_notes.osapi"

    def __init__(self) -> None:
        self._store: NoteStore | None = None

    def _build(self) -> NoteStore | SaveReceipt:
        try:
            module = importlib.import_module(self.MODULE)
        except ModuleNotFoundError as exc:
            if exc.name not in (self.MODULE, "charm_notes"):
                log.warning("note store import failed: %s", exc)
            return SaveReceipt(ok=False, error=NOT_INSTALLED)
        cls = getattr(module, "OsApiStore", None)
        if cls is None:
            return SaveReceipt(ok=False, error=NOT_INSTALLED)
        factory = getattr(cls, "from_env", None) or cls
        try:
            store: NoteStore = factory()
        except Exception as exc:  # config not found, bad config, ...
            reason = str(exc) or type(exc).__name__
            log.warning("note store unavailable: %s", reason)
            return SaveReceipt(ok=False, error=f"note store not configured ({reason})")
        return store

    async def save(self, note: Note) -> SaveReceipt:
        if self._store is None:
            built = self._build()
            if isinstance(built, SaveReceipt):
                return built
            self._store = built
        return await self._store.save(note)


class FileNoteStore:
    """One new Markdown file per note (never overwrites), in the same format as the osapi store.

    `ok=True` only after the file is written and fsynced. A name collision gets a numeric suffix.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _write(self, note: Note) -> SaveReceipt:
        from charm_notes.osapi import note_content, note_filename

        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            stem = f"{note.captured_at:%Y-%m-%d}-charm-" + note_filename(note).removesuffix(".md")
            for n in range(100):
                path = self.directory / (f"{stem}.md" if n == 0 else f"{stem}-{n + 1}.md")
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    continue
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(note_content(note))
                    handle.flush()
                    os.fsync(handle.fileno())
                return SaveReceipt(ok=True, where=str(path))
        except OSError as exc:
            return SaveReceipt(ok=False, error=f"couldn't write the note ({exc.strerror or exc})")
        return SaveReceipt(ok=False, error="couldn't pick a free file name")

    async def save(self, note: Note) -> SaveReceipt:
        return await asyncio.to_thread(self._write, note)


def make_store(backend: str, notes_dir: Path | None = None) -> NoteStore:
    backend = backend.strip().lower() or "file"
    if backend == "file":
        return FileNoteStore(notes_dir or Path(".local") / "notes")
    if backend == "fake":
        return FakeNoteStore()
    if backend == "off":
        return UnavailableStore("saving notes is turned off on this server")
    if backend == "osapi":
        return LazyOsApiStore()
    return UnavailableStore(f"unknown note store {backend!r} (use file, osapi, fake or off)")
