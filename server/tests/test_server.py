"""The server side of docs/PROTOCOL.md, over a real localhost WebSocket with fake engines."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus

from charm_server import SERVER_ID
from charm_server.agent import AgentError
from charm_server.session import NO_REAL_ORDER_TEXT, SAMPLE_ORDER_TEXT

from .conftest import EXAMPLES, TOKEN, Client, FakeTTS, Harness, fake, texts, tone, types

# --- auth ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "first",
    [
        {"type": "hello", "device_id": "t", "fw": "x", "token": "wrong", "caps": []},
        {"type": "hello", "device_id": "t", "fw": "x", "caps": []},
        {"type": "ping"},
        "not json",
    ],
)
async def test_bad_or_missing_token_gets_auth_error_and_4401(
    harness: Harness, first: object
) -> None:
    ws = await harness.raw()
    await ws.send(first if isinstance(first, str) else json.dumps(first))
    reply = json.loads(await ws.recv())
    assert reply["type"] == "error" and reply["code"] == "auth"
    with pytest.raises(ConnectionClosed) as closed:
        await ws.recv()
    assert closed.value.rcvd is not None and closed.value.rcvd.code == 4401


async def test_binary_first_frame_is_refused(harness: Harness) -> None:
    ws = await harness.raw()
    await ws.send(b"\x00\x00")
    assert json.loads(await ws.recv())["code"] == "auth"
    with pytest.raises(ConnectionClosed) as closed:
        await ws.recv()
    assert closed.value.rcvd is not None and closed.value.rcvd.code == 4401


async def test_empty_server_token_refuses_everyone(harness: Harness) -> None:
    from dataclasses import replace

    harness.deps.config = replace(harness.deps.config, token="")
    ws = await harness.raw()
    await ws.send(json.dumps({"type": "hello", "token": "", "device_id": "t", "fw": "x"}))
    assert json.loads(await ws.recv())["code"] == "auth"


async def test_wrong_path_is_404(harness: Harness) -> None:
    from websockets.asyncio.client import connect

    with pytest.raises(InvalidStatus) as exc:
        await connect(harness.url.replace("/charm", "/other"))
    assert exc.value.response.status_code == 404


async def test_welcome_then_idle(harness: Harness) -> None:
    ws = await harness.raw()
    await ws.send(json.dumps({"type": "hello", "device_id": "d", "fw": "f", "token": TOKEN}))
    welcome = json.loads(await ws.recv())
    assert welcome["type"] == "welcome"
    assert welcome["server"] == SERVER_ID and "proto/0" in welcome["server"]
    assert welcome["tz"] == "America/Chicago" and "T" in welcome["time"]
    assert json.loads(await ws.recv()) == {"type": "state", "value": "idle"}


async def test_ping_pong_and_garbage_is_ignored(harness: Harness) -> None:
    dev = await harness.device()
    await dev.ws.send("{nope")
    await dev.send({"type": "mystery"})
    await dev.send({"no": "type"})
    await dev.ws.send(b"\x01\x02")  # stray audio outside a talk
    await dev.send({"type": "ping"})
    assert await dev.recv() == {"type": "pong"}


# --- talk flow -------------------------------------------------------------------------------


async def test_talk_flow_in_protocol_order(harness: Harness) -> None:
    stt, agent, tts = fake(harness.deps)
    dev = await harness.device()
    await dev.talk(tone(1.2))
    frames = await dev.until_idle()
    assert types(frames) == [
        "state:transcribing",
        "transcript",
        "state:working",
        "card",
        "state:speaking",
        "speech_start",
        "<pcm>",
        "speech_end",
        "state:idle",
    ]
    msgs = texts(frames)
    assert msgs[1] == {"type": "transcript", "text": stt.text, "final": True}
    assert msgs[2] == {"type": "state", "value": "working", "agent": "dex"}
    card = msgs[3]["card"]
    assert card["kind"] == "answer" and card["source"] == "dex"
    harness.deps.validator.check(card)
    start = msgs[5]
    assert start == {
        "type": "speech_start",
        "rate": 16000,
        "format": "s16le",
        "channels": 1,
        "card_id": card["id"],
    }
    audio = [f for f in frames if isinstance(f, bytes)]
    assert all(len(f) <= 4096 and len(f) % 2 == 0 for f in audio)
    assert b"".join(audio) == tts.pcm
    # Only two sentences are spoken; the card carries the whole (short) reply.
    assert tts.calls == [("A metaphor says one thing is another. He is a lion.", "en")]
    assert card["body"] == agent.reply_text and "footer" not in card
    await dev.send({"type": "displayed", "id": card["id"]})
    await dev.send({"type": "ping"})
    assert await dev.recv() == {"type": "pong"}


async def test_limit_reason_is_processed_like_released(harness: Harness) -> None:
    dev = await harness.device()
    await dev.talk(tone(1.0), reason="limit")
    assert "card" in types(await dev.until_idle())


async def test_spanish_question_gets_spanish_voice_hint(harness: Harness) -> None:
    stt, agent, tts = fake(harness.deps)
    stt.text, stt.language = "¿Qué es una metáfora?", "es"
    agent.reply_text = "Una metáfora dice que algo es otra cosa. Él es un león."
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until_idle()
    assert any("Spanish" in m["content"] for m in agent.calls[0] if m["role"] == "system")
    assert tts.calls[0][1] == "es"


async def test_long_answer_is_truncated_with_footer(harness: Harness) -> None:
    _, agent, tts = fake(harness.deps)
    agent.reply_text = " ".join(f"Sentence number {i} is here." for i in range(40))
    dev = await harness.device()
    await dev.talk(tone(1.0))
    card = next(m for m in texts(await dev.until_idle()) if m["type"] == "card")["card"]
    assert len(card["body"].split()) <= 60 and card["footer"]
    assert tts.calls[0][0] == "Sentence number 0 is here. Sentence number 1 is here."


async def test_conversation_context_is_kept_per_connection(harness: Harness) -> None:
    _, agent, _ = fake(harness.deps)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until_idle()
    await dev.talk(tone(1.0))
    await dev.until_idle()
    second = agent.calls[1]
    assert [m["role"] for m in second if m["role"] != "system"] == ["user", "assistant", "user"]
    assert second[-2]["content"] == agent.reply_text
    # A new connection starts fresh.
    other = await harness.device()
    await other.talk(tone(1.0))
    await other.until_idle()
    assert [m["role"] for m in agent.calls[2] if m["role"] != "system"] == ["user"]


# --- talk errors -----------------------------------------------------------------------------


@pytest.mark.parametrize("pcm", [tone(0.3), bytes(32000)], ids=["short", "silence"])
async def test_too_short_or_silent(harness: Harness, pcm: bytes) -> None:
    _, agent, _ = fake(harness.deps)
    dev = await harness.device()
    await dev.talk(pcm)
    frames = texts(await dev.until_idle())
    assert frames[0] == {"type": "state", "value": "transcribing"}
    assert frames[1]["type"] == "error" and frames[1]["code"] == "too_short"
    assert agent.calls == []


async def test_empty_transcript_is_no_speech(harness: Harness) -> None:
    stt, agent, _ = fake(harness.deps)
    stt.text = "  "
    dev = await harness.device()
    await dev.talk(tone(1.0))
    codes = [m.get("code") for m in texts(await dev.until_idle()) if m["type"] == "error"]
    assert codes == ["no_speech"] and agent.calls == []


async def test_agent_timeout(harness: Harness) -> None:
    _, agent, _ = fake(harness.deps)
    agent.delay = 5
    harness.deps.agent_timeout = 0.2
    dev = await harness.device()
    await dev.talk(tone(1.0))
    frames = texts(await dev.until_idle())
    assert [m["code"] for m in frames if m["type"] == "error"] == ["agent_timeout"]
    assert not any(m["type"] == "card" for m in frames)


async def test_agent_error_is_shown_honestly(harness: Harness) -> None:
    _, agent, _ = fake(harness.deps)
    agent.error = AgentError("Hermes returned HTTP 500.")
    dev = await harness.device()
    await dev.talk(tone(1.0))
    errors = [m for m in texts(await dev.until_idle()) if m["type"] == "error"]
    assert errors == [{"type": "error", "code": "agent_error", "text": "Hermes returned HTTP 500."}]


async def test_bad_audio_format(harness: Harness) -> None:
    stt, _, _ = fake(harness.deps)
    dev = await harness.device()
    await dev.send({"type": "audio_start", "rate": 8000, "format": "s16le", "channels": 1})
    assert await dev.recv() == {
        "type": "error",
        "code": "audio_format",
        "text": "I need 16 kHz, s16le, mono audio.",
    }
    await dev.ws.send(tone(1.0)[:4096])
    await dev.send({"type": "audio_end", "reason": "released"})
    assert await dev.silent_for(0.3) == []
    assert stt.calls == 0


async def test_oversized_audio_frame_is_rejected(harness: Harness) -> None:
    stt, _, _ = fake(harness.deps)
    dev = await harness.device()
    await dev.send({"type": "audio_start", "rate": 16000, "format": "s16le", "channels": 1})
    await dev.ws.send(bytes(5000))
    reply = await dev.recv()
    assert isinstance(reply, dict) and reply["code"] == "audio_format"
    await dev.send({"type": "audio_end", "reason": "released"})
    assert await dev.silent_for(0.3) == []
    assert stt.calls == 0


async def test_audio_end_cancel_discards(harness: Harness) -> None:
    stt, _, _ = fake(harness.deps)
    dev = await harness.device()
    await dev.talk(tone(1.0), reason="cancel")
    assert await dev.recv() == {"type": "state", "value": "idle"}
    assert await dev.silent_for(0.3) == [] and stt.calls == 0


async def test_busy_while_a_job_runs(harness: Harness) -> None:
    _, agent, _ = fake(harness.deps)
    agent.delay = 0.5
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m.get("value") == "working")
    await dev.talk(tone(1.0))
    frames = await dev.until_idle()
    msgs = texts(frames)
    assert msgs[0]["type"] == "error" and msgs[0]["code"] == "busy"
    assert [m["type"] for m in msgs].count("card") == 1
    assert len(agent.calls) == 1


# --- cancel ----------------------------------------------------------------------------------


async def test_cancel_while_thinking_drops_the_late_answer(harness: Harness) -> None:
    _, agent, tts = fake(harness.deps)
    agent.delay = 0.4
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m.get("value") == "working")
    await dev.send({"type": "cancel"})
    assert await dev.recv() == {"type": "state", "value": "idle"}
    assert await dev.silent_for(0.8) == []  # the answer would have landed at 0.4 s
    assert agent.finished == 0 and tts.calls == []
    # The cancelled question isn't remembered as answered context.
    agent.delay = 0
    await dev.talk(tone(1.0))
    await dev.until_idle()
    assert [m["role"] for m in agent.calls[1] if m["role"] != "system"] == ["user"]


async def test_cancel_while_speaking_sends_speech_end_then_idle(harness: Harness) -> None:
    _, _, tts = fake(harness.deps)
    tts.pcm = tone(4.0)
    harness.deps.speech_lead_s = 0.0  # real-time pacing so the speech is still streaming
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m["type"] == "speech_start")
    await dev.send({"type": "cancel"})
    frames = await dev.until_idle()
    assert types(frames)[-2:] == ["speech_end", "state:idle"]
    streamed = sum(len(f) for f in frames if isinstance(f, bytes))
    assert streamed < len(tts.pcm) / 2
    assert await dev.silent_for(0.3) == []


async def test_cancel_when_idle_just_confirms_idle(harness: Harness) -> None:
    dev = await harness.device()
    await dev.send({"type": "cancel"})
    assert await dev.recv() == {"type": "state", "value": "idle"}


async def test_tts_failure_leaves_the_card_without_speech(harness: Harness) -> None:
    from charm_server.tts import TTSError

    class BrokenTTS(FakeTTS):
        async def synthesize(self, text: str, language: str) -> bytes:
            raise TTSError("no audio")

    harness.deps.tts = BrokenTTS()
    dev = await harness.device()
    await dev.talk(tone(1.0))
    assert types(await dev.until_idle()) == [
        "state:transcribing",
        "transcript",
        "state:working",
        "card",
        "state:idle",
    ]


# --- requests --------------------------------------------------------------------------------


def _edition_card(section: str) -> dict[str, object]:
    return {
        "id": f"ed-{section}",
        "kind": "edition",
        "title": section,
        "source": "edition",
        "created_at": "2026-09-25T18:00:00-05:00",
        "data": {"section": section},
    }


async def test_edition_is_sent_in_section_order_and_invalid_cards_are_dropped(
    harness: Harness, tmp_path: Path
) -> None:
    sections = ["wire", "almanac", "masthead", "waiting", "one_thing", "sports"]
    for i, section in enumerate(sections):
        (tmp_path / f"{i:02d}-{section}.json").write_text(json.dumps(_edition_card(section)))
    bad = _edition_card("sports") | {"id": "ed-bad", "title": "x" * 61}
    (tmp_path / "99-bad.json").write_text(json.dumps(bad))
    (tmp_path / "98-broken.json").write_text("{not json")
    from dataclasses import replace

    harness.deps.config = replace(harness.deps.config, cards_dir=tmp_path)
    dev = await harness.device()
    await dev.send({"type": "request", "what": "edition"})
    await dev.send({"type": "request", "what": "status"})
    frames = texts(await dev.until(lambda m: m["type"] == "state"))
    ids = [m["card"]["id"] for m in frames if m["type"] == "card"]
    assert ids == [
        "ed-masthead",
        "ed-one_thing",
        "ed-sports",
        "ed-almanac",
        "ed-waiting",
        "ed-wire",
    ]


async def test_edition_from_contract_examples(harness: Harness) -> None:
    dev = await harness.device()
    await dev.send({"type": "request", "what": "edition"})
    first, second = await dev.recv(), await dev.recv()
    assert isinstance(first, dict) and isinstance(second, dict)
    assert [first["card"]["id"], second["card"]["id"]] == ["ed-sports", "ed-almanac"]


async def test_empty_edition_says_so(harness: Harness, tmp_path: Path) -> None:
    from dataclasses import replace

    harness.deps.config = replace(harness.deps.config, cards_dir=tmp_path)
    dev = await harness.device()
    await dev.send({"type": "request", "what": "edition"})
    reply = await dev.recv()
    assert isinstance(reply, dict) and reply["card"]["kind"] == "notice"
    assert reply["card"]["title"] == "No edition on file"


async def test_pending_then_attention(harness: Harness) -> None:
    dev = await harness.device()
    await dev.send({"type": "request", "what": "pending"})
    frames = texts(await dev.until(lambda m: m["type"] == "state"))
    kinds = sorted(m["card"]["kind"] for m in frames if m["type"] == "card")
    assert kinds == ["decision", "job", "money", "notice", "tracker"]
    assert frames[-1] == {"type": "state", "value": "attention"}


async def test_status_reports_current_state(harness: Harness) -> None:
    dev = await harness.device()
    await dev.send({"type": "request", "what": "status"})
    assert await dev.recv() == {"type": "state", "value": "idle"}


# --- actions ---------------------------------------------------------------------------------


async def _pending(dev: Client) -> None:
    await dev.send({"type": "request", "what": "pending"})
    await dev.until(lambda m: m["type"] == "state")


def _log(harness: Harness) -> list[dict[str, object]]:
    path = harness.deps.config.action_log
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize(
    ("action", "label"),
    [
        ("approve", "Approved. Logged."),
        ("reject", "Rejected. Logged."),
        ("snooze", "Snoozed. Logged."),
    ],
)
async def test_decision_is_logged_then_done_then_dismissed(
    harness: Harness, action: str, label: str
) -> None:
    dev = await harness.device()
    await _pending(dev)
    await dev.send({"type": "action", "card_id": "dec-001", "action": action})
    assert await dev.recv() == {"type": "state", "value": "done", "label": label}
    assert await dev.recv() == {"type": "dismiss", "card_id": "dec-001"}
    entry = _log(harness)[-1]
    assert entry["card_id"] == "dec-001" and entry["action"] == action
    assert entry["outcome"] == "logged"


async def test_action_on_unknown_card_dismisses_it(harness: Harness) -> None:
    dev = await harness.device()
    await dev.send({"type": "action", "card_id": "ghost", "action": "approve"})
    assert await dev.recv() == {"type": "dismiss", "card_id": "ghost"}
    assert _log(harness) == []


async def test_unknown_action_id_is_ignored(harness: Harness) -> None:
    dev = await harness.device()
    await _pending(dev)
    await dev.send({"type": "action", "card_id": "dec-001", "action": "explode"})
    assert await dev.silent_for(0.3) == []
    assert _log(harness) == []


@pytest.mark.parametrize("held", [None, 0, 1999, True])
async def test_money_confirm_without_a_full_hold_is_rejected(
    harness: Harness, held: object
) -> None:
    dev = await harness.device()
    await _pending(dev)
    message: dict[str, object] = {"type": "action", "card_id": "order-001", "action": "confirm"}
    if held is not None:
        message["held_ms"] = held
    await dev.send(message)
    reply = await dev.recv()
    assert isinstance(reply, dict) and reply["type"] == "error" and reply["code"] == "too_short"
    assert "Nothing was ordered" in reply["text"]
    assert await dev.silent_for(0.3) == []  # no ✓, no dismiss
    assert _log(harness)[-1]["outcome"] == "rejected_short_hold"


async def test_fixture_money_confirm_is_a_sample_that_charges_nothing(harness: Harness) -> None:
    dev = await harness.device()
    await _pending(dev)
    await dev.send({"type": "action", "card_id": "order-001", "action": "confirm", "held_ms": 2150})
    reply = await dev.recv()
    assert isinstance(reply, dict) and reply["type"] == "card"
    card = reply["card"]
    assert card["id"] == "order-001" and card["kind"] == "notice"
    assert card["body"] == SAMPLE_ORDER_TEXT
    assert await dev.recv() == {"type": "state", "value": "idle"}
    entry = _log(harness)[-1]
    assert (
        entry["outcome"] == "sample_ack" and entry["fixture"] is True and entry["held_ms"] == 2150
    )


async def test_non_fixture_money_confirm_still_orders_nothing(
    harness: Harness, tmp_path: Path
) -> None:
    money = json.loads((EXAMPLES / "money.json").read_text())
    money["data"]["fixture"] = False
    (tmp_path / "money.json").write_text(json.dumps(money))
    from dataclasses import replace

    harness.deps.config = replace(harness.deps.config, cards_dir=tmp_path)
    dev = await harness.device()
    await _pending(dev)
    await dev.send({"type": "action", "card_id": "order-001", "action": "confirm", "held_ms": 3000})
    reply = await dev.recv()
    assert isinstance(reply, dict) and reply["card"]["body"] == NO_REAL_ORDER_TEXT
    assert _log(harness)[-1]["outcome"] == "refused"


async def test_money_cancel_dismisses(harness: Harness) -> None:
    dev = await harness.device()
    await _pending(dev)
    await dev.send({"type": "action", "card_id": "order-001", "action": "reject"})
    assert await dev.recv() == {"type": "dismiss", "card_id": "order-001"}
    assert await dev.recv() == {"type": "state", "value": "idle"}


async def test_job_action_is_only_logged(harness: Harness) -> None:
    dev = await harness.device()
    await _pending(dev)
    await dev.send({"type": "action", "card_id": "job-001", "action": "send_claude"})
    reply = await dev.recv()
    assert isinstance(reply, dict) and reply["card"]["kind"] == "notice"
    assert "doesn't forward" in reply["card"]["body"]


async def test_events_and_receipts_are_accepted(harness: Harness) -> None:
    dev = await harness.device()
    await dev.send({"type": "event", "name": "battery", "value": 81})
    await dev.send({"type": "displayed", "id": "ans-x"})
    await dev.send({"type": "ping"})
    assert await dev.recv() == {"type": "pong"}


async def test_disconnect_mid_job_cancels_it(harness: Harness) -> None:
    _, agent, _ = fake(harness.deps)
    agent.delay = 0.3
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m.get("value") == "working")
    await dev.ws.close()
    await asyncio.sleep(0.5)
    assert agent.finished == 0
