"""Coach's pieces without a server: reply parsing, cards, the ledger, the job desk, the channel."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from charm_server.agent import AgentError
from charm_server.cards import CardValidator
from charm_server.coach import (
    COACH_PERSONA,
    CoachDesk,
    ContainerLedger,
    Delivery,
    LedgerError,
    age_text,
    coach_messages,
    failed_card,
    job_card,
    latest_delivered,
    ledger_card,
    result_card,
    split_call,
)
from charm_server.config import Config
from charm_server.hermes import COACH_ENV_FILE, COACH_PORT, ssh_command, worker_script

from .conftest import FakeAgent

TZ = "America/Lima"

CALL_REPLY = (
    "Keep Purdy in. Maye has one touchdown and six picks through three games, and Buffalo is "
    "unbeaten.\nCALL: Start Purdy | BY: Sun 12:00 | FLIP: Purdy gets an injury designation"
)

LEDGER = "\n".join(
    [
        json.dumps(
            {
                "call": "Add Keon Coleman; drop the Giants D/ST.",
                "decided_at": "2026-09-27T12:00:00+00:00",
                "deadline": "2026-09-30T02:00:00-05:00",
                "delivered": True,
                "decision_id": "older",
                "kind": "waiver",
                "week": 4,
            }
        ),
        json.dumps(
            {
                "call": "The one lineup decision is Brock Purdy versus Drake Maye; keep Purdy in.",
                "deadline": "2026-10-04T12:00:00-05:00",
                "decided_at": "2026-09-28T16:37:15.705959+00:00",
                "decision_id": "c41867dcd08117b6",
                "delivered": True,
                "flip_condition": "Start Maye only if Purdy receives a material injury "
                "designation before Maye locks.",
                "kind": "lineup",
                "week": 4,
            }
        ),
        json.dumps({"call": "A silent draft", "decided_at": "2026-09-28T18:00:00+00:00"}),
        "not json at all",
    ]
)


# --- the reply ------------------------------------------------------------------------------


def test_split_call_parses_and_removes_the_verdict_line() -> None:
    body, verdict = split_call(CALL_REPLY)
    assert "CALL" not in body and body.startswith("Keep Purdy in.")
    assert verdict is not None
    assert verdict.default == "Start Purdy"
    assert verdict.deadline == "Sun 12:00"
    assert verdict.flip_if == "Purdy gets an injury designation"


def test_split_call_without_a_verdict_is_an_answer() -> None:
    assert split_call("Purdy plays Denver at home on Sunday.") == (
        "Purdy plays Denver at home on Sunday.",
        None,
    )
    body, verdict = split_call("Take the Bills.\ncall: Bills D/ST")
    assert body == "Take the Bills."
    assert verdict is not None and verdict.default == "Bills D/ST" and verdict.deadline is None


def test_result_card_is_a_valid_call(validator: CardValidator) -> None:
    card, say = result_card("should I start Purdy or Maye?", CALL_REPLY, "en", TZ)
    validator.check(card)
    assert card["kind"] == "decision" and card["source"] == "coach"
    assert card["data"] == {
        "default": "Start Purdy",
        "deadline": "Sun 12:00",
        "flip_if": "Purdy gets an injury designation",
    }
    assert [a["id"] for a in card["actions"]] == ["hear", "why", "later"]
    assert card["title"] == "Should I start Purdy or Maye?"
    assert say == (
        "Keep Purdy in. Maye has one touchdown and six picks through three games, and Buffalo "
        "is unbeaten."
    )
    assert "CALL" not in card["body"]


def test_result_card_without_a_verdict_is_a_coach_answer(validator: CardValidator) -> None:
    reply = " ".join(f"Sentence {i} about the slate." for i in range(30))
    card, say = result_card("How's the slate?", reply, "es", TZ)
    validator.check(card)
    assert card["kind"] == "answer" and card["source"] == "coach"
    assert [a["id"] for a in card["actions"]] == ["hear", "later"]
    assert card["footer"] == "Resumida. Pídele a Coach el resto."
    assert say == "Sentence 0 about the slate. Sentence 1 about the slate."


def test_long_verdict_fields_are_clipped_to_the_contract(validator: CardValidator) -> None:
    reply = "Go.\nCALL: " + "word " * 20 + "| BY: " + "late " * 20 + "| FLIP: " + "if " * 60
    card, _ = result_card("q", reply, "en", TZ)
    validator.check(card)
    assert len(card["data"]["default"]) <= 40 and len(card["data"]["flip_if"]) <= 80


def test_job_and_failed_cards_are_valid(validator: CardValidator) -> None:
    job = validator.check(job_card("coach-job-1", "Should I start Purdy?", "en", TZ))
    assert job["title"] == "Coach is on it" and job["data"] == {"status": "running"}
    failed = validator.check(failed_card("coach-job-1", "Coach timed out.", "en", TZ))
    assert failed["id"] == "coach-job-1" and failed["kind"] == "notice"
    assert "No call was made" in failed["body"]


def test_the_persona_is_read_only_and_short() -> None:
    messages = coach_messages("es", [])
    assert messages[0]["content"] == COACH_PERSONA
    assert "read-only" in COACH_PERSONA and "never set a lineup" in COACH_PERSONA
    assert "Spanish" in messages[1]["content"]


# --- the ledger -----------------------------------------------------------------------------


def test_latest_delivered_skips_undelivered_and_garbage() -> None:
    entry = latest_delivered(LEDGER)
    assert entry is not None and entry.decision_id == "c41867dcd08117b6"
    assert entry.kind == "lineup" and entry.week == 4
    assert latest_delivered("") is None
    assert latest_delivered('{"call": "x", "delivered": false}') is None


def test_ledger_card_shows_the_age_and_the_deadline(validator: CardValidator) -> None:
    entry = latest_delivered(LEDGER)
    assert entry is not None
    now = entry.decided_at + timedelta(hours=3, minutes=5)
    card = validator.check(ledger_card(entry, "en", TZ, now))
    assert card["id"] == "coach-call-c41867dcd08117b6"
    assert card["title"] == "Week 4 lineup"
    assert card["footer"] == "Called 3 h ago"
    assert card["data"]["default"] == "Keep Purdy in"
    assert card["data"]["deadline"] == "Sun 12:00"
    assert card["data"]["flip_if"].startswith("Start Maye only if Purdy")
    assert card["created_at"].startswith("2026-09-28T11:37:15-05:00")
    assert "stale" not in card


def test_ledger_card_past_its_deadline_is_stale(validator: CardValidator) -> None:
    entry = latest_delivered(LEDGER)
    assert entry is not None
    card = validator.check(ledger_card(entry, "es", TZ, datetime(2026, 10, 6, tzinfo=UTC)))
    assert card["stale"] is True
    assert card["footer"] == "Jugada: hace 7 d · ya pasó la hora"
    assert card["data"]["deadline"] == "Dom 12:00"


def test_age_text() -> None:
    assert age_text(20, "en") == "<1 min ago"
    assert age_text(600, "en") == "10 min ago"
    assert age_text(5 * 3600, "es") == "Hace 5 h"
    assert age_text(3 * 86400, "en") == "3 d ago"


async def test_container_ledger_is_a_read_only_tail() -> None:
    ledger = ContainerLedger("hermes", "hermes-agent", "/opt/x/decisions.jsonl")
    command = ledger._command()
    assert command[0] == "ssh" and command[-2] == "hermes"
    assert command[-1] == ("docker exec hermes-agent tail -n 200 /opt/x/decisions.jsonl")
    local = ContainerLedger("local", "c", "/p")._command()
    assert local == ["docker", "exec", "c", "tail", "-n", "200", "/p"]
    ok = ContainerLedger("x", "c", "/p", command=[sys.executable, "-c", "print('line')"])
    assert (await ok.tail()).strip() == "line"
    bad = ContainerLedger("x", "c", "/p", command=[sys.executable, "-c", "raise SystemExit(1)"])
    with pytest.raises(LedgerError):
        await bad.tail()


# --- Coach's channel: same transport, his key file and port ------------------------------------


def test_coach_worker_reads_his_key_inside_the_container_and_calls_8644() -> None:
    script = worker_script(COACH_ENV_FILE, COACH_PORT, "Coach")
    assert "'/opt/data/profiles/coach/.env'" in script
    assert "'http://127.0.0.1:8644/v1/chat/completions'" in script
    assert "'Coach sent an empty answer.'" in script
    assert "8642" not in script and "'/opt/data/.env'" not in script
    command = ssh_command("local", "c", COACH_ENV_FILE, COACH_PORT, "Coach")
    assert command[:4] == ["docker", "exec", "-i", "c"]


def test_config_reads_the_coach_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COACH_ENABLED", "0")
    monkeypatch.setenv("COACH_ENV_PATH", "/opt/data/profiles/other/.env")
    monkeypatch.setenv("COACH_PORT", "8650")
    monkeypatch.setenv("CHARM_VOICE_COACH_EN", "en-US-EricNeural")
    config = Config.from_env(env_file=None)
    assert config.coach_enabled is False
    assert (config.coach_env_path, config.coach_port) == ("/opt/data/profiles/other/.env", 8650)
    assert config.coach_voice_en == "en-US-EricNeural"
    for name in ("COACH_ENABLED", "COACH_ENV_PATH", "COACH_PORT", "CHARM_VOICE_COACH_EN"):
        monkeypatch.delenv(name)
    config = Config.from_env(env_file=None)
    assert config.coach_enabled is False  # an optional second agent: off unless switched on
    assert (config.coach_env_path, config.coach_port) == ("/opt/data/profiles/coach/.env", 8644)
    assert config.coach_voice_en != config.voice_en and config.coach_voice_es != config.voice_es


# --- the desk -------------------------------------------------------------------------------


async def test_a_result_is_persisted_before_it_is_offered(
    tmp_path: Path, validator: CardValidator
) -> None:
    path = tmp_path / ".local" / "coach-jobs.json"
    desk = CoachDesk(FakeAgent(reply_text=CALL_REPLY), TZ, path=path, validate=validator.check)
    got: list[Delivery] = []

    async def listener(delivery: Delivery) -> None:
        assert json.loads(path.read_text())["results"][-1]["card"] == delivery.card
        got.append(delivery)

    desk.attach(listener)
    job = desk.submit("Start Purdy?", "en")
    assert desk.busy and json.loads(path.read_text())["jobs"][0]["id"] == job["id"]
    await asyncio.sleep(0.05)
    assert not desk.busy and len(got) == 1 and got[0].ok
    again = CoachDesk(None, TZ, path=path)
    assert [d.card["id"] for d in again.undelivered()] == [got[0].card["id"]]
    again.mark_displayed(got[0].card["id"])
    assert CoachDesk(None, TZ, path=path).undelivered() == []


async def test_a_job_the_server_restart_interrupted_becomes_an_honest_notice(
    tmp_path: Path, validator: CardValidator
) -> None:
    path = tmp_path / "coach-jobs.json"
    desk = CoachDesk(FakeAgent(delay=30), TZ, path=path, validate=validator.check)
    job = desk.submit("Start Purdy?", "en")
    await desk.close()  # the server stops mid-job
    after = CoachDesk(None, TZ, path=path)
    [delivery] = after.undelivered()
    assert delivery.card["id"] == job["id"] and delivery.card["kind"] == "notice"
    assert "restarted" in delivery.card["body"] and not delivery.ok
    validator.check(delivery.card)


async def test_failures_are_notices_never_answers(validator: CardValidator) -> None:
    desk = CoachDesk(
        FakeAgent(error=AgentError("Hermes returned HTTP 502.")), TZ, validate=validator.check
    )
    desk.submit("Start Purdy?", "en")
    await asyncio.sleep(0.05)
    [delivery] = desk.results
    assert delivery.card["kind"] == "notice" and "HTTP 502" in delivery.card["body"]
    slow = CoachDesk(FakeAgent(delay=5), TZ, timeout=0.05, validate=validator.check)
    slow.submit("Start Purdy?", "es")
    await asyncio.sleep(0.2)
    [late] = slow.results
    assert late.card["title"] == "Coach no terminó" and "minutos" in late.card["body"]
    assert slow.agent is not None and slow.agent.finished == 0  # type: ignore[attr-defined]
