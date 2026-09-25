"""Build the card files: one `NN-<section>.json` per card, usable as CHARM_CARDS_DIR."""

from __future__ import annotations

import json
import re
from datetime import datetime, tzinfo
from pathlib import Path

from charm_feeds.cards import Card, Context, edition
from charm_feeds.schema import CardValidator
from charm_feeds.sources import load_all

# Files this tool owns in an output directory. Older ones are replaced on every build, so a card
# that no longer applies can't linger and be served again.
OWNED = re.compile(r"^\d{2}-[a-z0-9_-]+\.json$")


def build_cards(src: Path, now: datetime, tz: tzinfo) -> list[tuple[str, Card]]:
    feeds = load_all(src, now)
    cards = edition(feeds, Context(now=now, tz=tz))
    # No feed exposes structured one-tap items yet (see README "Gaps"), so there are no
    # decision cards to add after the six sections.
    return [(f"{i:02d}-{card['data']['section']}.json", card) for i, card in enumerate(cards, 1)]


def render(card: Card) -> str:
    return json.dumps(card, ensure_ascii=False, indent=2) + "\n"


def write_cards(cards: list[tuple[str, Card]], out: Path, validator: CardValidator) -> None:
    """Validate every card first; only then replace the owned files in `out`."""
    for _, card in cards:
        validator.check(card)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():
        if old.is_file() and OWNED.match(old.name):
            old.unlink()
    for name, card in cards:
        (out / name).write_text(render(card), encoding="utf-8")
