"""The desk feeds this project may read, and how fresh each one is.

Only the five feeds in `FEEDS` are ever pulled. `spend-pulse.json` (finance) is deliberately absent:
finance data stays on the VPS.

Freshness follows the rule Dex's own board uses (`build-daily-board-payload.js`, `freshFeed`):
a feed is fresh when `status != "failed"` and `fresh_until` is still in the future.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from charm_feeds.text import parse_time

BOARD = "/opt/data/board"


@dataclass(frozen=True)
class FeedSpec:
    name: str
    remote_path: str
    desk: str  # how the desk is named on a card ("sports desk")
    # For feeds that publish no `fresh_until` of their own: how long a filing counts as fresh.
    default_ttl: timedelta | None = None


FEEDS: tuple[FeedSpec, ...] = (
    FeedSpec("sports", f"{BOARD}/feeds/sports.json", "sports desk"),
    FeedSpec("almanac", f"{BOARD}/feeds/almanac.json", "almanac desk"),
    FeedSpec("digest", f"{BOARD}/feeds/digest.json", "digest desk"),
    FeedSpec("radar", f"{BOARD}/feeds/radar.json", "radar desk"),
    # paper-feed.json is the Gmail/Calendar sweep. It carries only `generated_at`; its window is
    # `newer_than:1d`, so a filing older than a day no longer describes today's mail.
    FeedSpec("paper-feed", f"{BOARD}/paper-feed.json", "paper desk", timedelta(hours=24)),
)

FEEDS_BY_NAME = {spec.name: spec for spec in FEEDS}

FORBIDDEN = ("spend-pulse",)


class State(StrEnum):
    FRESH = "fresh"  # usable and within its deadline
    STALE = "stale"  # usable content, but past `fresh_until` (or no deadline was published)
    FAILED = "failed"  # the desk reported failure, or the file can't be read: show no content
    MISSING = "missing"  # nothing was ever pulled: honest-empty


@dataclass(frozen=True)
class Feed:
    spec: FeedSpec
    state: State
    payload: dict[str, Any] | None = None
    generated_at: datetime | None = None
    fresh_until: datetime | None = None
    error: str | None = None

    @property
    def usable(self) -> bool:
        """Content may be shown (fresh, or stale with a label)."""
        return self.state in (State.FRESH, State.STALE) and self.payload is not None

    def sections(self) -> dict[str, Any]:
        if self.payload is None:
            return {}
        sections = self.payload.get("sections")
        return sections if isinstance(sections, dict) else {}


def assess(spec: FeedSpec, payload: object, now: datetime) -> Feed:
    """Decide how fresh one parsed feed is at `now`."""
    if not isinstance(payload, dict):
        return Feed(spec, State.FAILED, error="not a JSON object")
    generated_at = parse_time(payload.get("generated_at"))
    fresh_until = parse_time(payload.get("fresh_until"))
    if fresh_until is None and generated_at is not None and spec.default_ttl is not None:
        fresh_until = generated_at + spec.default_ttl
    if payload.get("status") == "failed":
        return Feed(spec, State.FAILED, payload, generated_at, fresh_until, "desk reported failure")
    if generated_at is None:
        return Feed(spec, State.FAILED, payload, None, fresh_until, "no readable generated_at")
    errors = payload.get("errors")
    if fresh_until is None or now >= fresh_until or errors:
        return Feed(spec, State.STALE, payload, generated_at, fresh_until)
    return Feed(spec, State.FRESH, payload, generated_at, fresh_until)


def load(spec: FeedSpec, directory: Path, now: datetime) -> Feed:
    """Load `<name>.json` from `directory` and assess it. A missing file is MISSING, never faked."""
    path = directory / f"{spec.name}.json"
    if not path.is_file():
        return Feed(spec, State.MISSING)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Feed(spec, State.FAILED, error=f"unreadable: {exc.__class__.__name__}")
    return assess(spec, payload, now)


def load_all(directory: Path, now: datetime) -> dict[str, Feed]:
    return {spec.name: load(spec, directory, now) for spec in FEEDS}
