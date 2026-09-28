"""Dex + Coach over the real WebSocket server, with fakes for both channels (PROTOCOL § Agents)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from charm_server.agent import AgentError
from charm_server.cards import CardValidator
from charm_server.coach import CoachDesk, LedgerError, coach_persona

from .conftest import FakeAgent, FakeSTT, FakeTTS, Harness, fake, texts, tone, types
from .test_coach import CALL_REPLY, LEDGER

TZ = "America/Lima"
QUESTION = "Coach, should I start Purdy or Maye?"


@dataclass
class FakeLedger:
    text: str = LEDGER
    error: str | None = None
    reads: int = 0

    async def tail(self) -> str:
        self.reads += 1
        if self.error:
            raise LedgerError(self.error)
        return self.text


@dataclass
class Coach:
    agent: FakeAgent
    tts: FakeTTS
    ledger: FakeLedger
    desk: CoachDesk


@pytest.fixture
def coach(harness: Harness, validator: CardValidator, tmp_path: Path) -> Coach:
    agent = FakeAgent(reply_text=CALL_REPLY, delay=0.3)
    ledger = FakeLedger()
    desk = CoachDesk(
        agent,
        TZ,
        path=tmp_path / ".local" / "coach-jobs.json",
        ledger=ledger,
        validate=validator.check,
    )
    tts = FakeTTS(pcm=tone(0.3))
    harness.with_deps(coach=desk, coach_tts=tts)
    return Coach(agent, tts, ledger, desk)


def ask(harness: Harness, text: str, language: str = "en") -> None:
    stt, _, _ = fake(harness.deps)
    stt.text, stt.language = text, language


def states(frames: list[dict[str, Any] | bytes]) -> list[dict[str, Any]]:
    return [f for f in texts(frames) if f["type"] == "state"]


def cards(frames: list[dict[str, Any] | bytes]) -> list[dict[str, Any]]:
    return [f["card"] for f in texts(frames) if f["type"] == "card"]


def result(frames: list[dict[str, Any] | bytes]) -> dict[str, Any]:
    """Coach's latest result card among `frames` (not the "on it" job card)."""
    return [c for c in cards(frames) if c["kind"] != "job"][-1]


async def test_a_coach_question_is_a_walk_away_job(harness: Harness, coach: Coach) -> None:
    ask(harness, QUESTION)
    _, dex, dex_tts = fake(harness.deps)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    frames = await dev.until(lambda m: m["type"] == "card")
    assert types(frames) == ["state:transcribing", "transcript", "mode", "state:working", "card"]
    msgs = texts(frames)
    assert msgs[2] == {"type": "mode", "value": "default", "agent": "coach"}
    assert msgs[3] == {
        "type": "state",
        "value": "working",
        "label": "Coach is on it",
        "agent": "coach",
    }
    job = msgs[4]["card"]
    assert (job["kind"], job["source"], job["data"]) == ("job", "coach", {"status": "running"})

    # … minutes later: the call, the job card dismissed, attention. No speech, no ping.
    later = await dev.until(lambda m: m.get("value") == "attention")
    assert types(later) == ["card", "dismiss", "state:attention"]
    call = texts(later)[0]["card"]
    assert call["kind"] == "decision" and call["source"] == "coach"
    assert call["data"]["default"] == "Start Purdy" and call["data"]["flip_if"]
    assert texts(later)[1] == {"type": "dismiss", "card_id": job["id"]}
    assert texts(later)[2] == {"type": "state", "value": "attention", "agent": "coach"}
    assert await dev.silent_for(0.3) == []
    assert coach.tts.calls == [] and dex_tts.calls == []

    # Coach got his persona and the question without the wake word; Dex got nothing.
    [messages] = coach.agent.calls
    assert messages[0] == {"role": "system", "content": coach_persona(tz=TZ)}
    assert messages[-1] == {"role": "user", "content": "Should I start Purdy or Maye?"}
    assert dex.calls == []


async def test_hear_speaks_the_call_in_coachs_voice(harness: Harness, coach: Coach) -> None:
    ask(harness, QUESTION)
    _, _, dex_tts = fake(harness.deps)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    call = result(await dev.until(lambda m: m.get("value") == "attention"))
    await dev.send({"type": "action", "card_id": call["id"], "action": "hear"})
    frames = await dev.until_idle(agent="coach")
    assert types(frames) == ["state:speaking", "speech_start", "<pcm>", "speech_end", "state:idle"]
    assert texts(frames)[0] == {"type": "state", "value": "speaking", "agent": "coach"}
    assert texts(frames)[1]["card_id"] == call["id"]
    assert coach.tts.calls == [
        (
            "Keep Purdy in. Maye has one touchdown and six picks through three games, and "
            "Buffalo is unbeaten.",
            "en",
        )
    ]
    assert dex_tts.calls == []


async def test_why_starts_a_follow_up_job(harness: Harness, coach: Coach) -> None:
    ask(harness, QUESTION)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    call = result(await dev.until(lambda m: m.get("value") == "attention"))
    coach.agent.reply_text = "Maye's six picks are the whole story."
    await dev.send({"type": "action", "card_id": call["id"], "action": "why"})
    frames = await dev.until(lambda m: m["type"] == "card")
    assert types(frames) == ["state:working", "card"]
    assert cards(frames)[0]["kind"] == "job"
    answer = result(await dev.until(lambda m: m.get("value") == "attention"))
    assert answer["kind"] == "answer" and answer["body"] == "Maye's six picks are the whole story."
    why = coach.agent.calls[1]
    assert why[-1]["content"].startswith("Why? Give me the reasoning behind your call: Start Purdy")
    assert any(m["role"] == "assistant" for m in why)  # his own call is in his history


async def test_later_dismisses_quietly(harness: Harness, coach: Coach) -> None:
    ask(harness, QUESTION)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    call = result(await dev.until(lambda m: m.get("value") == "attention"))
    await dev.send({"type": "action", "card_id": call["id"], "action": "later"})
    frames = await dev.until_idle(agent="coach")
    assert texts(frames)[0] == {"type": "dismiss", "card_id": call["id"]}
    assert coach.tts.calls == []


@pytest.mark.parametrize(
    ("change", "wording"),
    [
        ({"delay": 5.0}, "Coach didn't answer within"),
        ({"error": AgentError("Hermes returned HTTP 502.")}, "Hermes returned HTTP 502."),
        ({"reply_text": "   "}, "empty answer"),
    ],
)
async def test_a_failed_job_replaces_the_job_card_with_an_honest_notice(
    harness: Harness, coach: Coach, change: dict[str, Any], wording: str
) -> None:
    coach.desk.timeout = 0.3 if "delay" in change else 5.0
    for key, value in change.items():
        setattr(coach.agent, key, value)
    ask(harness, QUESTION)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    job = cards(await dev.until(lambda m: m["type"] == "card"))[0]
    frames = await dev.until(lambda m: m.get("value") == "attention", timeout=5)
    assert types(frames) == ["card", "state:attention"]
    notice = cards(frames)[0]
    assert notice["id"] == job["id"] and notice["kind"] == "notice"
    assert wording in notice["body"] and "No call was made" in notice["body"]
    assert all(c["kind"] != "decision" for c in cards(frames))


async def test_the_result_waits_for_a_device_that_walked_away(
    harness: Harness, coach: Coach
) -> None:
    ask(harness, QUESTION)
    first = await harness.device()
    await first.talk(tone(1.0))
    job = cards(await first.until(lambda m: m["type"] == "card"))[0]
    await first.ws.close()  # put it down, pocket it, lose Wi-Fi…

    # Reconnect while he's still working: the job card is back, and so is "on it".
    again = await harness.device()
    frames = await again.until(lambda m: m.get("value") == "working")
    assert types(frames) == ["mode", "card", "state:working"]
    assert texts(frames)[0]["agent"] == "coach" and cards(frames)[0]["id"] == job["id"]
    await again.ws.close()

    await coach.desk._tasks[job["id"]]  # he finishes while nobody is connected
    assert [d.displayed for d in coach.desk.results] == [False]

    back = await harness.device()
    frames = await back.until(lambda m: m.get("value") == "attention")
    assert types(frames) == ["mode", "card", "dismiss", "state:attention"]
    call = cards(frames)[0]
    assert call["kind"] == "decision" and texts(frames)[2]["card_id"] == job["id"]
    await back.send({"type": "displayed", "id": call["id"]})
    await back.send({"type": "ping"})
    await back.until(lambda m: m["type"] == "pong")
    await back.ws.close()

    # Shown once: the next connection starts clean.
    last = await harness.device()
    assert await last.silent_for(0.3) == []


async def test_one_coach_job_at_a_time(harness: Harness, coach: Coach) -> None:
    coach.agent.delay = 2.0
    ask(harness, QUESTION)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m["type"] == "card")
    await dev.talk(tone(1.0))
    frames = await dev.until_idle(agent="coach")
    assert [m["code"] for m in texts(frames) if m["type"] == "error"] == ["busy"]
    assert len(coach.agent.calls) == 1


async def test_dex_answers_while_coach_works(harness: Harness, coach: Coach) -> None:
    coach.agent.delay = 1.0
    ask(harness, QUESTION)
    _, dex, dex_tts = fake(harness.deps)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m["type"] == "card")
    ask(harness, "What is a metaphor?")
    await dev.talk(tone(1.0))
    frames = await dev.until_idle()
    msgs = texts(frames)
    assert msgs[2] == {"type": "mode", "value": "default", "agent": "dex"}
    assert msgs[3] == {"type": "state", "value": "working", "agent": "dex"}
    assert len(dex.calls) == 1 and dex_tts.calls and coach.tts.calls == []
    # Dex's history never carries Coach's turns, and the other way round.
    assert all(m["content"] != QUESTION for m in dex.calls[0])
    later = await dev.until(lambda m: m.get("value") == "attention", timeout=5)
    assert texts(later)[0] == {"type": "mode", "value": "default", "agent": "coach"}


async def test_coach_disabled_is_an_honest_notice(harness: Harness) -> None:
    ask(harness, QUESTION)
    _, dex, _ = fake(harness.deps)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    frames = await dev.until_idle()
    assert types(frames) == ["state:transcribing", "transcript", "card", "state:idle"]
    notice = cards(frames)[0]
    assert notice["kind"] == "notice" and notice["title"] == "Coach isn't connected"
    assert dex.calls == []


async def test_the_fast_path_reads_his_ledger(harness: Harness, coach: Coach) -> None:
    ask(harness, "What's Coach's latest call?")
    dev = await harness.device()
    await dev.talk(tone(1.0))
    frames = await dev.until_idle(agent="coach")
    assert types(frames) == [
        "state:transcribing",
        "transcript",
        "mode",
        "state:working",
        "card",
        "state:speaking",
        "speech_start",
        "<pcm>",
        "speech_end",
        "state:idle",
    ]
    call = cards(frames)[0]
    assert call["id"] == "coach-call-c41867dcd08117b6" and call["source"] == "coach"
    assert call["footer"].startswith("Called ") and call["footer"].endswith("ago")
    assert coach.agent.calls == [] and coach.ledger.reads == 1  # no fresh run
    assert coach.tts.calls and coach.tts.calls[0][0].startswith("The one lineup decision")


async def test_the_fast_path_in_spanish(harness: Harness, coach: Coach) -> None:
    ask(harness, "¿Cuál es la última jugada de Coach?", "es")
    dev = await harness.device()
    await dev.talk(tone(1.0))
    call = cards(await dev.until_idle(agent="coach"))[0]
    assert call["title"] == "Semana 4: alineación" and call["footer"].startswith("Jugada: hace")
    assert coach.tts.calls[0][1] == "es"


@pytest.mark.parametrize(
    ("ledger", "title"),
    [
        (FakeLedger(text='{"call": "draft", "delivered": false}'), "No call on file"),
        (FakeLedger(error="the ledger read timed out"), "Couldn't read his ledger"),
    ],
)
async def test_the_fast_path_says_so_when_there_is_nothing(
    harness: Harness, coach: Coach, ledger: FakeLedger, title: str
) -> None:
    coach.desk.ledger = ledger
    ask(harness, "What's Coach's latest call?")
    dev = await harness.device()
    await dev.talk(tone(1.0))
    frames = await dev.until_idle(agent="coach")
    [notice] = cards(frames)
    assert notice["kind"] == "notice" and notice["title"] == title
    assert "<pcm>" not in types(frames) and coach.agent.calls == []


async def test_every_state_names_the_agent(harness: Harness, coach: Coach) -> None:
    ask(harness, QUESTION)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    frames = await dev.until(lambda m: m.get("value") == "attention")
    ask(harness, "What is a metaphor?")
    await dev.talk(tone(1.0))
    frames += await dev.until_idle()
    assert states(frames) and all(s["agent"] in ("dex", "coach") for s in states(frames))
    assert [s["agent"] for s in states(frames)][-1] == "dex"


async def test_routing_logs_the_agent_never_the_words(
    harness: Harness, coach: Coach, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="charm_server.session")
    ask(harness, QUESTION)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m["type"] == "card")
    routes = [r.getMessage() for r in caplog.records if r.getMessage().startswith("route ")]
    assert routes == ["route coach (wake)"]
    assert not any("Purdy" in r.getMessage() for r in caplog.records)


async def test_pending_includes_coachs_cards(harness: Harness, coach: Coach) -> None:
    ask(harness, QUESTION)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    call = result(await dev.until(lambda m: m.get("value") == "attention"))
    await dev.ws.close()
    other = await harness.device()
    await other.until(lambda m: m.get("value") == "attention")  # redelivered: never displayed
    await other.send({"type": "request", "what": "pending"})
    frames = await other.until(lambda m: m.get("value") == "attention")
    assert call["id"] in [c["id"] for c in cards(frames)]
    await other.send({"type": "action", "card_id": call["id"], "action": "hear"})
    assert "speech_start" in types(await other.until_idle(agent="coach"))


def test_fakes_are_distinct(harness: Harness, coach: Coach) -> None:
    assert isinstance(harness.deps.stt, FakeSTT)
    assert harness.deps.tts is not coach.tts
