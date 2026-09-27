"""OsApiStore against a local fake OS knowledge service — no network, no real vault."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fake_service import TOKEN, Fake

from charm_notes import Book, Note, NoteStore
from charm_notes.osapi import (
    OsApiConfig,
    OsApiStore,
    check_health,
    config_search_paths,
    load_config,
    note_content,
    note_filename,
)

NOTE = Note("Foxes win because they change their minds.",
            datetime(2026, 9, 27, 18, 40, tzinfo=timezone(timedelta(hours=-5))), "en",
            Book("Superforecasting", "Philip Tetlock", "3"))


def _store(base: str, timeout: float = 5.0) -> OsApiStore:
    return OsApiStore(OsApiConfig(base=base, token=TOKEN, source="test"), timeout=timeout)


def _assert_no_token(*texts: object) -> None:
    for t in texts:
        assert TOKEN not in str(t)


async def test_is_a_note_store() -> None:
    store: NoteStore = _store("http://127.0.0.1:9")
    assert store is not None


async def test_success_posts_once_with_bearer_and_payload(fake: tuple[Fake, str]) -> None:
    state, base = fake
    receipt = await _store(base + "/").save(NOTE)
    assert receipt.ok and receipt.where == "inbox/2026-09-27-charm-foxes.md"
    assert receipt.error is None
    [req] = state.requests
    assert req["method"] == "POST" and req["path"] == "/submit"
    assert req["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert req["headers"]["Content-Type"] == "application/json"
    payload = json.loads(req["body"])
    assert payload == {"filename": "foxes-win-because-they-change-their.md",
                       "content": note_content(NOTE), "agent": "charm"}


@pytest.mark.parametrize(("status", "reason"), [
    (401, "vault service rejected the token (401)"),
    (403, "vault service refused the write (403)"),
    (500, "vault service error (500)"),
    (503, "vault service error (503)"),
    (400, "vault service returned HTTP 400"),
    (302, "vault service returned HTTP 302"),
])
async def test_http_errors_fail_once_without_retry(fake: tuple[Fake, str], status: int,
                                                   reason: str) -> None:
    state, base = fake
    state.status, state.body = status, b'{"error": "nope"}'
    state.headers = {"Location": base + "/elsewhere"} if status == 302 else {}
    receipt = await _store(base).save(NOTE)
    assert not receipt.ok and receipt.where is None and receipt.error == reason
    assert len(state.requests) == 1  # no retry, and no redirect follow-up


@pytest.mark.parametrize("body", [
    b"not json",
    b"[]",
    b"{}",
    b'{"ok": true}',
    b'{"ok": true, "path": ""}',
    b'{"ok": true, "path": 42}',
    b'{"ok": false, "path": "inbox/x.md"}',
    b"\xff\xfe",
])
async def test_2xx_without_path_is_malformed(fake: tuple[Fake, str], body: bytes) -> None:
    state, base = fake
    state.body = body
    receipt = await _store(base).save(NOTE)
    assert receipt == receipt.__class__(ok=False, error="vault service gave a malformed reply")
    assert len(state.requests) == 1


async def test_timeout_fails_once_without_retry(fake: tuple[Fake, str]) -> None:
    state, base = fake
    state.delay = 1.0
    receipt = await _store(base, timeout=0.2).save(NOTE)
    assert not receipt.ok and receipt.error == "vault service timed out"
    await asyncio.sleep(1.2)  # let a (wrong) retry land before counting
    assert len(state.requests) == 1


async def test_unreachable() -> None:
    receipt = await _store("http://127.0.0.1:9").save(NOTE)  # discard port: nothing listens
    assert not receipt.ok and receipt.error == "vault service unreachable"


async def test_missing_config_never_claims_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("charm_notes.osapi.load_config", lambda: None)
    store = OsApiStore()
    assert not store.configured
    receipt = await store.save(NOTE)
    assert not receipt.ok and receipt.error == "vault service config not found"


def test_default_timeout_is_10s() -> None:
    store = OsApiStore(OsApiConfig("http://x", TOKEN, "test"))
    assert store._timeout == 10.0


async def test_token_never_leaks(fake: tuple[Fake, str], caplog: pytest.LogCaptureFixture,
                                 capsys: pytest.CaptureFixture[str]) -> None:
    caplog.set_level(logging.DEBUG)
    state, base = fake
    store = _store(base)
    receipts = [await store.save(NOTE)]
    # A hostile/buggy service echoing the token back must not get it into our errors.
    for status in (200, 401, 500):
        state.status = status
        state.body = json.dumps({"error": TOKEN, "detail": TOKEN}).encode()
        receipts.append(await store.save(NOTE))
    state.delay = 0.5
    receipts.append(await _store(base, timeout=0.1).save(NOTE))
    receipts.append(await _store("http://127.0.0.1:9").save(NOTE))
    out = capsys.readouterr()
    _assert_no_token(caplog.text, out.out, out.err, repr(store), repr(store._config),
                     *receipts, *(r.error for r in receipts), note_content(NOTE))
    assert caplog.records  # we did log; just never the token


def test_content_format_is_exact() -> None:
    assert note_content(NOTE) == (
        "---\n"
        'title: "Foxes win because they change their minds."\n'
        "type: reading-note\n"
        "created: 2026-09-27T18:40:00-05:00\n"
        "source: dex-charm\n"
        'book: "Superforecasting"\n'
        'author: "Philip Tetlock"\n'
        'chapter: "3"\n'
        'language: "en"\n'
        "tags: [reading, charm]\n"
        "---\n"
        "\n"
        "> Foxes win because they change their minds.\n"
    )


def test_content_is_verbatim_and_yaml_safe() -> None:
    text = ('Ojo: "no es lo mismo" — ¿verdad?\n\n  second: line: with colons  \n'
            "#not a comment ---")
    note = Note(text, datetime(2026, 9, 27, tzinfo=UTC), "es",
                Book('He said "Hi": a novel', None, None))
    content = note_content(note)
    front, body = content.split("\n---\n\n", 1)
    assert 'book: "He said \\"Hi\\": a novel"' in front
    assert "author: null" in front and "chapter: null" in front
    assert 'language: "es"' in front
    assert 'title: "Ojo: \\"no es lo mismo\\" — ¿verdad? second:…"' in front
    unquoted = "\n".join(line[2:] if line.startswith("> ") else line[1:]
                         for line in body.rstrip("\n").split("\n"))
    assert unquoted == text  # exact words, nothing generated around them
    assert body.count("\n") == text.count("\n") + 1


def test_content_without_book() -> None:
    note = Note("A loose thought.", datetime(2026, 9, 27, tzinfo=UTC), "en")
    content = note_content(note)
    assert "book: null\nauthor: null\nchapter: null\n" in content
    assert content.endswith("---\n\n> A loose thought.\n")


@pytest.mark.parametrize(("text", "name"), [
    ("Foxes win because they change their minds.", "foxes-win-because-they-change-their.md"),
    ("¿Qué pasa?", "qu-pasa.md"),
    ("!!!", "note.md"),
])
def test_filename_slug(text: str, name: str) -> None:
    assert note_filename(Note(text, datetime(2026, 9, 27, tzinfo=UTC), "en")) == name


def test_config_env_wins(tmp_path: Path) -> None:
    f = tmp_path / "os-api.env"
    f.write_text("OS_API_BASE=http://file\nOS_API_TOKEN=filetok\n")
    cfg = load_config({"OS_API_BASE": "http://env/", "OS_API_TOKEN": "envtok"}, [f])
    assert cfg == OsApiConfig("http://env", "envtok", "env")


def test_config_file_order_and_parsing(tmp_path: Path) -> None:
    first, second = tmp_path / "custom.env", tmp_path / "home.env"
    second.write_text("OS_API_BASE=http://second\nOS_API_TOKEN=second\n")
    assert load_config({}, [first, second]) == OsApiConfig("http://second", "second", str(second))
    first.write_text('# comment\nexport OS_API_BASE="http://first:8088/"\n'
                     "OS_API_TOKEN='abc def' # trailing\n")
    assert load_config({}, [first, second]) == OsApiConfig("http://first:8088", "abc def",
                                                          str(first))
    # A partial env is completed from the file.
    assert load_config({"OS_API_BASE": "http://env"}, [first]) == OsApiConfig(
        "http://env", "abc def", str(first))


def test_config_uses_os_api_config_then_home(tmp_path: Path) -> None:
    custom = tmp_path / "c.env"
    assert config_search_paths({"OS_API_CONFIG": str(custom)}, tmp_path) == [
        custom, tmp_path / ".os-api.env", Path("/etc/os-api.env")]
    assert config_search_paths({}, tmp_path)[0] == tmp_path / ".os-api.env"


def test_config_not_found(tmp_path: Path) -> None:
    assert load_config({}, [tmp_path / "missing.env"]) is None
    (tmp_path / "half.env").write_text("OS_API_BASE=http://x\n")
    assert load_config({}, [tmp_path / "half.env"]) is None


def test_health(fake: tuple[Fake, str]) -> None:
    state, base = fake
    state.body = b'{"ok": true}'
    assert check_health(base) == (True, "ok")
    assert state.requests[0]["method"] == "GET" and state.requests[0]["path"] == "/health"
    assert "Authorization" not in state.requests[0]["headers"]
    state.status = 500
    assert check_health(base) == (False, "HTTP 500")
    state.status, state.body = 200, b"nope"
    assert check_health(base) == (False, "unexpected reply (HTTP 200)")
    assert check_health("http://127.0.0.1:9") == (False, "unreachable")
