from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parent
UI = REPO / "ui"
DUMMY_MANIFEST = TOOLS / "fixtures/dummy/manifest.json"


@pytest.fixture
def write_manifest(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Write a manifest dict next to a copy of the dummy sheet; returns its path."""

    def _write(sprites: dict[str, Any] | None = None, fonts: dict[str, Any] | None = None) -> Path:
        sheet = TOOLS / "fixtures/dummy/dummy-sheet.png"
        (tmp_path / "sheet.png").write_bytes(sheet.read_bytes())
        raw: dict[str, Any] = {"version": 1}
        if sprites is not None:
            raw["sprites"] = sprites
        if fonts is not None:
            raw["fonts"] = fonts
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(raw))
        return p

    return _write


def base_sprites(**over: Any) -> dict[str, Any]:
    s: dict[str, Any] = {
        "cell": [32, 40],
        "scale": {"full": 5, "mini": 4},
        "mini_origin": [6, 2],
        "palette": ["#FF00FF", "#00C8B4", "#FFD000", "#FFFFFF", "#283050"],
        "sheets": {"base": "sheet.png"},
        "animations": [
            {"pose": "idle", "row": 0, "frames": [{"col": 0, "ms": 500}, {"col": 1, "ms": 500}]}
        ],
    }
    s.update(over)
    return s
