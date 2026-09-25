"""The committed fixture cards: all valid, in order, and exactly what the builder makes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import CARDS, FIXTURE_NOW, RAW, TZ

from charm_feeds.build import build_cards, render
from charm_feeds.cards import SECTIONS
from charm_feeds.schema import CardValidator
from charm_feeds.sources import FEEDS

CARD_FILES = sorted(CARDS.glob("*.json"))


def test_fixture_cards_exist() -> None:
    assert [p.name for p in CARD_FILES] == [f"{i:02d}-{s}.json" for i, s in
                                            enumerate(SECTIONS, 1)]


@pytest.mark.parametrize("path", CARD_FILES, ids=lambda p: p.name)
def test_every_fixture_card_validates(path: Path, validator: CardValidator) -> None:
    card = json.loads(path.read_text(encoding="utf-8"))
    assert validator.errors(card) == []


def test_fixture_cards_match_a_fresh_build() -> None:
    """Guards drift: fixtures/cards must be regenerated whenever the mapping changes."""
    for name, card in build_cards(RAW, FIXTURE_NOW, TZ):
        assert (CARDS / name).read_text(encoding="utf-8") == render(card), name


def test_one_raw_fixture_per_feed_and_never_spend_pulse() -> None:
    assert sorted(p.stem for p in RAW.glob("*.json")) == sorted(s.name for s in FEEDS)
    assert not list(RAW.parent.rglob("*spend*"))


def test_fixtures_cover_fresh_and_stale() -> None:
    cards = [json.loads(p.read_text(encoding="utf-8")) for p in CARD_FILES]
    assert any(c.get("stale") for c in cards)
    assert any(not c.get("stale") for c in cards)
    assert all(c["kind"] == "edition" for c in cards)
