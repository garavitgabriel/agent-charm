"""One device connection after auth: the talk job, cancel, requests and card actions."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import protocol as p
from .agent import Agent, AgentError, AgentTimeout, Message, system_messages
from .cards import Card, CardValidator, answer_card, load_cards, notice_card, say_text
from .config import Config
from .stt import STT, TooShort
from .tts import TTS, TTSError

log = logging.getLogger(__name__)

Send = Callable[[str | bytes], Awaitable[None]]

HISTORY_TURNS = 8  # question/answer pairs kept per connection
SAMPLE_ORDER_TEXT = "Sample order: nothing was charged."
NO_REAL_ORDER_TEXT = "Ordering isn't wired up yet. Nothing was ordered or charged."


@dataclass
class Deps:
    config: Config
    stt: STT
    agent: Agent
    tts: TTS
    validator: CardValidator
    agent_timeout: float = p.AGENT_TIMEOUT_SECONDS
    # Stream speech at real time plus this much lead, so the device's ring buffer never
    # overflows. None sends as fast as possible (tests).
    speech_lead_s: float | None = 1.0


@dataclass
class Timings:
    stt: float = 0.0
    agent: float = 0.0
    tts: float = 0.0
    total: float = 0.0

    def line(self) -> str:
        return (
            f"stt={self.stt:.2f}s agent={self.agent:.2f}s tts={self.tts:.2f}s "
            f"total={self.total:.2f}s"
        )


@dataclass
class Session:
    send_raw: Send
    deps: Deps
    device_id: str = "?"
    history: list[Message] = field(default_factory=list)
    cards: dict[str, Card] = field(default_factory=dict)
    displayed: set[str] = field(default_factory=set)
    last_state: str = "idle"
    last_timings: Timings | None = None
    _capture: bytearray | None = None
    _discarding: bool = False
    _job: asyncio.Task[None] | None = None
    _speaking: bool = False

    # --- sending -----------------------------------------------------------------------------

    async def send(self, message: dict[str, Any]) -> None:
        if message["type"] == "state":
            self.last_state = message["value"]
        await self.send_raw(p.encode(message))

    async def send_state(
        self, value: str, label: str | None = None, agent: str | None = None
    ) -> None:
        await self.send(p.state(value, label, agent))

    async def send_error(self, code: str, text: str) -> None:
        await self.send(p.error(code, text))

    async def send_card(self, card: Card) -> None:
        self.deps.validator.check(card)  # never send a card the contract rejects
        self.cards[card["id"]] = card
        await self.send({"type": "card", "card": card})

    async def dismiss(self, card_id: str) -> None:
        self.cards.pop(card_id, None)
        await self.send({"type": "dismiss", "card_id": card_id})

    # --- receiving ---------------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._job is not None and not self._job.done()

    async def handle_text(self, text: str) -> None:
        if len(text.encode()) > p.MAX_TEXT_FRAME:
            log.warning("dropping oversized text frame (%d bytes)", len(text.encode()))
            return
        try:
            message = json.loads(text)
        except ValueError:
            log.warning("dropping non-JSON text frame")
            return
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            log.warning("dropping frame without a type")
            return
        handler = getattr(self, f"_on_{message['type']}", None)
        if handler is None:
            log.info("ignoring unknown frame type %r", message["type"])
            return
        await handler(message)

    async def handle_binary(self, data: bytes) -> None:
        if self._capture is None:
            return  # stray audio, or audio after busy/format rejection
        if len(data) > p.MAX_BINARY_FRAME or len(data) % 2:
            self._capture = None
            self._discarding = True
            await self.send_error(
                "audio_format", "Audio frames must be whole s16le samples, 4096 bytes max."
            )
            return
        room = p.MAX_AUDIO_BYTES - len(self._capture)
        self._capture.extend(data[: max(0, room)])

    async def _on_hello(self, message: dict[str, Any]) -> None:
        log.info("repeated hello ignored")

    async def _on_ping(self, message: dict[str, Any]) -> None:
        await self.send({"type": "pong"})

    async def _on_audio_start(self, message: dict[str, Any]) -> None:
        self._capture = None
        self._discarding = True
        if self.busy:
            await self.send_error("busy", "I'm still on the last one. Cancel it or wait a moment.")
            return
        if (
            message.get("rate") != p.SAMPLE_RATE
            or message.get("format") != p.SAMPLE_FORMAT
            or message.get("channels") != p.CHANNELS
        ):
            await self.send_error("audio_format", "I need 16 kHz, s16le, mono audio.")
            return
        self._capture = bytearray()
        self._discarding = False

    async def _on_audio_end(self, message: dict[str, Any]) -> None:
        pcm, self._capture = self._capture, None
        discarding, self._discarding = self._discarding, False
        if pcm is None:
            if not discarding:
                log.info("audio_end without audio_start ignored")
            return
        reason = message.get("reason")
        if reason == "cancel":
            await self.send_state("idle")
            return
        if reason not in p.AUDIO_END_REASONS:
            await self.send_error("audio_format", f"Unknown audio_end reason {reason!r}.")
            await self.send_state("idle")
            return
        self._job = asyncio.create_task(self._talk(bytes(pcm)), name="talk")

    async def _on_cancel(self, message: dict[str, Any]) -> None:
        self._capture = None
        self._discarding = False
        was_speaking = self._speaking
        job, self._job = self._job, None
        if job is not None and not job.done():
            job.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await job
        self._speaking = False
        if was_speaking:
            await self.send({"type": "speech_end"})
        await self.send_state("idle")

    async def _on_request(self, message: dict[str, Any]) -> None:
        what = message.get("what")
        if what == "status":
            await self.send_state(self.last_state)
            return
        if what not in ("edition", "pending"):
            log.info("ignoring request for %r", what)
            return
        cardset = await asyncio.to_thread(
            load_cards, self.deps.config.cards_dir, self.deps.validator
        )
        tz = self.deps.config.tz
        if what == "edition":
            if not cardset.edition:
                empty = "The desk hasn't filed an edition yet."
                await self.send_card(notice_card("ed-none", "No edition on file", empty, tz))
                return
            for card in cardset.edition:
                await self.send_card(card)
            return
        for card in cardset.pending:
            await self.send_card(card)
        if cardset.pending and not self.busy:
            await self.send_state("attention")

    async def _on_displayed(self, message: dict[str, Any]) -> None:
        card_id = message.get("id")
        if isinstance(card_id, str):
            self.displayed.add(card_id)
            log.info("displayed %s", card_id)

    async def _on_event(self, message: dict[str, Any]) -> None:
        log.info("device event %s value=%r", message.get("name"), message.get("value"))

    async def _on_action(self, message: dict[str, Any]) -> None:
        card_id = message.get("card_id")
        action_id = message.get("action")
        held = message.get("held_ms")
        held_ms = held if isinstance(held, int) and not isinstance(held, bool) else None
        card = self.cards.get(card_id) if isinstance(card_id, str) else None
        if card is None:
            log.warning("action %r on unknown card %r; dismissing it", action_id, card_id)
            if isinstance(card_id, str) and card_id:
                await self.dismiss(card_id)
            return
        spec = next((a for a in card.get("actions", []) if a.get("id") == action_id), None)
        if spec is None:
            log.warning("card %s has no action %r; ignored", card_id, action_id)
            return
        kind = card["kind"]
        fixture = bool(card.get("data", {}).get("fixture")) if kind == "money" else None

        if kind == "money" and "hold_ms" in spec:
            required = max(int(spec["hold_ms"]), 2000)
            if held_ms is None or held_ms < required:
                self._log_action(card, str(action_id), held_ms, "rejected_short_hold", fixture)
                await self.send_error(
                    "too_short",
                    f"Hold for the full {required / 1000:g} seconds to confirm. "
                    "Nothing was ordered.",
                )
                return
            # v0 never places a real order: no DeliveryCo call exists anywhere in this server.
            text = SAMPLE_ORDER_TEXT if fixture else NO_REAL_ORDER_TEXT
            outcome = "sample_ack" if fixture else "refused"
            self._log_action(card, str(action_id), held_ms, outcome, fixture)
            title = "Sample order" if fixture else "Not ordered"
            await self.send_card(notice_card(card["id"], title, text, self.deps.config.tz))
            await self.send_state("idle")
            return

        if kind == "decision":
            self._log_action(card, str(action_id), held_ms, "logged", None)
            labels = {"approve": "Approved", "reject": "Rejected", "snooze": "Snoozed"}
            label = labels.get(str(action_id), str(spec.get("label", action_id)))
            await self.send_state("done", label=f"{label}. Logged.")
            await self.dismiss(card["id"])
            return

        if kind == "money":  # a non-hold money action, e.g. cancel
            self._log_action(card, str(action_id), held_ms, "logged", fixture)
            await self.dismiss(card["id"])
            await self.send_state("idle")
            return

        # job / tracker / notice / answer actions: logged only; v0 forwards nothing.
        self._log_action(card, str(action_id), held_ms, "logged", None)
        noted = "Logged on the server. v0 doesn't forward this yet."
        await self.send_card(notice_card(card["id"], "Noted", noted, self.deps.config.tz))

    def _log_action(
        self, card: Card, action: str, held_ms: int | None, outcome: str, fixture: bool | None
    ) -> None:
        entry = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "device_id": self.device_id,
            "card_id": card["id"],
            "kind": card["kind"],
            "action": action,
            "held_ms": held_ms,
            "outcome": outcome,
        }
        if fixture is not None:
            entry["fixture"] = fixture
        path: Path = self.deps.config.action_log
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log.info("action %s", entry)

    # --- the talk job ------------------------------------------------------------------------

    async def _talk(self, pcm: bytes) -> None:
        timings = Timings()
        started = time.monotonic()
        try:
            await self.send_state("transcribing")
            try:
                heard = await self.deps.stt.transcribe(pcm)
            except TooShort as exc:
                await self._fail("too_short", str(exc))
                return
            timings.stt = time.monotonic() - started
            if not heard.text.strip():
                await self._fail("no_speech", "I didn't catch any words. Try again?")
                return
            await self.send({"type": "transcript", "text": heard.text, "final": True})
            await self.send_state("working", agent="dex")

            question: Message = {"role": "user", "content": heard.text}
            messages = system_messages(heard.language) + self.history + [question]
            asked = time.monotonic()
            try:
                reply = await asyncio.wait_for(
                    self.deps.agent.reply(messages), timeout=self.deps.agent_timeout
                )
            except (TimeoutError, AgentTimeout):
                await self._fail("agent_timeout", "Dex didn't answer within 120 seconds.")
                return
            except AgentError as exc:
                await self._fail("agent_error", str(exc) or "Dex couldn't answer.")
                return
            timings.agent = time.monotonic() - asked
            self.history += [question, {"role": "assistant", "content": reply}]
            self.history = self.history[-2 * HISTORY_TURNS :]

            card = answer_card(heard.text, reply, heard.language, self.deps.config.tz)
            await self.send_card(card)

            synth_started = time.monotonic()
            first_audio = await self._speak(say_text(reply), heard.language, card["id"])
            timings.tts = (first_audio or time.monotonic()) - synth_started
            timings.total = time.monotonic() - started
            self.last_timings = timings
            log.info("talk timings %s", timings.line())
            await self.send_state("idle")
        except asyncio.CancelledError:
            log.info("talk cancelled; any late answer is dropped")
            raise

    async def _fail(self, code: str, text: str) -> None:
        await self.send_error(code, text)
        await self.send_state("idle")

    async def _speak(self, text: str, language: str, card_id: str) -> float | None:
        """Stream TTS as it's synthesized. Returns when the first audio went out, if any.

        A TTS failure before any audio leaves the card up without speech; a failure midway
        ends the speech early. Either way the device gets an honest `speech_end`.
        """
        lead = self.deps.speech_lead_s
        began = 0.0
        sent_seconds = 0.0
        pending = bytearray()

        async def send_frame(frame: bytes) -> None:
            nonlocal sent_seconds
            if lead is not None:
                ahead = sent_seconds - (time.monotonic() - began) - lead
                if ahead > 0:
                    await asyncio.sleep(ahead)
            await self.send_raw(frame)
            sent_seconds += len(frame) / p.BYTES_PER_SECOND

        try:
            async for chunk in self.deps.tts.stream(text, language):
                if not self._speaking:
                    await self.send_state("speaking")
                    await self.send(
                        {
                            "type": "speech_start",
                            "rate": p.SAMPLE_RATE,
                            "format": p.SAMPLE_FORMAT,
                            "channels": p.CHANNELS,
                            "card_id": card_id,
                        }
                    )
                    self._speaking = True
                    began = time.monotonic()
                pending.extend(chunk)
                while len(pending) >= p.MAX_BINARY_FRAME:
                    await send_frame(bytes(pending[: p.MAX_BINARY_FRAME]))
                    del pending[: p.MAX_BINARY_FRAME]
        except TTSError as exc:
            log.warning("tts failed: %s", exc)
        if not self._speaking:
            return None
        tail = bytes(pending[: len(pending) - len(pending) % 2])
        if tail:
            await send_frame(tail)
        self._speaking = False
        await self.send({"type": "speech_end"})
        return began

    async def close(self) -> None:
        if self._job is not None and not self._job.done():
            self._job.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._job
