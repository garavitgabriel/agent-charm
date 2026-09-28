from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from charm_feeds.build import build_cards
from charm_feeds.cards import Card
from charm_feeds.schema import CardValidator

FEEDS_ROOT = Path(__file__).resolve().parents[1]
RAW = FEEDS_ROOT / "fixtures" / "raw"
CARDS = FEEDS_ROOT / "fixtures" / "cards"
# The moment the committed fixture cards were built at (just after the pull on 2026-09-25).
FIXTURE_NOW = datetime.fromisoformat("2026-09-25T17:30:00+00:00")
TZ = ZoneInfo("America/Lima")


@pytest.fixture(scope="session")
def validator() -> CardValidator:
    return CardValidator()


@pytest.fixture
def feed_dir(tmp_path: Path) -> Path:
    """A private copy of the scrubbed raw fixtures that a test may mutate."""
    target = tmp_path / "feeds"
    shutil.copytree(RAW, target)
    return target


def read_feed(directory: Path, name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
    return data


def write_feed(directory: Path, name: str, payload: object) -> None:
    (directory / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def edit_feed(directory: Path, name: str, change: Callable[[dict[str, Any]], None]) -> None:
    payload = read_feed(directory, name)
    change(payload)
    write_feed(directory, name, payload)


def built(
    directory: Path, validator: CardValidator, now: datetime = FIXTURE_NOW
) -> dict[str, Card]:
    """Build, check every card against the contract, and index the cards by section."""
    cards = build_cards(directory, now, TZ)
    for _, card in cards:
        validator.check(card)
    return {card["data"]["section"]: card for _, card in cards}
