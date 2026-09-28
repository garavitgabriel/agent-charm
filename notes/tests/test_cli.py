"""`charm-notes` CLI — against the fake service from test_osapi; never the real one."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_service import TOKEN, Fake

from charm_notes import cli


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No real env vars or config files leak into these tests."""
    for var in ("OS_API_BASE", "OS_API_TOKEN", "OS_API_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    cfg = tmp_path / "os-api.env"
    paths = lambda env=None, home=None: [cfg]
    monkeypatch.setattr("charm_notes.osapi.config_search_paths", paths)
    monkeypatch.setattr("charm_notes.cli.config_search_paths", paths)
    return cfg


def test_save_dry_run_prints_exact_file_and_sends_nothing(
        capsys: pytest.CaptureFixture[str], fake: tuple[Fake, str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    state, base = fake
    monkeypatch.setenv("OS_API_BASE", base)
    monkeypatch.setenv("OS_API_TOKEN", TOKEN)
    rc = cli.main(["save", "Foxes win because they change their minds.", "--book",
                   "Superforecasting", "--author", "Philip Tetlock", "--chapter", "3",
                   "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0 and state.requests == []
    lines = out.split("\n")
    assert lines[0] == ("# dry run: would POST /submit "
                        "filename=foxes-win-because-they-change-their.md agent=charm")
    assert lines[1] == "---" and lines[3] == "type: reading-note"
    assert lines[4].startswith("created: ")
    assert lines[5:12] == ["source: dex-charm", 'book: "Superforecasting"',
                           'author: "Philip Tetlock"', 'chapter: "3"', 'language: "en"',
                           "tags: [reading, charm]", "---"]
    assert out.endswith("\n\n> Foxes win because they change their minds.\n")
    assert TOKEN not in out


def test_save_without_config_is_not_saved(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["save", "a thought"]) == 1
    out = capsys.readouterr()
    assert out.out == "" and out.err == "not saved: vault service config not found\n"


def test_save_through_fake_service(capsys: pytest.CaptureFixture[str],
                                   fake: tuple[Fake, str],
                                   isolated_config: Path) -> None:
    state, base = fake
    isolated_config.write_text(f"OS_API_BASE={base}\nOS_API_TOKEN={TOKEN}\n")
    assert cli.main(["save", "a thought", "--book", "Dune", "--language", "es"]) == 0
    out = capsys.readouterr()
    assert out.out == "saved: inbox/2026-09-27-charm-foxes.md\n"
    [req] = state.requests
    assert json.loads(req["body"])["content"].endswith('\n---\n\n> a thought\n')
    state.status = 401
    assert cli.main(["save", "again"]) == 1
    out2 = capsys.readouterr()
    assert out2.err == "not saved: vault service rejected the token (401)\n"
    assert len(state.requests) == 2
    assert TOKEN not in out.out + out.err + out2.out + out2.err


def test_check_reports_config_not_found_honestly(capsys: pytest.CaptureFixture[str],
                                                 fake: tuple[Fake, str],
                                                 isolated_config: Path) -> None:
    state, base = fake
    state.body = b'{"ok": true}'
    assert cli.main(["check", "--base", base]) == 1  # healthy service, but no config
    out = capsys.readouterr().out
    assert out == (f"config: not found (looked in: env OS_API_BASE/OS_API_TOKEN, "
                   f"{isolated_config})\n"
                   f"health: ok ({base}/health)\n")
    assert [r["method"] for r in state.requests] == ["GET"]  # check never writes


def test_check_without_base_or_config(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["check"]) == 1
    assert capsys.readouterr().out.endswith("health: skipped (no base URL; pass --base)\n")


def test_check_with_config_never_prints_token(capsys: pytest.CaptureFixture[str],
                                              fake: tuple[Fake, str],
                                              isolated_config: Path) -> None:
    state, base = fake
    state.body = b'{"ok": true}'
    isolated_config.write_text(f"OS_API_BASE={base}\nOS_API_TOKEN={TOKEN}\n")
    assert cli.main(["check"]) == 0
    out = capsys.readouterr().out
    assert out == (f"config: found ({isolated_config}); base {base}; token present\n"
                   f"health: ok ({base}/health)\n")
    assert TOKEN not in out
    assert [r["path"] for r in state.requests] == ["/health"]


def test_author_needs_book() -> None:
    with pytest.raises(SystemExit):
        cli.main(["save", "x", "--chapter", "3"])
