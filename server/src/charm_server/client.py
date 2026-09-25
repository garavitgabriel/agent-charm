"""`charm-client`: a fake device on the Mac. It speaks the device side of docs/PROTOCOL.md.

    charm-client --say "What's a metaphor?"     # macOS `say` -> 16 kHz PCM -> Dex
    charm-client --wav question.wav
    charm-client --mic                          # Enter to start, Enter to stop
    charm-client --edition                      # pull the pocket edition
    charm-client --pending --action order-001:confirm --held-ms 2000

It prints states, the transcript and cards, sends `displayed` receipts like the device does, and
plays Dex's speech through the Mac speakers.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from . import protocol as p
from .config import Config
from .tts import decode_to_pcm

CLIENT_FW = "charm-client/0.1 proto/0"


def _stamp(t0: float) -> str:
    return f"[{time.monotonic() - t0:6.2f}s]"


class Player:
    """Streams s16le mono PCM to the default output as frames arrive (sounddevice).

    Falls back to writing a WAV and running `afplay` once speech ends.
    """

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._stream: Any = None
        self._all = bytearray()
        self._fallback = False

    def start(self) -> None:
        self._all.clear()
        if not self.enabled or self._stream is not None or self._fallback:
            return
        try:
            import sounddevice as sd

            self._stream = sd.RawOutputStream(
                samplerate=p.SAMPLE_RATE,
                channels=1,
                dtype="int16",
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:  # no PortAudio, no output device, ...
            print(f"  (live playback unavailable: {exc}; using afplay)")
            self._fallback = True

    def _callback(self, outdata: Any, frames: int, _time: Any, _status: Any) -> None:
        need = len(outdata)
        with self._lock:
            chunk = bytes(self._buffer[:need])
            del self._buffer[:need]
        outdata[: len(chunk)] = chunk
        outdata[len(chunk) :] = b"\x00" * (need - len(chunk))

    def feed(self, pcm: bytes) -> None:
        self._all.extend(pcm)
        if self._stream is not None:
            with self._lock:
                self._buffer.extend(pcm)

    def stop_now(self) -> None:
        with self._lock:
            self._buffer.clear()

    async def drain(self) -> None:
        """Wait until everything received has been played."""
        if not self.enabled or not self._all:
            return
        if self._stream is not None:
            while True:
                with self._lock:
                    left = len(self._buffer)
                if not left:
                    break
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.2)
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(p.SAMPLE_RATE)
            w.writeframes(bytes(self._all))
        proc = await asyncio.create_subprocess_exec("afplay", str(path))
        await proc.wait()
        await asyncio.to_thread(path.unlink, missing_ok=True)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


@dataclass
class Marks:
    """Arrival times (monotonic) of the talk flow's milestones, for the timing summary."""

    audio_end: float = 0.0
    transcript: float = 0.0
    working: float = 0.0
    card: float = 0.0
    speech_start: float = 0.0
    speech_end: float = 0.0
    idle: float = 0.0
    speech_bytes: int = 0

    def summary(self) -> str:
        def gap(a: float, b: float) -> str:
            return f"{b - a:.2f}s" if a and b else "n/a"

        return (
            f"stt {gap(self.audio_end, self.transcript)} · "
            f"agent {gap(self.working, self.card)} · "
            f"tts {gap(self.card, self.speech_start)} · "
            f"first audio {gap(self.audio_end, self.speech_start)} · "
            f"total {gap(self.audio_end, self.speech_end or self.idle)} "
            f"(speech {self.speech_bytes / p.BYTES_PER_SECOND:.1f}s of audio)"
        )


@dataclass
class Device:
    ws: ClientConnection
    player: Player
    t0: float = field(default_factory=time.monotonic)
    marks: Marks = field(default_factory=Marks)
    cards: dict[str, dict[str, Any]] = field(default_factory=dict)
    in_speech: bool = False
    errors: list[str] = field(default_factory=list)
    _waiters: list[tuple[str, asyncio.Future[dict[str, Any]]]] = field(default_factory=list)

    async def send(self, message: dict[str, Any]) -> None:
        await self.ws.send(json.dumps(message))

    def wait_for(self, kind: str) -> asyncio.Future[dict[str, Any]]:
        """A future resolved by the next frame matching `kind` (a type, or `state:<value>`)."""
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._waiters.append((kind, future))
        return future

    def _resolve(self, message: dict[str, Any]) -> None:
        keys = {message["type"]}
        if message["type"] == "state":
            keys.add(f"state:{message.get('value')}")
        for waiter in list(self._waiters):
            kind, future = waiter
            if kind in keys and not future.done():
                future.set_result(message)
                self._waiters.remove(waiter)

    async def barrier(self) -> None:
        """Wait until the server has handled everything sent so far.

        One connection's frames are handled in order and every ping gets exactly one pong, so
        the pong for this ping comes after the replies to all earlier frames.
        """
        future = self.wait_for("pong")
        await self.send({"type": "ping"})
        await future

    async def receive_forever(self) -> None:
        try:
            async for frame in self.ws:
                if isinstance(frame, bytes):
                    if self.in_speech:
                        self.player.feed(frame)
                        self.marks.speech_bytes += len(frame)
                    continue
                message = json.loads(frame)
                await self._show(message)
                self._resolve(message)
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd else None
            print(f"{_stamp(self.t0)} connection closed ({code})")
            for _, future in self._waiters:
                if not future.done():
                    future.set_exception(exc)

    async def _show(self, m: dict[str, Any]) -> None:
        now = time.monotonic()
        at = _stamp(self.t0)
        kind = m.get("type")
        if kind == "state":
            extra = " ".join(f"{k}={m[k]!r}" for k in ("label", "agent") if k in m)
            print(f"{at} state {m.get('value')} {extra}".rstrip())
            if m.get("value") == "working" and self.marks.audio_end:
                self.marks.working = self.marks.working or now
            if m.get("value") == "idle" and self.marks.audio_end:
                self.marks.idle = now
        elif kind == "transcript":
            self.marks.transcript = self.marks.transcript or now
            print(f'{at} heard: "{m.get("text")}"')
        elif kind == "card":
            card = m["card"]
            self.cards[card["id"]] = card
            if card.get("kind") == "answer" and self.marks.audio_end:
                self.marks.card = self.marks.card or now
            print(f"{at} card")
            print(format_card(card))
            await self.send({"type": "displayed", "id": card["id"]})
        elif kind == "dismiss":
            self.cards.pop(m.get("card_id", ""), None)
            print(f"{at} dismiss {m.get('card_id')}")
        elif kind == "speech_start":
            self.marks.speech_start = self.marks.speech_start or now
            self.in_speech = True
            self.player.start()
            print(f"{at} speech_start (card {m.get('card_id')})")
        elif kind == "speech_end":
            self.marks.speech_end = self.marks.speech_end or now
            self.in_speech = False
            print(f"{at} speech_end")
        elif kind == "error":
            self.errors.append(str(m.get("code")))
            print(f"{at} ERROR {m.get('code')}: {m.get('text')}")
        elif kind == "welcome":
            print(f"{at} welcome from {m.get('server')} ({m.get('tz')}, {m.get('time')})")
        elif kind == "pong":
            pass
        else:
            print(f"{at} {m}")


def format_card(card: dict[str, Any]) -> str:
    lines = [f"  ┌ [{card['kind']}] {card['title']}  ({card['id']}, from {card['source']})"]
    if card.get("stale"):
        lines.append("  │ STALE")
    if card.get("body"):
        for line in textwrap.wrap(card["body"], 72):
            lines.append(f"  │ {line}")
    data = card.get("data") or {}
    for row in data.get("rows", []):
        stamp = f"  [{row['stamp']}]" if row.get("stamp") else ""
        lines.append(f"  │ · {row['text']}{stamp}")
    for tile in data.get("tiles", []):
        lines.append(f"  │ ▢ {tile['value']} {tile['label']}")
    if card["kind"] == "money":
        for item in data.get("items", []):
            lines.append(f"  │ {item['qty']}x {item['name']}")
        fixture = " (sample)" if data.get("fixture") else ""
        lines.append(f"  │ total {data.get('total')} {data.get('currency')}{fixture}")
    for action in card.get("actions", []):
        hold = f" hold {action['hold_ms']}ms" if action.get("hold_ms") else ""
        lines.append(f"  │ ({action['id']}) {action['label']}{hold}")
    if card.get("footer"):
        lines.append(f"  │ — {card['footer']}")
    lines.append("  └")
    return "\n".join(lines)


# --- audio sources -------------------------------------------------------------------------


async def pcm_from_say(text: str, voice: str | None) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "say.aiff"
        command = ["say", "-o", str(out)] + (["-v", voice] if voice else []) + [text]
        proc = await asyncio.create_subprocess_exec(*command)
        if await proc.wait():
            raise SystemExit("macOS `say` failed")
        return await decode_to_pcm(await asyncio.to_thread(out.read_bytes))


async def pcm_from_file(path: Path) -> bytes:
    return await decode_to_pcm(await asyncio.to_thread(path.read_bytes))


async def stream_pcm(device: Device, pcm: bytes) -> None:
    limit = int(p.TALK_LIMIT_SECONDS * p.BYTES_PER_SECOND)
    reason = "limit" if len(pcm) > limit else "released"
    await device.send({"type": "audio_start", "rate": 16000, "format": "s16le", "channels": 1})
    for frame in p.chunk_pcm(pcm[:limit]):
        await device.ws.send(frame)
    device.marks.audio_end = time.monotonic()
    await device.send({"type": "audio_end", "reason": reason})
    print(f"{_stamp(device.t0)} sent {min(len(pcm), limit) / p.BYTES_PER_SECOND:.1f}s audio")


async def stream_mic(device: Device) -> None:
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def callback(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))

    await loop.run_in_executor(None, input, "Press Enter to start talking… ")
    stop = loop.run_in_executor(None, input, "Recording. Press Enter to stop. ")
    await device.send({"type": "audio_start", "rate": 16000, "format": "s16le", "channels": 1})
    sent = 0
    limit = int(p.TALK_LIMIT_SECONDS * p.BYTES_PER_SECOND)
    reason = "released"
    with sd.RawInputStream(
        samplerate=p.SAMPLE_RATE, channels=1, dtype="int16", blocksize=2048, callback=callback
    ):
        while not stop.done():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=0.1)
            except TimeoutError:
                continue
            for frame in p.chunk_pcm(chunk[: limit - sent]):
                await device.ws.send(frame)
                sent += len(frame)
            if sent >= limit:
                reason = "limit"
                print("25 s limit reached.")
                break
    device.marks.audio_end = time.monotonic()
    await device.send({"type": "audio_end", "reason": reason})
    print(f"{_stamp(device.t0)} sent {sent / p.BYTES_PER_SECOND:.1f}s audio")


# --- main ----------------------------------------------------------------------------------


async def talk(device: Device, source: str, args: argparse.Namespace) -> None:
    if source == "say":
        pcm = await pcm_from_say(args.say, args.voice)
    elif source == "wav":
        pcm = await pcm_from_file(args.wav)
    else:
        pcm = b""
    done = device.wait_for("state:idle")
    if source == "mic":
        await stream_mic(device)
    else:
        await stream_pcm(device, pcm)
    await asyncio.wait_for(done, timeout=args.timeout)
    await device.player.drain()
    print(f"\ntimings (client-observed): {device.marks.summary()}")


async def run(args: argparse.Namespace, config: Config) -> int:
    url = args.url or f"ws://{config.host}:{config.port}{p.PATH}"
    token = args.token or config.token
    player = Player(enabled=not args.no_play)
    try:
        async with connect(url, compression=None, max_size=4 * p.MAX_TEXT_FRAME) as ws:
            device = Device(ws=ws, player=player)
            welcome = device.wait_for("welcome")
            receiver = asyncio.create_task(device.receive_forever())
            await device.send(
                {
                    "type": "hello",
                    "device_id": args.device_id,
                    "fw": CLIENT_FW,
                    "token": token,
                    "caps": ["mic", "speaker"],
                }
            )
            try:
                await asyncio.wait_for(welcome, timeout=10)
            except (ConnectionClosed, TimeoutError):
                print("Not paired: check CHARM_TOKEN.")
                return 2
            if args.edition:
                await device.send({"type": "request", "what": "edition"})
                await device.barrier()
            if args.pending or args.action:
                await device.send({"type": "request", "what": "pending"})
                await device.barrier()
            if args.action:
                card_id, _, action = args.action.partition(":")
                message: dict[str, Any] = {"type": "action", "card_id": card_id, "action": action}
                if args.held_ms is not None:
                    message["held_ms"] = args.held_ms
                print(f"{_stamp(device.t0)} action {card_id}:{action} held_ms={args.held_ms}")
                await device.send(message)
                await device.barrier()
            for source in ("say", "wav", "mic"):
                if getattr(args, source):
                    await talk(device, source, args)
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await receiver
            return 1 if device.errors else 0
    except OSError as exc:
        print(f"Can't reach the charm server at {url}: {exc}")
        return 3
    finally:
        player.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake Dex Charm device")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--say", metavar="TEXT", help="speak TEXT with macOS `say` and send it")
    source.add_argument("--wav", type=Path, metavar="FILE", help="send an audio file")
    source.add_argument("--mic", action="store_true", help="talk into the Mac mic")
    parser.add_argument("--voice", help="macOS `say` voice (e.g. Paulina for Spanish)")
    parser.add_argument("--edition", action="store_true", help="request the pocket edition")
    parser.add_argument("--pending", action="store_true", help="request pending cards")
    parser.add_argument("--action", metavar="CARD:ACTION", help="press a card button")
    parser.add_argument("--held-ms", type=int, help="hold duration to report with --action")
    parser.add_argument("--no-play", action="store_true", help="don't play Dex's speech")
    parser.add_argument("--url", help="default ws://CHARM_HOST:CHARM_PORT/charm")
    parser.add_argument("--token", help="default CHARM_TOKEN")
    parser.add_argument("--device-id", default=f"charm-client-{os.getpid()}")
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds to wait for Dex")
    args = parser.parse_args()
    if not (args.say or args.wav or args.mic or args.edition or args.pending or args.action):
        parser.error("nothing to do: pass --say, --wav, --mic, --edition, --pending or --action")
    sys.exit(asyncio.run(run(args, Config.from_env())))


if __name__ == "__main__":
    main()
