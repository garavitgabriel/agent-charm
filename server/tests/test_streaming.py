"""The streamed talk flow: speech starts on Dex's first sentence, the card when the answer is in.

Same localhost server and fake engines as test_server.py, with an agent that streams its answer
piece by piece (like HermesChannel). The protocol is unchanged: the device sees the same message
types, `state{speaking}` still comes before `speech_start`, and cancel still drops everything.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from charm_server.agent import AgentError, AgentTimeout, Message, StreamingAgent
from charm_server.cards import say_text

from .conftest import FakeTTS, Harness, texts, tone, types


@dataclass
class StreamingFakeAgent:
    pieces: list[str] = field(
        default_factory=lambda: ["A metaphor says one ", "thing is another. ", "He is a ", "lion."]
    )
    gap: float = 0.0  # seconds between pieces
    fail_after: int | None = None  # raise after this many pieces
    error: Exception = field(default_factory=lambda: AgentError("Hermes returned HTTP 502."))
    calls: list[list[Message]] = field(default_factory=list)
    sent: list[float] = field(default_factory=list)
    finished: int = 0

    async def reply(self, messages: list[Message]) -> str:
        return "".join([p async for p in self.stream(messages)])

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        self.calls.append(messages)
        for i, piece in enumerate([*self.pieces, None]):
            if i:
                await asyncio.sleep(self.gap)
            if self.fail_after is not None and i == self.fail_after:
                raise self.error
            if piece is None:
                break
            self.sent.append(time.monotonic())
            yield piece
        self.finished += 1


@dataclass
class TimedTTS(FakeTTS):
    started: list[float] = field(default_factory=list)
    first_chunk_delay: float = 0.0

    async def stream(self, text: str, language: str) -> AsyncIterator[bytes]:
        self.calls.append((text, language))
        self.started.append(time.monotonic())
        await asyncio.sleep(self.first_chunk_delay)
        for i in range(0, len(self.pcm), 3001):
            yield self.pcm[i : i + 3001]


def use(harness: Harness, agent: StreamingFakeAgent, tts: FakeTTS | None = None) -> TimedTTS:
    harness.deps.agent = agent
    timed = tts if isinstance(tts, TimedTTS) else TimedTTS()
    harness.deps.tts = timed
    return timed


def test_fakes_speak_the_streaming_protocol() -> None:
    assert isinstance(StreamingFakeAgent(), StreamingAgent)


async def test_speech_starts_on_the_first_sentence_before_the_answer_is_done(
    harness: Harness,
) -> None:
    agent = StreamingFakeAgent(gap=0.4)
    tts = use(harness, agent)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    frames = await dev.until_idle()
    # Sentence 1 went to TTS alone, as soon as it was complete (when "He is a " showed it
    # ended), long before the last piece; sentence 2 got its own TTS stream.
    assert [c[0] for c in tts.calls] == ["A metaphor says one thing is another.", "He is a lion."]
    assert tts.started[0] < agent.sent[-1] - 0.2
    # The device sees the same types; speech began before the card, which came mid-speech.
    assert types(frames) == [
        "state:transcribing",
        "transcript",
        "state:working",
        "state:speaking",
        "speech_start",
        "<pcm>",
        "card",
        "<pcm>",
        "speech_end",
        "state:idle",
    ]
    msgs = texts(frames)
    card = next(m for m in msgs if m["type"] == "card")["card"]
    start = next(m for m in msgs if m["type"] == "speech_start")
    assert start["card_id"] == card["id"]  # the card id is fixed before speech starts
    assert card["body"] == "A metaphor says one thing is another. He is a lion."
    harness.deps.validator.check(card)
    audio = b"".join(f for f in frames if isinstance(f, bytes))
    assert audio == tts.pcm * 2 and all(
        len(f) <= 4096 and len(f) % 2 == 0 for f in frames if isinstance(f, bytes)
    )


async def test_card_first_when_the_answer_beats_the_first_audio(harness: Harness) -> None:
    agent = StreamingFakeAgent(gap=0.05)
    tts = TimedTTS(first_chunk_delay=0.6)  # Edge is slower than the rest of the answer
    use(harness, agent, tts)
    dev = await harness.device()
    await dev.talk(tone(1.0))
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
    assert len(tts.calls) == 2  # still synthesized per sentence, started early


async def test_only_two_sentences_are_spoken_and_the_card_is_capped(harness: Harness) -> None:
    long = [f"Sentence {i} is here. " for i in range(40)]
    agent = StreamingFakeAgent(pieces=long, gap=0.001)
    tts = use(harness, agent)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    msgs = texts(await dev.until_idle())
    spoken = " ".join(c[0] for c in tts.calls)
    assert spoken == say_text("".join(long)) == "Sentence 0 is here. Sentence 1 is here."
    card = next(m for m in msgs if m["type"] == "card")["card"]
    assert len(card["body"].split()) <= 60
    assert card["footer"] == "Shortened. Ask Dex for the rest."


async def test_spanish_streams_with_abbreviations_and_decimals(harness: Harness) -> None:
    stt = harness.deps.stt
    stt.text, stt.language = "¿Cuánto mide?", "es"  # type: ignore[attr-defined]
    agent = StreamingFakeAgent(
        pieces=[
            "El Sr. Pérez ",
            "mide 1.75 m ",
            "en EE. UU. ",
            "según el Dr. Ruiz. ",
            "¡Así ",
            "es!",
        ],
        gap=0.02,
    )
    tts = use(harness, agent)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until_idle()
    assert tts.calls == [
        ("El Sr. Pérez mide 1.75 m en EE. UU. según el Dr. Ruiz.", "es"),
        ("¡Así es!", "es"),
    ]


async def test_the_full_streamed_answer_is_remembered(harness: Harness) -> None:
    agent = StreamingFakeAgent(gap=0.01)
    use(harness, agent)
    dev = await harness.device()
    for _ in range(2):
        await dev.talk(tone(1.0))
        await dev.until_idle()
    assert agent.calls[1][-2] == {
        "role": "assistant",
        "content": "A metaphor says one thing is another. He is a lion.",
    }


def test_timings_line_has_the_new_fields() -> None:
    from charm_server.session import Timings

    line = Timings(stt=0.5, agent_first=2.0, agent=3.0, tts=1.5, first_audio=4.2).line()
    assert "agent_first=2.00s" in line and "first_audio=4.20s" in line and "tts=1.50s" in line


# --- errors mid-stream -----------------------------------------------------------------------


async def test_error_before_any_text_is_like_before(harness: Harness) -> None:
    agent = StreamingFakeAgent(fail_after=0)
    tts = use(harness, agent)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    frames = await dev.until_idle()
    assert types(frames) == [
        "state:transcribing",
        "transcript",
        "state:working",
        "error",
        "state:idle",
    ]
    assert texts(frames)[3]["code"] == "agent_error" and tts.calls == []


async def test_error_mid_speech_ends_the_speech_honestly_and_sends_no_card(
    harness: Harness,
) -> None:
    agent = StreamingFakeAgent(
        pieces=["First sentence. ", "Second ", "starts."], gap=0.4, fail_after=2
    )
    use(harness, agent)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    frames = await dev.until_idle()
    assert types(frames)[-4:] == ["<pcm>", "speech_end", "error", "state:idle"]
    assert "speech_start" in types(frames) and "card" not in types(frames)
    error = next(m for m in texts(frames) if m["type"] == "error")
    assert error == {"type": "error", "code": "agent_error", "text": "Hermes returned HTTP 502."}


async def test_timeout_mid_stream_is_agent_timeout(harness: Harness) -> None:
    agent = StreamingFakeAgent(pieces=["Hello. ", "And ", "then."], gap=1.0)
    use(harness, agent)
    harness.deps.agent_timeout = 0.5
    dev = await harness.device()
    await dev.talk(tone(1.0))
    frames = await dev.until_idle()
    codes = [m["code"] for m in texts(frames) if m["type"] == "error"]
    assert codes == ["agent_timeout"] and "card" not in types(frames)
    if "speech_start" in types(frames):
        assert types(frames).index("speech_end") < types(frames).index("error")


async def test_channel_timeout_is_agent_timeout(harness: Harness) -> None:
    agent = StreamingFakeAgent(fail_after=1, error=AgentTimeout("slow"))
    use(harness, agent)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    codes = [m["code"] for m in texts(await dev.until_idle()) if m["type"] == "error"]
    assert codes == ["agent_timeout"]


@pytest.mark.parametrize("pieces", [[], ["   "]], ids=["nothing", "blank"])
async def test_empty_stream_is_an_agent_error(harness: Harness, pieces: list[str]) -> None:
    use(harness, StreamingFakeAgent(pieces=pieces))
    dev = await harness.device()
    await dev.talk(tone(1.0))
    errors = [m for m in texts(await dev.until_idle()) if m["type"] == "error"]
    assert [e["code"] for e in errors] == ["agent_error"]


# --- cancel ----------------------------------------------------------------------------------


async def test_cancel_mid_stream_while_speaking_drops_everything_late(harness: Harness) -> None:
    agent = StreamingFakeAgent(pieces=["First one. ", "Second ", "one. ", "Third."], gap=0.3)
    tts = use(harness, agent)
    tts.pcm = tone(3.0)
    harness.deps.speech_lead_s = 0.0  # real-time pacing: still speaking when we cancel
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m["type"] == "speech_start")
    await dev.send({"type": "cancel"})
    frames = await dev.until_idle()
    assert types(frames)[-2:] == ["speech_end", "state:idle"]
    assert await dev.silent_for(1.2) == []  # no late card, speech or state
    assert agent.finished == 0
    # The cancelled question isn't remembered.
    agent.pieces, agent.gap = ["Fine."], 0.0
    await dev.talk(tone(1.0))
    await dev.until_idle()
    assert [m["role"] for m in agent.calls[1] if m["role"] != "system"] == ["user"]


async def test_cancel_while_thinking_before_any_sentence(harness: Harness) -> None:
    agent = StreamingFakeAgent(pieces=["Not yet a sentence ", "still going"], gap=0.4)
    tts = use(harness, agent)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m.get("value") == "working")
    await dev.send({"type": "cancel"})
    assert await dev.recv() == {"type": "state", "value": "idle"}
    assert await dev.silent_for(0.8) == []
    assert tts.calls == []


async def test_busy_while_streaming(harness: Harness) -> None:
    agent = StreamingFakeAgent(gap=0.3)
    use(harness, agent)
    dev = await harness.device()
    await dev.talk(tone(1.0))
    await dev.until(lambda m: m.get("value") == "working")
    await dev.talk(tone(1.0))
    msgs = texts(await dev.until_idle())
    assert msgs[0]["type"] == "error" and msgs[0]["code"] == "busy"
    assert [m["type"] for m in msgs].count("card") == 1 and len(agent.calls) == 1
