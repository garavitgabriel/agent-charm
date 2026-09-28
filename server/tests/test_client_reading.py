"""charm-client's reading additions: `--setting`, and printing mode/setting/detail/saved."""

from __future__ import annotations

import argparse

import pytest

from charm_server import client

from .conftest import Harness


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "say": None,
        "wav": None,
        "mic": False,
        "voice": None,
        "edition": False,
        "pending": False,
        "action": None,
        "held_ms": None,
        "no_play": True,
        "url": None,
        "token": None,
        "device_id": "test-client",
        "timeout": 10.0,
        "setting": None,
    }
    return argparse.Namespace(**(base | overrides))


async def test_setting_is_sent_and_the_echo_printed(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.deps.books.enter("Dune", chapter="2")
    code = await client.run(
        _args(url=harness.url, setting=["speech=on", "mode=default"]), harness.deps.config
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "mode reading (Dune · 2)" in out  # restored on connect
    assert "setting speech=on" in out
    assert "mode default" in out and "setting mode=default" in out


def test_format_card_shows_detail_and_saved() -> None:
    card = {
        "id": "a",
        "kind": "answer",
        "title": "T",
        "source": "dex",
        "body": "Lead.",
        "detail": "Para one.\n\nPara two.",
        "data": {"saved": True},
    }
    text = client.format_card(card)
    assert "Para one." in text and "Para two." in text
    assert "saved: yes (store confirmed)" in text
