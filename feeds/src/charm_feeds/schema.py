"""Validation against the frozen wire contract, `contract/card.schema.json`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from charm_feeds.text import parse_time

# feeds/src/charm_feeds/schema.py -> repo root is three levels above the package.
DEFAULT_SCHEMA = Path(__file__).resolve().parents[3] / "contract" / "card.schema.json"


class CardError(ValueError):
    pass


def schema_path() -> Path:
    return Path(os.environ.get("CHARM_CARD_SCHEMA", DEFAULT_SCHEMA))


class CardValidator:
    def __init__(self, path: Path | None = None) -> None:
        path = path or schema_path()
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def errors(self, card: Any) -> list[str]:
        problems = [
            f"{'/'.join(map(str, e.absolute_path)) or '<card>'}: {e.message}"
            for e in self._validator.iter_errors(card)
        ]
        # jsonschema doesn't assert `format: date-time` without an extra package; check it here.
        if isinstance(card, dict):
            for key in ("created_at", "fresh_until"):
                if key in card and parse_time(card[key]) is None:
                    problems.append(f"{key}: not an RFC 3339 date-time with offset")
        return problems

    def check(self, card: Any) -> None:
        problems = self.errors(card)
        if problems:
            ident = card.get("id", "?") if isinstance(card, dict) else "?"
            raise CardError(f"card {ident} breaks the contract: " + "; ".join(problems))
