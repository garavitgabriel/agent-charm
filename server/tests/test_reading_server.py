"""Reading mode over a real localhost WebSocket with fake engines (PROTOCOL § Reading mode)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from charm_notes import Book, FakeNoteStore, Note, SaveReceipt

from charm_server import session as session_module
from charm_server.books import BookStore
from charm_server.notestore import LazyOsApiStore, make_store
from charm_server.reading import READING_PERSONA
from charm_server.server import start

from .conftest import Client, Harness, fake, texts, tone, types

ENTER = "I'm reading Superforecasting by Philip Tetlock, chapter 3."
BOOK_JSON = {"title": "Superforecasting", "author": "Philip Tetlock", "chapter": "3"}
LEAD = "The fox knows many small things. That beats one big theory."
DETAIL = "The author's claim: foxes update.\n\nMy reading: it's humility."
READING_REPLY = f"{LEAD}\n\n{DETAIL}"


async def say(dev: Client, harness: Harness, text: str, language: str = "en") -> list[Any]:
    stt, _, _ = fake(harness.deps)
    stt.text, stt.language = text, language
    await dev.talk(tone(1.0))
    return await dev.until_idle()


def notes(harness: Harness) -> FakeNoteStore:
    assert isinstance(harness.deps.notes, FakeNoteStore)
    return harness.deps.notes


def only(frames: list[Any], kind: str) -> list[dict[str, Any]]:
    return [f for f in texts(frames) if f["type"] == kind]


async def reading_device(harness: Harness) -> Client:
    dev = await harness.device()
    await say(dev, harness, ENTER)
    return dev


# --- entering, switching, leaving ------------------------------------------------------------


async def test_enter_reading_sends_mode_and_quiet_setting(harness: Harness) -> None:
    _, agent, tts = fake(harness.deps)
    dev = await harness.device()
    frames = await say(dev, harness, ENTER)
    assert types(frames) == ["state:transcribing", "transcript", "mode", "setting", "state:idle"]
    msgs = texts(frames)
    assert msgs[2] == {"type": "mode", "value": "reading", "book": BOOK_JSON}
    assert msgs[3] == {"type": "setting", "name": "speech", "value": "off"}
    assert agent.calls == [] and tts.calls == []  # an intent never goes to Dex


async def test_enter_reading_in_spanish(harness: Harness) -> None:
    dev = await harness.device()
    frames = await say(dev, harness, "Estoy leyendo Cien años de soledad, capítulo 3.", "es")
    assert only(frames, "mode") == [
        {
            "type": "mode",
            "value": "reading",
            "book": {"title": "Cien años de soledad", "chapter": "3"},
        }
    ]


async def test_chapter_update_and_leave(harness: Harness) -> None:
    dev = await reading_device(harness)
    frames = await say(dev, harness, "I'm on chapter 4 now.")
    assert only(frames, "mode") == [
        {"type": "mode", "value": "reading", "book": {**BOOK_JSON, "chapter": "4"}}
    ]
    assert only(frames, "setting") == []  # same mode: speech unchanged, no echo needed
    frames = await say(dev, harness, "Deja de leer.", "es")
    assert types(frames) == ["state:transcribing", "transcript", "mode", "setting", "state:idle"]
    assert only(frames, "mode") == [{"type": "mode", "value": "default"}]
    assert only(frames, "setting") == [{"type": "setting", "name": "speech", "value": "on"}]


async def test_leave_when_not_reading_just_confirms(harness: Harness) -> None:
    dev = await harness.device()
    frames = await say(dev, harness, "Stop reading.")
    assert only(frames, "mode") == [{"type": "mode", "value": "default"}]


async def test_switching_books_switches_context(harness: Harness) -> None:
    _, agent, _ = fake(harness.deps)
    agent.reply_text = READING_REPLY
    dev = await reading_device(harness)
    await say(dev, harness, "Who are the foxes?")
    frames = await say(dev, harness, "I'm reading Dune, chapter 2.")
    assert only(frames, "mode")[0]["book"] == {"title": "Dune", "chapter": "2"}
    assert only(frames, "setting") == []  # still reading: speech stays as it was
    await say(dev, harness, "Who is Paul?")
    dune_prompt = agent.calls[-1]
    assert "Dune" in dune_prompt[1]["content"]
    assert all(m["content"] != "Who are the foxes?" for m in dune_prompt)  # no cross-talk
    await say(dev, harness, ENTER)
    await say(dev, harness, "And the hedgehogs?")
    back = agent.calls[-1]
    assert {"role": "user", "content": "Who are the foxes?"} in back
    assert {"role": "user", "content": "Who is Paul?"} not in back


# --- quiet reading answers -------------------------------------------------------------------


async def test_quiet_reading_answer_has_no_speech_frames(harness: Harness) -> None:
    _, agent, tts = fake(harness.deps)
    agent.reply_text = READING_REPLY
    dev = await reading_device(harness)
    frames = await say(dev, harness, "What does the author mean by foxes?")
    assert types(frames) == [
        "state:transcribing",
        "transcript",
        "state:working",
        "card",
        "state:idle",
    ]
    assert not any(isinstance(f, bytes) for f in frames)
    assert tts.calls == []
    card = only(frames, "card")[0]["card"]
    harness.deps.validator.check(card)
    assert card["kind"] == "answer" and card["body"] == LEAD and card["detail"] == DETAIL
    assert card["data"] == {"book": BOOK_JSON}
    prompt = agent.calls[-1]
    assert prompt[0] == {"role": "system", "content": READING_PERSONA}
    assert "chapter 3" in prompt[1]["content"]
    assert prompt[-1] == {"role": "user", "content": "What does the author mean by foxes?"}
    # The Q&A is kept for this book, on disk.
    assert harness.deps.books.turns()[-1]["a"] == READING_REPLY


async def test_voice_on_in_reading_speaks_only_the_lead(harness: Harness) -> None:
    _, agent, tts = fake(harness.deps)
    agent.reply_text = "Short lead.\n\nA long detail. That is never spoken. Ever."
    dev = await reading_device(harness)
    frames = await say(dev, harness, "Voice on.")
    assert only(frames, "setting") == [{"type": "setting", "name": "speech", "value": "on"}]
    frames = await say(dev, harness, "What's going on?")
    assert "speech_start" in types(frames) and "speech_end" in types(frames)
    assert tts.calls == [("Short lead.", "en")]
    frames = await say(dev, harness, "Silencio.", "es")
    assert only(frames, "setting") == [{"type": "setting", "name": "speech", "value": "off"}]
    frames = await say(dev, harness, "And now?")
    assert "speech_start" not in types(frames) and len(tts.calls) == 1


async def test_default_mode_speech_off_is_quiet_too(harness: Harness) -> None:
    _, _, tts = fake(harness.deps)
    dev = await harness.device()
    await say(dev, harness, "Be quiet.")
    frames = await say(dev, harness, "What is a metaphor?")
    assert types(frames) == [
        "state:transcribing",
        "transcript",
        "state:working",
        "card",
        "state:idle",
    ]
    assert tts.calls == []


async def test_cancel_during_a_quiet_answer(harness: Harness) -> None:
    _, agent, _ = fake(harness.deps)
    agent.delay = 1.0
    dev = await reading_device(harness)
    stt, _, _ = fake(harness.deps)
    stt.text = "What does it mean?"
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m.get("value") == "working")
    await dev.send({"type": "cancel"})
    assert await dev.recv() == {"type": "state", "value": "idle"}  # no speech_end: none began
    assert await dev.silent_for(1.3) == []  # the late answer is dropped
    assert harness.deps.books.turns() == []


# --- persistence ------------------------------------------------------------------------------


async def test_reading_survives_reconnect(harness: Harness) -> None:
    dev = await reading_device(harness)
    await dev.ws.close()
    again = await harness.device()  # welcome + idle, then the reading session is restored
    assert await again.recv() == {"type": "mode", "value": "reading", "book": BOOK_JSON}
    assert await again.recv() == {"type": "setting", "name": "speech", "value": "off"}


async def test_reading_survives_server_restart(harness: Harness, books_path: Path) -> None:
    _, agent, _ = fake(harness.deps)
    agent.reply_text = READING_REPLY
    dev = await reading_device(harness)
    await say(dev, harness, "Voice on.")
    await say(dev, harness, "Who are the foxes?")
    assert await asyncio.to_thread(books_path.is_file)

    from dataclasses import replace

    deps2 = replace(harness.deps, books=BookStore(books_path))  # a fresh process's store
    server = await start(deps2, "127.0.0.1", 0)
    port = next(iter(server.sockets)).getsockname()[1]
    try:
        second = Harness(deps=deps2, url=f"ws://127.0.0.1:{port}/charm")
        dev2 = await second.device()
        assert await dev2.recv() == {"type": "mode", "value": "reading", "book": BOOK_JSON}
        assert await dev2.recv() == {"type": "setting", "name": "speech", "value": "on"}
        assert deps2.books.turns()[0]["q"] == "Who are the foxes?"
    finally:
        server.close()
        await server.wait_closed()


async def test_default_mode_connect_sends_nothing_extra(harness: Harness) -> None:
    dev = await harness.device()
    await dev.send({"type": "ping"})
    assert await dev.recv() == {"type": "pong"}


# --- settings from the device ----------------------------------------------------------------


async def test_speech_setting_is_honored_and_echoed(harness: Harness) -> None:
    dev = await reading_device(harness)
    await dev.send({"type": "setting", "name": "speech", "value": "on"})
    assert await dev.recv() == {"type": "setting", "name": "speech", "value": "on"}
    await dev.send({"type": "setting", "name": "speech", "value": "loud"})
    assert await dev.recv() == {"type": "setting", "name": "speech", "value": "on"}  # effective
    await dev.send({"type": "setting", "name": "speech", "value": "off"})
    assert await dev.recv() == {"type": "setting", "name": "speech", "value": "off"}


async def test_mode_setting_resumes_and_leaves_reading(harness: Harness) -> None:
    dev = await reading_device(harness)
    await dev.send({"type": "setting", "name": "mode", "value": "default"})
    assert await dev.recv() == {"type": "mode", "value": "default"}
    assert await dev.recv() == {"type": "setting", "name": "speech", "value": "on"}
    assert await dev.recv() == {"type": "setting", "name": "mode", "value": "default"}
    await dev.send({"type": "setting", "name": "mode", "value": "reading"})
    assert await dev.recv() == {"type": "mode", "value": "reading", "book": BOOK_JSON}
    assert await dev.recv() == {"type": "setting", "name": "speech", "value": "off"}
    assert await dev.recv() == {"type": "setting", "name": "mode", "value": "reading"}
    await dev.send({"type": "setting", "name": "mode", "value": "reading"})  # already there
    assert await dev.recv() == {"type": "setting", "name": "mode", "value": "reading"}


async def test_mode_setting_without_a_book_stays_default(harness: Harness) -> None:
    dev = await harness.device()
    await dev.send({"type": "setting", "name": "mode", "value": "reading"})
    assert await dev.recv() == {"type": "setting", "name": "mode", "value": "default"}
    await dev.send({"type": "setting", "name": "volume", "value": "11"})
    await dev.send({"type": "ping"})
    assert await dev.recv() == {"type": "pong"}  # unknown settings are ignored


# --- save this thought -----------------------------------------------------------------------


async def test_save_in_reading_mode_confirms_after_the_store(harness: Harness) -> None:
    _, agent, tts = fake(harness.deps)
    dev = await reading_device(harness)
    frames = await say(dev, harness, "Save this: Foxes win because they change their minds.")
    assert types(frames) == [
        "state:transcribing",
        "transcript",
        "state:working",
        "card",
        "state:done",
        "state:idle",
    ]
    msgs = texts(frames)
    assert msgs[2] == {"type": "state", "value": "working", "label": "Saving"}
    card = msgs[3]["card"]
    harness.deps.validator.check(card)
    assert card["kind"] == "notice" and card["data"] == {"saved": True, "book": BOOK_JSON}
    assert card["body"] == "“Foxes win because they change their minds.”"
    assert msgs[4] == {"type": "state", "value": "done", "label": "Saved"}
    (note,) = notes(harness).saved
    assert note.text == "Foxes win because they change their minds."  # verbatim
    assert note.book == Book("Superforecasting", "Philip Tetlock", "3")
    assert note.language == "en" and note.captured_at.tzinfo is not None
    assert agent.calls == [] and tts.calls == []  # a save never goes to Dex, never spoken


async def test_save_outside_reading_has_no_book(harness: Harness) -> None:
    dev = await harness.device()
    frames = await say(dev, harness, "Guarda esto: la memoria es un río.", "es")
    card = only(frames, "card")[0]["card"]
    assert card["data"] == {"saved": True} and "footer" not in card
    (note,) = notes(harness).saved
    assert note.book is None and note.language == "es" and note.text == "la memoria es un río."


async def test_save_failure_is_honest(harness: Harness) -> None:
    harness.deps.notes = FakeNoteStore(fail="vault unreachable")
    dev = await reading_device(harness)
    frames = await say(dev, harness, "Save this: foxes.")
    assert types(frames) == [
        "state:transcribing",
        "transcript",
        "state:working",
        "error",
        "card",
        "state:idle",
    ]
    error = only(frames, "error")[0]
    assert error["code"] == "save_failed" and "vault unreachable" in error["text"]
    card = only(frames, "card")[0]["card"]
    harness.deps.validator.check(card)
    assert card["data"]["saved"] is False and "vault unreachable" in card["body"]
    assert all(f.get("value") != "done" for f in texts(frames))


async def test_save_with_store_not_installed(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LazyOsApiStore, "MODULE", "charm_notes.not_merged_yet")
    harness.deps.notes = make_store("osapi")
    dev = await harness.device()
    frames = await say(dev, harness, "Save this: a thought.")
    error = only(frames, "error")[0]
    assert error == {
        "type": "error",
        "code": "save_failed",
        "text": "Not saved: note store not installed",
    }
    assert only(frames, "card")[0]["card"]["data"] == {"saved": False}
    assert all(f.get("value") != "done" for f in texts(frames))


@dataclass
class RaisingStore:
    async def save(self, note: Note) -> SaveReceipt:
        raise ConnectionError("boom")


@dataclass
class HangingStore:
    async def save(self, note: Note) -> SaveReceipt:
        await asyncio.sleep(60)
        return SaveReceipt(ok=True, where="too/late")


@dataclass
class TruthyStore:
    """A store that returns something truthy that isn't `True`: not a confirmation."""

    async def save(self, note: Note) -> SaveReceipt:
        return SaveReceipt(ok="yes", where="?")  # type: ignore[arg-type]


async def test_save_store_crash_or_non_true_receipt_is_a_failure(harness: Harness) -> None:
    dev = await harness.device()
    for store in (RaisingStore(), TruthyStore()):
        harness.deps.notes = store
        frames = await say(dev, harness, "Save this: x")
        assert only(frames, "error")[0]["code"] == "save_failed"
        assert all(f.get("value") != "done" for f in texts(frames))


async def test_save_store_timeout_is_a_failure(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session_module, "SAVE_TIMEOUT_SECONDS", 0.2)
    harness.deps.notes = HangingStore()
    dev = await harness.device()
    frames = await say(dev, harness, "Save this: x")
    assert "didn't confirm" in only(frames, "error")[0]["text"]
    assert only(frames, "card")[0]["card"]["data"] == {"saved": False}


async def test_empty_save_saves_nothing(harness: Harness) -> None:
    dev = await harness.device()
    frames = await say(dev, harness, "Save this.")
    assert types(frames) == ["state:transcribing", "transcript", "error", "card", "state:idle"]
    assert only(frames, "error")[0]["code"] == "save_failed"
    assert notes(harness).saved == []


async def test_save_text_that_looks_like_a_command_is_still_saved(harness: Harness) -> None:
    dev = await reading_device(harness)
    await say(dev, harness, "Save this: stop reading and turn the voice on.")
    assert notes(harness).saved[0].text == "stop reading and turn the voice on."
    assert harness.deps.books.mode == "reading" and harness.deps.books.speech_value == "off"


async def test_every_card_and_frame_stays_in_contract(harness: Harness) -> None:
    """A whole reading session: every card validates and every mode/setting is well-formed."""
    _, agent, _ = fake(harness.deps)
    agent.reply_text = READING_REPLY + " " + "More words here. " * 200
    dev = await harness.device()
    frames: list[Any] = []
    for text in (ENTER, "What's the fox?", "Voice on", "Why?", "Save this: yes.", "Stop reading"):
        frames += await say(dev, harness, text)
    for message in texts(frames):
        if message["type"] == "card":
            harness.deps.validator.check(message["card"])
        if message["type"] == "mode":
            assert message["value"] in ("reading", "default")
            assert ("book" in message) == (message["value"] == "reading")
        if message["type"] == "setting":
            assert message["name"] in ("speech", "mode")
