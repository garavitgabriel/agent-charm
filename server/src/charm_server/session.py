"""One device connection after auth: the talk job, cancel, requests and card actions."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from charm_notes import Book, Note, NoteStore, SaveReceipt

from . import protocol as p
from .agent import Agent, AgentError, AgentTimeout, Message, answer_stream, system_messages
from .books import BookStore
from .cards import (
    Card,
    CardValidator,
    SpeechSplitter,
    answer_card,
    load_cards,
    new_answer_id,
    notice_card,
)
from .config import Config
from .intents import EnterReading, LeaveReading, SaveThought, SetChapter, SetSpeech, parse
from .notestore import UnavailableStore
from .reading import (
    EMPTY_SAVE_REASON,
    LeadSplitter,
    book_json,
    not_saved_card,
    reading_card,
    reading_messages,
    saved_card,
)
from .stt import STT, TooShort
from .tts import TTS, TTSError

log = logging.getLogger(__name__)

Send = Callable[[str | bytes], Awaitable[None]]

HISTORY_TURNS = 8  # question/answer pairs kept per connection
SAMPLE_ORDER_TEXT = "Sample order: nothing was charged."
NO_REAL_ORDER_TEXT = "Ordering isn't wired up yet. Nothing was ordered or charged."
# A backstop over the store's own timeout (the OS API store gives up after 10 s).
SAVE_TIMEOUT_SECONDS = 30.0


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
    # Reading state (shared by every connection) and where "save this" goes.
    books: BookStore = field(default_factory=BookStore.memory)
    notes: NoteStore = field(
        default_factory=lambda: UnavailableStore("no note store is configured")
    )


@dataclass
class Timings:
    """Seconds, measured on the server from the end of the recording.

    agent_first: question sent → first piece of the answer. agent: → the whole answer.
    tts: first sentence ready → its first audio out. first_audio: → the first audio out.
    """

    stt: float = 0.0
    agent_first: float = 0.0
    agent: float = 0.0
    tts: float = 0.0
    first_audio: float = 0.0
    total: float = 0.0

    def line(self) -> str:
        return (
            f"stt={self.stt:.2f}s agent_first={self.agent_first:.2f}s agent={self.agent:.2f}s "
            f"tts={self.tts:.2f}s first_audio={self.first_audio:.2f}s total={self.total:.2f}s"
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

    async def send_mode(self) -> None:
        """`mode{value, book?}`: the book is present in reading mode."""
        message: dict[str, Any] = {"type": "mode", "value": self.deps.books.mode}
        reading = self.deps.books.reading
        if reading is not None:
            message["book"] = book_json(reading.book)
        await self.send(message)

    async def send_setting(self, name: str) -> None:
        """Echo the *effective* value; the device shows state only from this echo."""
        books = self.deps.books
        value = books.speech_value if name == "speech" else books.mode
        await self.send({"type": "setting", "name": name, "value": value})

    async def greet(self) -> None:
        """On connect: restore an active reading session (it outlives connections)."""
        if self.deps.books.reading is not None:
            await self.send_mode()
            await self.send_setting("speech")

    async def _mode_changed(self) -> None:
        await self.send_mode()
        await self.send_setting("speech")  # each mode has its own speech default

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

    async def _on_setting(self, message: dict[str, Any]) -> None:
        name = message.get("name")
        value = message.get("value")
        books = self.deps.books
        if name == "speech":
            if value in p.SPEECH_VALUES:
                books.set_speech(str(value))
            else:
                log.info("setting speech=%r ignored", value)
            await self.send_setting("speech")
            return
        if name == "mode":
            before = books.mode
            if value == "reading":
                if books.resume() is None:
                    log.info("setting mode=reading with no book on record; staying in default")
            elif value == "default":
                books.leave()
            else:
                log.info("setting mode=%r ignored", value)
            if books.mode != before:
                await self._mode_changed()
            await self.send_setting("mode")
            return
        log.info("ignoring unknown setting %r", name)

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
        """Hear → ask Dex (streamed) → speak each sentence as soon as it's complete → card.

        The speech runs alongside the answer: sentence 1 goes to TTS the moment it's complete,
        sentence 2 is synthesized while sentence 1 plays. The card is sent once the whole
        answer is in. When the answer is already complete by the time the first audio is ready,
        the card still goes first (the PROTOCOL.md flow order); otherwise it arrives mid-speech.
        """
        timings = Timings()
        started = time.monotonic()
        speaker: _Speaker | None = None
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
            books = self.deps.books
            intent = parse(heard.text, reading=books.reading is not None)
            if intent is not None:
                log.info("intent %s", type(intent).__name__)
                await self._command(intent, heard.language)
                return
            await self.send_state("working", agent="dex")

            question: Message = {"role": "user", "content": heard.text}
            reading = books.reading
            book = reading.book if reading is not None else None
            splitter: SpeechSplitter | LeadSplitter
            if book is not None:
                messages = [*reading_messages(book, heard.language, books.turns()), question]
                splitter = LeadSplitter()  # only the lead is ever spoken
            else:
                messages = system_messages(heard.language) + self.history + [question]
                splitter = SpeechSplitter()
            card_id = new_answer_id()
            # Quiet (speech off): no speech_start/speech_end at all, just the card.
            if books.speech_value == "on":
                speaker = _Speaker(self, heard.language, card_id)
            parts: list[str] = []
            asked = time.monotonic()
            try:
                async with asyncio.timeout(self.deps.agent_timeout):
                    async for piece in answer_stream(self.deps.agent, messages):
                        if not parts:
                            timings.agent_first = time.monotonic() - asked
                        parts.append(piece)
                        for sentence in splitter.feed(piece):
                            if speaker is not None:
                                speaker.say(sentence)
            except (TimeoutError, AgentTimeout):
                if speaker is not None:
                    await speaker.abort()
                await self._fail("agent_timeout", "Dex didn't answer within 120 seconds.")
                return
            except AgentError as exc:
                if speaker is not None:
                    await speaker.abort()
                await self._fail("agent_error", str(exc) or "Dex couldn't answer.")
                return
            reply = "".join(parts).strip()
            if not reply:
                if speaker is not None:
                    await speaker.abort()
                await self._fail("agent_error", "Dex sent an empty answer.")
                return
            for sentence in splitter.finish():
                if speaker is not None:
                    speaker.say(sentence)
            if speaker is not None:
                speaker.end()
            timings.agent = time.monotonic() - asked
            tz = self.deps.config.tz
            if book is not None:
                books.add_turn(book.title, heard.text, reply)  # this book's own context
                card = reading_card(heard.text, reply, heard.language, tz, book, card_id)
            else:
                self.history += [question, {"role": "assistant", "content": reply}]
                self.history = self.history[-2 * HISTORY_TURNS :]
                card = answer_card(heard.text, reply, heard.language, tz, card_id)
            if speaker is not None:
                speaker.answer_complete = True
            try:
                await self.send_card(card)
            finally:
                if speaker is not None:
                    speaker.card_sent.set()

            if speaker is not None:
                first_audio = await speaker.wait()
                if first_audio is not None and speaker.first_text is not None:
                    timings.tts = first_audio - speaker.first_text
                    timings.first_audio = first_audio - started
            timings.total = time.monotonic() - started
            self.last_timings = timings
            log.info("talk timings %s", timings.line())
            await self.send_state("idle")
        except asyncio.CancelledError:
            log.info("talk cancelled; any late answer is dropped")
            raise
        finally:
            if speaker is not None:
                await speaker.abort()

    async def _command(
        self, intent: EnterReading | SetChapter | LeaveReading | SaveThought | SetSpeech, lang: str
    ) -> None:
        """A rule-based intent: handled here, never sent to Dex."""
        books = self.deps.books
        if isinstance(intent, SaveThought):
            await self._save(intent.text, lang)
            return
        if isinstance(intent, EnterReading):
            before = books.mode
            books.enter(intent.title, intent.author, intent.chapter)
            await self.send_mode()
            if before != "reading":
                await self.send_setting("speech")
        elif isinstance(intent, SetChapter):
            books.set_chapter(intent.chapter)
            await self.send_mode()
        elif isinstance(intent, LeaveReading):
            if books.mode == "reading":
                books.leave()
                await self._mode_changed()
            else:
                await self.send_mode()  # already out: confirm it anyway
        elif isinstance(intent, SetSpeech):
            books.set_speech(intent.value)
            await self.send_setting("speech")
        await self.send_state("idle")

    async def _save(self, text: str, language: str) -> None:
        """Save this thought: working{Saving} → receipt → saved notice + done, or save_failed.

        ✓ / `state{done}` only after the store confirms. The words are saved verbatim.
        """
        reading = self.deps.books.reading
        book: Book | None = reading.book if reading is not None else None
        tz = self.deps.config.tz
        card_id = f"ntc-{uuid.uuid4().hex[:10]}"
        if not text:
            await self._save_failed(card_id, EMPTY_SAVE_REASON.get(language, ""), language, book)
            return
        await self.send_state("working", label="Saving")
        note = Note(text=text, captured_at=datetime.now(ZoneInfo(tz)), language=language, book=book)
        try:
            async with asyncio.timeout(SAVE_TIMEOUT_SECONDS):
                receipt = await self.deps.notes.save(note)
        except TimeoutError:
            receipt = SaveReceipt(
                ok=False, error=f"the note store didn't confirm within {SAVE_TIMEOUT_SECONDS:g} s."
            )
        except Exception as exc:
            log.warning("note store raised %s", type(exc).__name__)
            receipt = SaveReceipt(ok=False, error=f"the note store failed ({type(exc).__name__}).")
        if receipt.ok is not True:
            await self._save_failed(card_id, receipt.error or "", language, book)
            return
        log.info("note saved (%s)", receipt.where)
        await self.send_card(saved_card(card_id, text, language, tz, book))
        await self.send_state("done", label="Saved")
        await self.send_state("idle")

    async def _save_failed(
        self, card_id: str, reason: str, language: str, book: Book | None
    ) -> None:
        reason = reason.strip() or "the note store didn't confirm."
        log.warning("save failed: %s", reason)
        await self.send_error("save_failed", f"Not saved: {reason}")
        await self.send_card(not_saved_card(card_id, reason, language, self.deps.config.tz, book))
        await self.send_state("idle")

    async def _fail(self, code: str, text: str) -> None:
        if self._speaking:  # the answer broke off mid-speech: end it honestly first
            self._speaking = False
            await self.send({"type": "speech_end"})
        await self.send_error(code, text)
        await self.send_state("idle")

    async def close(self) -> None:
        if self._job is not None and not self._job.done():
            self._job.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._job


_END = None  # end of the spoken sentences


class _Speaker:
    """Speaks the answer's sentences as they arrive, for one talk job.

    Sentences that are already waiting when TTS can start are synthesized together (one call);
    each later sentence gets its own TTS stream, started at once so it's ready by the time the
    one before it has played. Audio goes out in order, paced at real time plus a lead.

    A TTS failure before any audio leaves the card up without speech; a failure midway ends the
    speech early. Either way the device gets an honest `speech_end`.
    """

    def __init__(self, session: Session, language: str, card_id: str) -> None:
        self.session = session
        self.language = language
        self.card_id = card_id
        self.answer_complete = False
        self.card_sent = asyncio.Event()
        self.first_text: float | None = None  # when the first sentence was ready
        self._sentences: asyncio.Queue[str | None] = asyncio.Queue()
        self._segments: asyncio.Queue[asyncio.Queue[bytes | Exception | None] | None] = (
            asyncio.Queue()
        )
        self._producers: list[asyncio.Task[None]] = []
        self._batcher = asyncio.create_task(self._batch(), name="speech-batch")
        self._player = asyncio.create_task(self._play(), name="speech-play")

    def say(self, sentence: str) -> None:
        if self.first_text is None:
            self.first_text = time.monotonic()
        self._sentences.put_nowait(sentence)

    def end(self) -> None:
        self._sentences.put_nowait(_END)

    async def wait(self) -> float | None:
        """Wait for the speech to finish. Returns when the first audio went out, if any."""
        return await self._player

    async def abort(self) -> None:
        tasks = [self._batcher, self._player, *self._producers]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(BaseException):
                await task

    async def _batch(self) -> None:
        try:
            ended = False
            while not ended:
                first = await self._sentences.get()
                if first is _END:
                    break
                batch = [first]
                while not self._sentences.empty():
                    more = self._sentences.get_nowait()
                    if more is _END:
                        ended = True
                        break
                    batch.append(more)
                segment: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()
                self._producers.append(
                    asyncio.create_task(self._synthesize(" ".join(batch), segment), name="tts")
                )
                self._segments.put_nowait(segment)
        finally:
            self._segments.put_nowait(None)

    async def _synthesize(self, text: str, out: asyncio.Queue[bytes | Exception | None]) -> None:
        try:
            async for chunk in self.session.deps.tts.stream(text, self.language):
                out.put_nowait(chunk)
        except TTSError as exc:
            out.put_nowait(exc)
        finally:
            out.put_nowait(None)

    async def _play(self) -> float | None:
        session = self.session
        lead = session.deps.speech_lead_s
        began: float | None = None
        sent_seconds = 0.0
        pending = bytearray()

        async def send_frame(frame: bytes) -> None:
            nonlocal sent_seconds
            if lead is not None and began is not None:
                ahead = sent_seconds - (time.monotonic() - began) - lead
                if ahead > 0:
                    await asyncio.sleep(ahead)
            await session.send_raw(frame)
            sent_seconds += len(frame) / p.BYTES_PER_SECOND

        failed = False
        while not failed and (segment := await self._segments.get()) is not None:
            while (chunk := await segment.get()) is not None:
                if isinstance(chunk, Exception):
                    log.warning("tts failed: %s", chunk)
                    failed = True
                    break
                if began is None:
                    if self.answer_complete:
                        await self.card_sent.wait()  # the card first, as in PROTOCOL.md
                    await session.send_state("speaking")
                    await session.send(
                        {
                            "type": "speech_start",
                            "rate": p.SAMPLE_RATE,
                            "format": p.SAMPLE_FORMAT,
                            "channels": p.CHANNELS,
                            "card_id": self.card_id,
                        }
                    )
                    session._speaking = True
                    began = time.monotonic()
                pending.extend(chunk)
                while len(pending) >= p.MAX_BINARY_FRAME:
                    await send_frame(bytes(pending[: p.MAX_BINARY_FRAME]))
                    del pending[: p.MAX_BINARY_FRAME]
        if began is None:
            return None
        tail = bytes(pending[: len(pending) - len(pending) % 2])
        if tail:
            await send_frame(tail)
        # The card must be out before the speech ends and the job goes idle.
        await self.card_sent.wait()
        session._speaking = False
        await session.send({"type": "speech_end"})
        return began
