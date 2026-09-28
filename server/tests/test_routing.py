"""Dex vs Coach routing (PROTOCOL § Agents): wake words, fantasy/NFL topics, near-misses."""

from __future__ import annotations

import pytest

from charm_server.routing import COACH, DEX, route, strip_wake


@pytest.mark.parametrize(
    ("text", "question"),
    [
        ("Coach, should I start Purdy or Maye?", "Should I start Purdy or Maye?"),
        ("Coach Beard: any waiver adds this week?", "Any waiver adds this week?"),
        ("Hey coach, who do I drop?", "Who do I drop?"),
        ("coach should I bench Allen", "Should I bench Allen"),
        ("Entrenador, ¿pongo a Purdy o a Maye?", "¿pongo a Purdy o a Maye?"),
        ("Oye entrenador, ¿qué hago con mi banca?", "¿qué hago con mi banca?"),
        ("Coach, what do you think about the weather?", "What do you think about the weather?"),
    ],
)
def test_wake_word_goes_to_coach_without_the_wake_word(text: str, question: str) -> None:
    r = route(text)
    assert (r.agent, r.reason, r.question) == (COACH, "wake", question)
    assert not r.latest_call


@pytest.mark.parametrize(
    "text",
    [
        "Should I start Purdy or Maye this week?",
        "Who should I start at flex?",
        "Any waiver wire pickups worth it?",
        "Is my team projected to win this week?",
        "Start or sit Keenan Allen?",
        "Who won the NFL game last night?",
        "¿Cómo va mi equipo de fantasy?",
        "¿Quién debería ir en mi alineación?",
        "Should I trade my RB for a WR?",
        "Is Mahomes questionable for week 4?",
    ],
)
def test_clear_fantasy_or_nfl_questions_go_to_coach(text: str) -> None:
    r = route(text)
    assert (r.agent, r.reason, r.question) == (COACH, "topic", text)


@pytest.mark.parametrize(
    "text",
    [
        "Coach Carter is a great movie",  # "Coach" as a name, not an address
        "My coach says I should stretch more",  # "coach" inside a sentence
        "I told the coach we'd be late",
        "Should I start the meeting early?",
        "Any good fantasy novels for the flight?",
        "What is the trade deficit with China?",
        "How is my team doing on the project?",
        "Should I add bench press to my routine?",
        "My knee hurts, should I play tennis today?",
        "Can I drop the kids at school this week?",
        "What is a metaphor?",
        "Dex, what's your latest call?",
        "",
    ],
)
def test_near_misses_stay_with_dex(text: str) -> None:
    r = route(text)
    assert (r.agent, r.reason, r.question) == (DEX, "default", text)


@pytest.mark.parametrize(
    "text",
    [
        "What's Coach's latest call?",
        "What's Coaches latest call?",  # as Whisper heard it live, 2026-09-28
        "whats coachs latest call",
        "what is coach's last call",
        "Tell me Coach Beard's latest decision",
        "Coach, what's your latest call?",
        "¿Cuál es la última jugada de Coach?",
        "¿Cuál es la última jugada del entrenador?",
        "Entrenador, ¿cuál es tu última jugada?",
    ],
)
def test_the_fast_path(text: str) -> None:
    r = route(text)
    assert (r.agent, r.reason, r.latest_call) == (COACH, "latest", True)


def test_reading_mode_keeps_topics_with_dex_but_honours_the_wake_word() -> None:
    assert route("Why does the quarterback matter in this chapter?", reading=True).agent == DEX
    assert route("Coach, who do I start this week?", reading=True).agent == COACH


def test_strip_wake() -> None:
    assert strip_wake("Coach, hi") == "Hi"
    assert strip_wake("Coach Carter was great") is None
    assert strip_wake("Coach,") == ""
    assert strip_wake("I love my coach") is None
