"""Rule-based reading intents, EN + ES, on Whisper-style transcripts. No model call."""

from __future__ import annotations

import pytest

from charm_server.intents import (
    EnterReading,
    LeaveReading,
    SaveThought,
    SetChapter,
    SetSpeech,
    chapter_name,
    parse,
)

# --- enter reading --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "I'm reading Superforecasting by Philip Tetlock, chapter 3.",
            EnterReading("Superforecasting", "Philip Tetlock", "3"),
        ),
        ("I'm reading Superforecasting, chapter 3", EnterReading("Superforecasting", None, "3")),
        ("I'm reading Superforecasting.", EnterReading("Superforecasting")),
        ("I am reading Thinking, Fast and Slow.", EnterReading("Thinking, Fast and Slow")),
        (
            "Hey Dex, I'm reading The Left Hand of Darkness by Ursula K. Le Guin. Chapter four.",
            EnterReading("The Left Hand of Darkness", "Ursula K. Le Guin", "4"),
        ),
        (
            "I just started Middlemarch by George Eliot",
            EnterReading("Middlemarch", "George Eliot"),
        ),
        ("I'm now reading Dune and I'm on chapter 12.", EnterReading("Dune", None, "12")),
        ("I\u2019m reading \u201cDune\u201d, chapter 2", EnterReading("Dune", None, "2")),
        ("Let's read the book Walden", EnterReading("Walden")),
        (
            "Estoy leyendo Cien años de soledad, capítulo 3.",
            EnterReading("Cien años de soledad", None, "3"),
        ),
        (
            "Estoy leyendo Cien años de soledad de Gabriel García Márquez, capítulo tres",
            EnterReading("Cien años de soledad", "Gabriel García Márquez", "3"),
        ),
        (
            "Estoy leyendo Ficciones por Borges",
            EnterReading("Ficciones", "Borges"),
        ),
        ("Empecé a leer El túnel, capítulo 1", EnterReading("El túnel", None, "1")),
        (
            "Estoy leyendo el libro Rayuela y voy en el capítulo 7",
            EnterReading("Rayuela", None, "7"),
        ),
        ("estoy leyendo la casa de los espíritus", EnterReading("La casa de los espíritus")),
    ],
)
def test_enter_reading(text: str, expected: EnterReading) -> None:
    assert parse(text, reading=False) == expected
    assert parse(text, reading=True) == expected  # switching books works from reading mode too


@pytest.mark.parametrize(
    "text",
    [
        "I'm reading about inflation.",
        "I'm reading up on Roman history",
        "I'm reading the news",
        "I'm reading Superforecasting, what does the author mean by foxes?",
        "Estoy leyendo sobre la inflación.",
        "¿Estoy leyendo bien este capítulo?",
        "I'm reading chapter 4",  # a chapter with no book: a question outside reading mode
        "What is a metaphor?",
        "I'm reading this. It is long. Really long.",
    ],
)
def test_not_enter_reading(text: str) -> None:
    assert parse(text, reading=False) is None


# --- chapter updates ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "chapter"),
    [
        ("Chapter 4", "4"),
        ("chapter four.", "4"),
        ("I'm on chapter 5 now.", "5"),
        ("I'm starting chapter 6", "6"),
        ("Moving on to chapter 10.", "10"),
        ("Now chapter IX", "IX"),
        ("Voy en el capítulo 4.", "4"),
        ("Estoy en el capítulo cinco", "5"),
        ("Capítulo 12", "12"),
        ("Ahora capítulo dos.", "2"),
    ],
)
def test_chapter_update_in_reading_mode(text: str, chapter: str) -> None:
    assert parse(text, reading=True) == SetChapter(chapter)


def test_chapter_update_means_nothing_outside_reading() -> None:
    assert parse("I'm on chapter 5 now.", reading=False) is None
    assert parse("Voy en el capítulo 4.", reading=False) is None


@pytest.mark.parametrize(
    "text",
    ["What happens in chapter 4?", "Chapter 4 was confusing, why did she leave?", "Chapter banana"],
)
def test_chapter_questions_stay_questions(text: str) -> None:
    assert parse(text, reading=True) is None


@pytest.mark.parametrize(
    ("word", "name"),
    [("3", "3"), ("03", "3"), ("three", "3"), ("tres", "3"), ("iv", "IV"), ("xii", "XII")],
)
def test_chapter_names(word: str, name: str) -> None:
    assert chapter_name(word) == name


def test_chapter_name_rejects_words() -> None:
    assert chapter_name("banana") is None
    assert chapter_name("") is None


# --- leave reading --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Stop reading.",
        "stop reading mode",
        "I'm done reading for today.",
        "Okay Dex, exit reading mode.",
        "Close the book.",
        "Deja de leer.",
        "Terminé de leer por hoy.",
        "Sal del modo lectura, por favor.",
        "Ya no estoy leyendo",
    ],
)
def test_leave_reading(text: str) -> None:
    assert parse(text, reading=True) == LeaveReading()
    assert parse(text, reading=False) == LeaveReading()  # harmless: the server just confirms


@pytest.mark.parametrize(
    "text", ["Why did he stop reading the letter?", "¿Por qué deja de leer la carta?"]
)
def test_leave_words_inside_questions(text: str) -> None:
    assert parse(text, reading=True) is None


# --- save this ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "saved"),
    [
        (
            "Save this: Foxes win because they change their minds.",
            "Foxes win because they change their minds.",
        ),
        ("Save this. foxes know many things", "foxes know many things"),
        ("save this thought, the map is not the territory", "the map is not the territory"),
        ("Hey Dex, save this: Beliefs are hypotheses.", "Beliefs are hypotheses."),
        ("Please save this — slow down to go fast", "slow down to go fast"),
        ("Note this: stop reading is not a command here", "stop reading is not a command here"),
        ("Guarda esto: la memoria es un río.", "la memoria es un río."),
        ("Guarda esta idea. El tiempo es circular", "El tiempo es circular"),
        ("Anota esto, capítulo 4 es el mejor", "capítulo 4 es el mejor"),
        ("Save this:   Voice on, said nobody.  ", "Voice on, said nobody."),
        ("Save this", ""),
        ("Guarda esto.", ""),
    ],
)
def test_save_is_verbatim_minus_the_trigger(text: str, saved: str) -> None:
    assert parse(text, reading=True) == SaveThought(saved)
    assert parse(text, reading=False) == SaveThought(saved)


@pytest.mark.parametrize(
    "text",
    [
        "Should I save this for later?",
        "How do I save thistles from frost?",
        "Saved this morning: nothing.",
        "¿Guardas esto?",
    ],
)
def test_not_save(text: str) -> None:
    assert not isinstance(parse(text, reading=True), SaveThought)


def test_save_keeps_casing_and_inner_punctuation() -> None:
    text = 'Save this: "Foxes" WIN — because (they) change; their minds!'
    assert parse(text, reading=False) == SaveThought(
        '"Foxes" WIN — because (they) change; their minds!'
    )


# --- speech on / off ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Voice on.", "on"),
        ("Speech off", "off"),
        ("Turn the voice on, please.", "on"),
        ("Turn off the sound", "off"),
        ("Be quiet.", "off"),
        ("Dex, quiet mode", "off"),
        ("Talk to me.", "on"),
        ("Read answers out loud", "on"),
        ("Activa la voz.", "on"),
        ("Desactiva la voz", "off"),
        ("Silencio, por favor.", "off"),
        ("Solo texto", "off"),
        ("Lee en voz alta", "on"),
    ],
)
def test_speech_toggle(text: str, value: str) -> None:
    assert parse(text, reading=True) == SetSpeech(value)
    assert parse(text, reading=False) == SetSpeech(value)


@pytest.mark.parametrize(
    "text",
    [
        "Why is the narrator so quiet in this chapter?",
        "What does the voice in chapter 2 represent?",
        "¿Por qué el personaje habla tan poco?",
    ],
)
def test_speech_words_inside_questions(text: str) -> None:
    assert parse(text, reading=True) is None


def test_empty_is_a_question() -> None:
    assert parse("   ", reading=True) is None
