from __future__ import annotations

import json

import pytest

from charm_server import protocol as p
from charm_server.cards import (
    CardInvalid,
    CardValidator,
    SpeechSplitter,
    answer_card,
    load_cards,
    plain_text,
    say_text,
    sentences,
    title_from_question,
)

from .conftest import EXAMPLES


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.name)
def test_every_contract_example_validates(validator: CardValidator, path: object) -> None:
    validator.check(json.loads(path.read_text()))  # type: ignore[attr-defined]


def test_money_confirm_needs_a_2000ms_hold(validator: CardValidator) -> None:
    money = json.loads((EXAMPLES / "money.json").read_text())
    money["actions"][0]["hold_ms"] = 500
    with pytest.raises(CardInvalid):
        validator.check(money)


@pytest.mark.parametrize("value", ["2026-09-25", "yesterday", "2026-09-25T18:00:00"])
def test_created_at_must_be_an_rfc3339_datetime(validator: CardValidator, value: str) -> None:
    card = json.loads((EXAMPLES / "answer.json").read_text()) | {"created_at": value}
    assert validator.errors(card)


def test_load_cards_splits_edition_and_pending(validator: CardValidator) -> None:
    cards = load_cards(EXAMPLES, validator)
    assert [c["id"] for c in cards.edition] == ["ed-sports", "ed-almanac"]
    assert {c["kind"] for c in cards.pending} == {"decision", "money", "tracker", "job", "notice"}
    assert cards.rejected == []


def test_missing_cards_dir_is_empty_not_an_error(validator: CardValidator, tmp_path) -> None:  # type: ignore[no-untyped-def]
    cards = load_cards(tmp_path / "nope", validator)
    assert cards.edition == [] and cards.pending == []


def test_plain_text_strips_markdown() -> None:
    md = "## Title\n**Bold** and *soft* with `code`.\n- a [link](http://x.y)\n1. item"
    assert plain_text(md) == "Title Bold and soft with code. a link item"


def test_say_is_two_sentences() -> None:
    assert say_text("One. Two? Three! Four.") == "One. Two?"
    assert say_text("¿Qué hora es? Son las tres. Y algo más.") == "¿Qué hora es? Son las tres."
    assert say_text("No full stop at all") == "No full stop at all"


def test_say_is_capped() -> None:
    assert len(say_text("word " * 200)) <= 320


def test_title_comes_from_the_question() -> None:
    assert title_from_question("what is a metaphor?") == "What is a metaphor?"
    long = title_from_question("tell me " * 30)
    assert len(long) <= 60 and long.endswith("…")


def test_short_answer_card(validator: CardValidator) -> None:
    card = answer_card("what?", "Short **answer**.", "en", "America/Chicago")
    validator.check(card)
    assert card["body"] == "Short answer." and "footer" not in card
    assert card["id"].startswith("ans-") and card["source"] == "dex"


@pytest.mark.parametrize("language", ["en", "es"])
def test_long_answer_card_is_truncated(validator: CardValidator, language: str) -> None:
    card = answer_card("q", "palabra " * 100, language, "America/Chicago")
    validator.check(card)
    assert len(card["body"].split()) <= 60 and card["body"].endswith("…")
    assert card["footer"] == (
        "Resumida. Pídele a Dex el resto."
        if language == "es"
        else "Shortened. Ask Dex for the rest."
    )


def test_answer_card_char_cap(validator: CardValidator) -> None:
    card = answer_card("q", " ".join(["supercalifragilistic"] * 59), "en", "America/Chicago")
    validator.check(card)
    assert len(card["body"]) <= 420 and "footer" in card


def test_encode_enforces_text_frame_limit() -> None:
    with pytest.raises(p.FrameTooLarge):
        p.encode({"type": "card", "blob": "x" * 9000})


def test_state_and_error_builders_follow_the_contract() -> None:
    with pytest.raises(ValueError):
        p.state("offline")  # the server never sends offline
    with pytest.raises(ValueError):
        p.error("oops", "x")
    assert p.state("working", agent="dex") == {"type": "state", "value": "working", "agent": "dex"}


def test_chunk_pcm() -> None:
    frames = p.chunk_pcm(bytes(10_000))
    assert [len(f) for f in frames] == [4096, 4096, 1808]
    assert p.chunk_pcm(b"") == []


# --- sentence splitting (streamed speech) ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("It costs 3.50 dollars. Then it rises.", ["It costs 3.50 dollars.", "Then it rises."]),
        ("Pi is about 3.14159. Nice.", ["Pi is about 3.14159.", "Nice."]),
        ("Dr. Smith agrees. Mrs. Lee does not.", ["Dr. Smith agrees.", "Mrs. Lee does not."]),
        ("Use e.g. a kettle. Or i.e. hot water.", ["Use e.g. a kettle.", "Or i.e. hot water."]),
        ("The U.S. economy grew. Stocks rose.", ["The U.S. economy grew.", "Stocks rose."]),
        ("J. R. R. Tolkien wrote it. Read it.", ["J. R. R. Tolkien wrote it.", "Read it."]),
        ("Meet at 5 p.m. today. Bring tea.", ["Meet at 5 p.m. today.", "Bring tea."]),
        ('He said "go." Then left.', ['He said "go."', "Then left."]),
        ("Wait... Really? Yes!", ["Wait...", "Really?", "Yes!"]),
        ("Cuesta 1.200 pesos. Es barato.", ["Cuesta 1.200 pesos.", "Es barato."]),
        ("El Sr. Pérez llegó. La Sra. Gómez no.", ["El Sr. Pérez llegó.", "La Sra. Gómez no."]),
        ("Vive en EE. UU. desde 2010. Le gusta.", ["Vive en EE. UU. desde 2010.", "Le gusta."]),
        ("¿Qué hora es? Son las 3.5 h. ¡Tarde!", ["¿Qué hora es?", "Son las 3.5 h.", "¡Tarde!"]),
        ("Dijo que sí. no lo creo.", ["Dijo que sí. no lo creo."]),  # lowercase: not a break
    ],
)
def test_sentences_en_es(text: str, expected: list[str]) -> None:
    assert sentences(text) == expected


def test_streaming_sentences_wait_for_the_next_word() -> None:
    assert sentences("It is 3.", final=False) == []  # "3." may be "3.5"
    assert sentences("It is 3.5 km. ", final=False) == []  # the next word may be lowercase
    assert sentences("It is 3.5 km. N", final=False) == ["It is 3.5 km."]
    assert sentences("Ask Dr. ", final=False) == []


@pytest.mark.parametrize(
    "answer",
    [
        "A metaphor says one thing is another. He is a lion. It commits harder.",
        "El Dr. Ruiz mide 1.75 m en EE. UU. ¿Y tú? ¡Yo no!",
        "**Short** answer: yes. The *rest* is `details`. More.",
        "No full stop at all",
        "One very long sentence " + "with many words " * 40 + "ends here. Two.",
        "Wait... Really? Yes!",
    ],
)
@pytest.mark.parametrize("chunk", [1, 3, 7, 1000])
def test_streamed_speech_equals_say_text(answer: str, chunk: int) -> None:
    splitter = SpeechSplitter()
    spoken: list[str] = []
    for i in range(0, len(answer), chunk):
        spoken += splitter.feed(answer[i : i + chunk])
    spoken += splitter.finish()
    assert " ".join(spoken) == say_text(answer)
    assert len(spoken) <= 2


def test_speech_splitter_emits_the_first_sentence_early() -> None:
    splitter = SpeechSplitter()
    assert splitter.feed("First one. ") == []
    assert splitter.feed("Second") == ["First one."]
    assert splitter.feed(" one. Third. Fourth.") == ["Second one."]
    assert splitter.finish() == []
