"""The `charm-feeds build` command end to end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import CARDS, RAW

from charm_feeds.cli import main
from charm_feeds.schema import CardValidator


def test_build_writes_the_fixture_cards(tmp_path: Path, validator: CardValidator) -> None:
    out = tmp_path / "cards"
    code = main(["build", "--src", str(RAW), "--out", str(out),
                 "--now", "2026-09-25T17:30:00+00:00"])
    assert code == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == sorted(p.name for p in CARDS.glob("*.json"))
    for path in out.iterdir():
        assert validator.errors(json.loads(path.read_text(encoding="utf-8"))) == []


def test_build_replaces_its_own_old_files_only(tmp_path: Path) -> None:
    out = tmp_path / "cards"
    out.mkdir()
    (out / "07-decision.json").write_text("{}", encoding="utf-8")  # left from an older build
    (out / "notes.txt").write_text("keep me", encoding="utf-8")
    assert main(["build", "--src", str(RAW), "--out", str(out)]) == 0
    assert not (out / "07-decision.json").exists()
    assert (out / "notes.txt").read_text(encoding="utf-8") == "keep me"


def test_build_rejects_a_naive_now(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["build", "--src", str(RAW), "--out", str(tmp_path),
                 "--now", "2026-09-25T17:30"]) == 2
    assert "offset" in capsys.readouterr().err


def test_build_from_an_empty_cache_still_writes_six_cards(tmp_path: Path) -> None:
    out = tmp_path / "cards"
    assert main(["build", "--src", str(tmp_path / "nothing"), "--out", str(out)]) == 0
    assert len(list(out.glob("*.json"))) == 6
