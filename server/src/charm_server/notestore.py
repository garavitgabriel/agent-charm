"""Which note store "save this" goes to: `CHARM_NOTES=osapi|fake|off` (default `osapi`).

- `osapi`: `charm_notes.osapi.OsApiStore`, the OS knowledge service's `POST /submit` (vault inbox
  only). It's imported lazily on the first save. Until that module exists (the notes batch), or
  while it can't be set up, every save fails honestly with the reason. Never a fake success.
- `fake`: `charm_notes.FakeNoteStore`, in memory. For tests and live checks without vault writes.
- `off`: saving is disabled; every save fails and says so.

The server never writes the vault itself: only a `NoteStore` persists notes, and only its
`SaveReceipt(ok=True)` counts as saved.
"""

from __future__ import annotations

import importlib
import logging

from charm_notes import FakeNoteStore, Note, NoteStore, SaveReceipt

log = logging.getLogger(__name__)

NOTES_BACKENDS = ("osapi", "fake", "off")
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


def make_store(backend: str) -> NoteStore:
    backend = backend.strip().lower() or "osapi"
    if backend == "fake":
        return FakeNoteStore()
    if backend == "off":
        return UnavailableStore("saving notes is turned off on this server")
    if backend == "osapi":
        return LazyOsApiStore()
    return UnavailableStore(f"unknown note store {backend!r} (use osapi, fake or off)")
