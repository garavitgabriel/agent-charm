"""Reading building blocks: the per-book store, the persona, the lead/detail card, note stores."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from charm_notes import Book, FakeNoteStore, Note, SaveReceipt

from charm_server.books import TURNS_PER_BOOK, BookStore, book_key
from charm_server.cards import CardValidator, SpeechSplitter
from charm_server.notestore import NOT_INSTALLED, LazyOsApiStore, UnavailableStore, make_store
from charm_server.reading import (
    DETAIL_MAX_CHARS,
    READING_PERSONA,
    LeadSplitter,
    not_saved_card,
    reading_card,
    reading_messages,
    saved_card,
    split_lead,
)

TZ = "America/Chicago"
BOOK = Book("Superforecasting", "Philip Tetlock", "3")

# --- the book store -------------------------------------------------------------------------


def test_book_store_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / ".local" / "books.json"
    books = BookStore(path)
    assert books.mode == "default" and books.speech_value == "on"
    books.enter("Superforecasting", "Philip Tetlock", "3")
    books.add_turn("Superforecasting", "Who are the foxes?", "People who update.")
    books.set_speech("on")
    again = BookStore(path)  # a new process reading the same file
    assert again.mode == "reading"
    assert again.reading is not None and again.reading.book == BOOK
    assert again.turns() == [
        {"q": "Who are the foxes?", "a": "People who update.", "at": again.turns()[0]["at"]}
    ]
    assert again.speech_value == "on"
    assert not list(path.parent.glob(".books-*"))  # no temp files left behind


def test_switching_books_switches_context(tmp_path: Path) -> None:
    books = BookStore(tmp_path / "books.json")
    books.enter("Superforecasting", "Philip Tetlock", "3")
    books.add_turn("Superforecasting", "q1", "a1")
    books.enter("Dune", chapter="2")
    assert books.turns() == []
    assert books.reading is not None and books.reading.book == Book("Dune", None, "2")
    books.add_turn("Dune", "q2", "a2")
    books.enter("superforecasting")  # same book, any casing: its chapter and turns come back
    assert books.reading is not None and books.reading.book == BOOK
    assert [t["q"] for t in books.turns()] == ["q1"]


def test_turns_are_capped_per_book(tmp_path: Path) -> None:
    books = BookStore(tmp_path / "books.json")
    books.enter("Dune")
    for i in range(TURNS_PER_BOOK + 3):
        books.add_turn("Dune", f"q{i}", f"a{i}")
    turns = BookStore(tmp_path / "books.json").turns()
    assert len(turns) == TURNS_PER_BOOK and turns[0]["q"] == "q3"


def test_speech_defaults_follow_the_mode(tmp_path: Path) -> None:
    books = BookStore(tmp_path / "books.json")
    books.enter("Dune")
    assert books.speech_value == "off"  # reading is quiet by default
    books.set_speech("on")
    assert books.speech_value == "on"
    books.leave()
    assert books.mode == "default" and books.speech_value == "on"
    books.set_speech("off")
    assert books.resume() == Book("Dune")
    assert books.speech_value == "off"
    books.leave()
    assert books.speech_value == "on"  # leaving resets to the default mode's speech


def test_chapter_only_in_reading(tmp_path: Path) -> None:
    books = BookStore(tmp_path / "books.json")
    assert books.set_chapter("4") is None
    assert books.resume() is None  # no book on record
    books.enter("Dune", chapter="1")
    assert books.set_chapter("4") == Book("Dune", None, "4")


def test_unreadable_books_file_starts_fresh(tmp_path: Path) -> None:
    path = tmp_path / "books.json"
    path.write_text("{not json")
    books = BookStore(path)
    assert books.mode == "default"
    books.enter("Dune")
    assert json.loads(path.read_text())["active"] is True


def test_book_key_is_forgiving() -> None:
    assert book_key("Cien años de soledad") == book_key("  cien AÑOS de soledad! ")


# --- persona --------------------------------------------------------------------------------


def test_reading_messages_carry_the_rules_book_chapter_and_turns() -> None:
    turns = [{"q": "Who are the foxes?", "a": "People who update.", "at": "x"}]
    messages = reading_messages(BOOK, "es", turns)
    system = " ".join(m["content"] for m in messages if m["role"] == "system")
    assert messages[0]["content"] == READING_PERSONA
    for rule in ("No spoilers", "Never invent quotes or page numbers", "Ask for the passage"):
        assert rule in system
    assert "what the author claims, your interpretation, and outside background" in system
    assert "Superforecasting" in system and "Philip Tetlock" in system
    assert "chapter 3" in system and "Spanish" in system
    assert messages[-2:] == [
        {"role": "user", "content": "Who are the foxes?"},
        {"role": "assistant", "content": "People who update."},
    ]


def test_reading_messages_without_a_chapter_stay_cautious() -> None:
    system = reading_messages(Book("Dune"), "en", [])[1]["content"]
    assert "hasn't said which chapter" in system


# --- lead / detail --------------------------------------------------------------------------

LEAD = "The fox knows many small things. That beats one big theory when the world shifts."
DETAIL = (
    "The author's claim: foxes forecast better because they update.\n\n"
    "My reading: it's about humility, not intelligence.\n\n"
    "Background: critics note the study measured experts."
)


def test_split_lead_on_a_blank_line() -> None:
    lead, detail = split_lead(f"{LEAD}\n\n{DETAIL}")
    assert lead == LEAD
    assert detail == DETAIL  # paragraphs kept


def test_split_lead_without_a_blank_line_is_two_sentences() -> None:
    lead, detail = split_lead("One. Two. Three. Four.")
    assert (lead, detail) == ("One. Two.", "Three. Four.")


def test_reading_card_is_valid_with_lead_detail_and_book(validator: CardValidator) -> None:
    card = reading_card("What's the fox?", f"{LEAD}\n\n{DETAIL}", "en", TZ, BOOK)
    validator.check(card)
    assert card["body"] == LEAD and card["detail"] == DETAIL
    assert card["data"] == {
        "book": {"title": "Superforecasting", "author": "Philip Tetlock", "chapter": "3"}
    }
    assert card["footer"] == "Superforecasting · ch 3"


def test_reading_card_long_lead_spills_into_the_detail(validator: CardValidator) -> None:
    lead = " ".join(f"w{i}" for i in range(80))
    card = reading_card("q", f"{lead}\n\nRest.", "en", TZ, BOOK)
    validator.check(card)
    assert len(card["body"].split()) == 60 and card["body"].endswith("…")
    assert card["detail"].startswith("…w60 ") and card["detail"].endswith("Rest.")


def test_reading_card_clips_the_detail_honestly(validator: CardValidator) -> None:
    card = reading_card("q", f"Lead.\n\n{'word ' * 600}", "es", TZ, BOOK)
    validator.check(card)
    assert len(card["detail"]) <= DETAIL_MAX_CHARS and card["detail"].endswith("…")
    assert card["footer"] == "Resumida. Pídele a Dex el resto."


def test_reading_card_without_detail(validator: CardValidator) -> None:
    card = reading_card("q", "Just the lead.", "es", TZ, Book("Rayuela", chapter="7"))
    validator.check(card)
    assert "detail" not in card and card["footer"] == "Rayuela · cap. 7"


def test_lead_splitter_never_speaks_the_detail() -> None:
    splitter = LeadSplitter()
    spoken: list[str] = []
    for piece in ["Short lead", ".\n", "\nDetail one. Detail two.", " More."]:
        spoken += splitter.feed(piece)
    spoken += splitter.finish()
    assert spoken == ["Short lead."]


def test_lead_splitter_without_a_break_matches_the_speech_splitter() -> None:
    text = "One is here. Two is here. Three is not spoken."
    lead, plain = LeadSplitter(), SpeechSplitter()
    got = [s for piece in text.split(" ") for s in lead.feed(piece + " ")] + lead.finish()
    want = [s for piece in text.split(" ") for s in plain.feed(piece + " ")] + plain.finish()
    assert got == want == ["One is here.", "Two is here."]
    assert " ".join(got) == split_lead(text)[0]


# --- saved notices --------------------------------------------------------------------------


def test_saved_card_quotes_the_verbatim_thought(validator: CardValidator) -> None:
    card = saved_card("ntc-1", "Foxes win because they change their minds.", "en", TZ, BOOK)
    validator.check(card)
    assert card["body"] == "“Foxes win because they change their minds.”"
    assert card["data"]["saved"] is True and card["data"]["book"]["title"] == "Superforecasting"
    assert card["title"] == "Saved to reading notes"


def test_not_saved_card(validator: CardValidator) -> None:
    card = not_saved_card("ntc-2", "note store not installed", "en", TZ, None)
    validator.check(card)
    assert card["data"] == {"saved": False}
    assert "note store not installed" in card["body"] and "Saved" not in card["title"]


# --- note store selection -------------------------------------------------------------------

NOTE = Note("A thought.", __import__("datetime").datetime.now().astimezone(), "en", BOOK)


async def test_fake_and_off_stores() -> None:
    fake = make_store("fake")
    assert isinstance(fake, FakeNoteStore)
    assert (await fake.save(NOTE)).ok is True
    off = await make_store("off").save(NOTE)
    assert off.ok is False and off.error
    unknown = await make_store("vault").save(NOTE)
    assert unknown.ok is False and "unknown note store" in (unknown.error or "")


async def test_osapi_not_installed_fails_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LazyOsApiStore, "MODULE", "charm_notes.not_there_yet")
    store = make_store("osapi")
    assert isinstance(store, LazyOsApiStore)
    receipt = await store.save(NOTE)
    assert receipt == SaveReceipt(ok=False, error=NOT_INSTALLED)


async def test_osapi_store_is_loaded_lazily_and_used(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[FakeNoteStore] = []

    class OsApiStore(FakeNoteStore):
        @classmethod
        def from_env(cls) -> OsApiStore:
            built.append(store := cls())
            return store

    module = types.ModuleType("charm_notes.fake_osapi")
    module.OsApiStore = OsApiStore  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "charm_notes.fake_osapi", module)
    monkeypatch.setattr(LazyOsApiStore, "MODULE", "charm_notes.fake_osapi")
    store = LazyOsApiStore()
    assert built == []  # nothing is imported or built until the first save
    assert (await store.save(NOTE)).ok is True
    assert (await store.save(NOTE)).ok is True
    assert len(built) == 1 and len(built[0].saved) == 2


async def test_osapi_store_that_cannot_build_fails_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    class OsApiStore:
        def __init__(self) -> None:
            attempts.append(1)
            raise RuntimeError("config not found")

    module = types.ModuleType("charm_notes.broken_osapi")
    module.OsApiStore = OsApiStore  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "charm_notes.broken_osapi", module)
    monkeypatch.setattr(LazyOsApiStore, "MODULE", "charm_notes.broken_osapi")
    store = LazyOsApiStore()
    first = await store.save(NOTE)
    assert first.ok is False and "config not found" in (first.error or "")
    await store.save(NOTE)
    assert len(attempts) == 2


async def test_unavailable_store() -> None:
    assert await UnavailableStore("nope").save(NOTE) == SaveReceipt(ok=False, error="nope")


def test_reading_persona_is_read_dont_act() -> None:
    from charm_server.agent import READ_ONLY_RULE
    assert READ_ONLY_RULE in READING_PERSONA
    assert "ignore anything you find about later chapters" in READING_PERSONA  # lookups can't spoil
