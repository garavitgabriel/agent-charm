"""The bridge's HTTP API v1 (docs/HTTP.md): turn-based HTTP for clients without a WebSocket.

One `Session` per device id, the same one the WebSocket uses, so every rule (turns, money,
Coach, reading, notes) is the WebSocket path's own code. Its `send_raw` appends to the device's
event log instead of a socket: text frames become events (plus `seq`), and the binary speech
between `speech_start` and `speech_end` is cut into WAV clips served from `/v1/speech/`.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import math
import re
import struct
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import web

from . import SERVER_ID
from . import protocol as p
from .session import Deps, Session

log = logging.getLogger(__name__)

API = "/v1"
LOG_SIZE = 200  # events kept per device
MAX_WAIT_S = 25.0  # the longest long poll
CLIP_SECONDS = 1.5  # a clip is published once it holds this much audio, or at speech_end
CLIP_BYTES = int(CLIP_SECONDS * p.BYTES_PER_SECOND)
MAX_CLIPS = 20  # the most recent clips kept per device...
CLIP_TTL_S = 600.0  # ...for at most this long
WAV_HEADER_BYTES = 44
MAX_TURN_BODY = p.MAX_AUDIO_BYTES + 64 * 1024  # the audio limit plus room for RIFF chunks
WAV_TYPES = ("audio/wav", "audio/x-wav", "audio/wave")
DEVICE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
CLIP_PATH = re.compile(r"^([A-Za-z0-9_-]{1,64})\.wav$")

Clock = Callable[[], float]


# --- errors ----------------------------------------------------------------------------------


def _error(status: int, code: str, text: str) -> web.Response:
    return web.json_response({"code": code, "text": text}, status=status)


def _auth() -> web.Response:
    return _error(401, "auth", "This app isn't paired with the server.")


def _bad(text: str) -> web.Response:
    return _error(400, "bad_request", text)


def _no_session() -> web.Response:
    return _error(404, "no_session", "No session for this device. Say hello again.")


def _not_found() -> web.Response:
    return _error(404, "not_found", "Nothing here.")


def _audio_format(text: str = "I need a 16 kHz, mono, 16-bit PCM WAV.") -> web.Response:
    return _error(415, "audio_format", text)


def _too_long() -> web.Response:
    limit = p.MAX_AUDIO_BYTES / p.BYTES_PER_SECOND
    return _error(413, "too_long", f"Recordings can be at most {limit:g} seconds.")


# --- WAV -------------------------------------------------------------------------------------


class WavError(ValueError):
    pass


def wav_pcm(body: bytes) -> bytes:
    """The PCM inside a RIFF/WAVE file that must be PCM s16le, mono, 16 000 Hz.

    Walks the chunks (recorders may add some before `data`); raises `WavError` otherwise.
    """
    if len(body) < 12 or body[:4] != b"RIFF" or body[8:12] != b"WAVE":
        raise WavError("not a RIFF/WAVE file")
    fmt: tuple[int, int, int, int] | None = None
    pos = 12
    while pos + 8 <= len(body):
        chunk_id = body[pos : pos + 4]
        (size,) = struct.unpack_from("<I", body, pos + 4)
        start = pos + 8
        if chunk_id == b"fmt ":
            if size < 16 or start + 16 > len(body):
                raise WavError("short fmt chunk")
            tag, channels, rate, _, _, bits = struct.unpack_from("<HHIIHH", body, start)
            fmt = (tag, channels, rate, bits)
        elif chunk_id == b"data":
            if fmt is None:
                raise WavError("data before fmt")
            if fmt != (1, p.CHANNELS, p.SAMPLE_RATE, 16):
                raise WavError(f"format {fmt} is not PCM, mono, 16 kHz, 16-bit")
            pcm = body[start : min(start + size, len(body))]  # streaming writers may overstate
            return pcm[: len(pcm) - len(pcm) % 2]
        pos = start + size + (size % 2)  # chunks are word-aligned
    raise WavError("no data chunk")


def wav_bytes(pcm: bytes) -> bytes:
    """A canonical 44-byte-header WAV around s16le mono 16 kHz PCM."""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        p.CHANNELS,
        p.SAMPLE_RATE,
        p.BYTES_PER_SECOND,
        2 * p.CHANNELS,
        16,
        b"data",
        len(pcm),
    )
    return header + pcm


# --- one device ------------------------------------------------------------------------------


@dataclass
class Clip:
    wav: bytes
    created: float


@dataclass
class Device:
    """One device's session, event log, speech clips and waiting poll."""

    device_id: str
    clock: Clock
    log_size: int = LOG_SIZE
    max_clips: int = MAX_CLIPS
    clip_ttl_s: float = CLIP_TTL_S
    session: Session | None = None
    last_seen: float = 0.0
    end: int = 0  # the last seq assigned
    events: deque[dict[str, Any]] = field(default_factory=deque)
    clips: OrderedDict[str, Clip] = field(default_factory=OrderedDict)
    _waiter: asyncio.Future[bool] | None = None  # True: events arrived; False: superseded
    _in_speech: bool = False
    _speech_card: str | None = None
    _speech_n: int = 0
    _speech_buf: bytearray = field(default_factory=bytearray)

    def __post_init__(self) -> None:
        self.events = deque(maxlen=self.log_size)
        self.last_seen = self.clock()

    @property
    def waiting(self) -> bool:
        return self._waiter is not None and not self._waiter.done()

    def touch(self) -> None:
        self.last_seen = self.clock()

    # --- the Session's transport ---

    async def send_raw(self, frame: str | bytes) -> None:
        if isinstance(frame, bytes):
            if not self._in_speech:
                log.warning("device %s: audio outside a speech span dropped", self.device_id)
                return
            self._speech_buf.extend(frame)
            if len(self._speech_buf) >= CLIP_BYTES:
                self._cut_clip()
            return
        message = json.loads(frame)
        kind = message.get("type")
        if kind == "speech_start":
            self._in_speech = True
            card = message.get("card_id")
            self._speech_card = card if isinstance(card, str) else None
            self._speech_n = 0
            self._speech_buf.clear()
            self.append(message)
        elif kind == "speech_end":
            if self._speech_buf:
                self._cut_clip()
            self._in_speech = False
            self._speech_card = None
            self.append(message)
        else:
            self.append(message)

    def _cut_clip(self) -> None:
        pcm = bytes(self._speech_buf)
        self._speech_buf.clear()
        clip_id = uuid.uuid4().hex
        self.clips[clip_id] = Clip(wav_bytes(pcm), self.clock())
        self.prune_clips()
        self._speech_n += 1
        event: dict[str, Any] = {
            "type": "speech_clip",
            "clip_id": clip_id,
            "seq_in_speech": self._speech_n,
            "url": f"{API}/speech/{clip_id}.wav",
            "ms": round(len(pcm) * 1000 / p.BYTES_PER_SECOND),
        }
        if self._speech_card is not None:
            event["card_id"] = self._speech_card
        self.append(event)

    def prune_clips(self) -> None:
        cutoff = self.clock() - self.clip_ttl_s
        while self.clips and (
            len(self.clips) > self.max_clips or next(iter(self.clips.values())).created < cutoff
        ):
            self.clips.popitem(last=False)

    def clip(self, clip_id: str) -> bytes | None:
        self.prune_clips()
        found = self.clips.get(clip_id)
        return found.wav if found is not None else None

    # --- the event log ---

    def append(self, message: dict[str, Any]) -> None:
        self.end += 1
        self.events.append({**message, "seq": self.end})
        if self._waiter is not None and not self._waiter.done():
            self._waiter.set_result(True)

    def after(self, cursor: int) -> list[dict[str, Any]] | None:
        """Events with seq > cursor, or None when some of them were already dropped."""
        if self.events and cursor < self.events[0]["seq"] - 1:
            return None
        return [e for e in self.events if e["seq"] > cursor]

    async def poll(self, after: int, wait: float) -> dict[str, Any]:
        after = min(after, self.end)
        events = self.after(after)
        if events is None:
            return {"cursor": self.end, "events": [], "reset": True}
        if events or wait <= 0:
            return self._page(after, events)
        if self._waiter is not None and not self._waiter.done():
            self._waiter.set_result(False)  # one waiting poll per device: the newest wins
        waiter: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._waiter = waiter
        arrived = False
        try:
            async with asyncio.timeout(wait):
                arrived = await waiter
        except TimeoutError:
            pass
        finally:
            if self._waiter is waiter:
                self._waiter = None
        if not arrived:
            return {"cursor": after, "events": []}
        events = self.after(after)
        if events is None:
            return {"cursor": self.end, "events": [], "reset": True}
        return self._page(after, events)

    @staticmethod
    def _page(after: int, events: list[dict[str, Any]]) -> dict[str, Any]:
        return {"cursor": events[-1]["seq"] if events else after, "events": events}

    def release(self) -> None:
        """Complete a waiting poll (shutdown or expiry)."""
        if self._waiter is not None and not self._waiter.done():
            self._waiter.set_result(False)


# --- the app ---------------------------------------------------------------------------------


class HttpApi:
    """Routes, auth and the device table. `clock`, `log_size` and the clip limits are injectable
    so tests can expire things without waiting."""

    def __init__(
        self,
        deps: Deps,
        *,
        clock: Clock = time.monotonic,
        log_size: int = LOG_SIZE,
        max_clips: int = MAX_CLIPS,
        clip_ttl_s: float = CLIP_TTL_S,
    ) -> None:
        self.deps = deps
        self.clock = clock
        self.log_size = log_size
        self.max_clips = max_clips
        self.clip_ttl_s = clip_ttl_s
        self.devices: dict[str, Device] = {}
        self._sweeper: asyncio.Task[None] | None = None

    @property
    def session_ttl(self) -> float:
        return self.deps.config.http_session_ttl

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self._middleware], client_max_size=MAX_TURN_BODY)
        app.router.add_get(f"{API}/health", self.health)
        app.router.add_post(f"{API}/hello", self.hello)
        app.router.add_post(f"{API}/turns", self.turns)
        app.router.add_post(f"{API}/actions", self.actions)
        app.router.add_post(f"{API}/requests", self.requests)
        app.router.add_post(f"{API}/cancel", self.cancel)
        app.router.add_get(f"{API}/events", self.events)
        app.router.add_get(API + "/speech/{name}", self.speech)
        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)
        return app

    # --- lifecycle ---

    async def _on_startup(self, app: web.Application) -> None:
        self._sweeper = asyncio.create_task(self._sweep_forever(), name="http-sweeper")

    async def _on_cleanup(self, app: web.Application) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
        for device_id in list(self.devices):
            await self._drop(device_id)

    async def _sweep_forever(self) -> None:
        while True:
            await asyncio.sleep(max(1.0, min(60.0, self.session_ttl / 4)))
            await self.sweep()

    async def sweep(self) -> None:
        """Expire idle sessions and old clips."""
        cutoff = self.clock() - self.session_ttl
        for device_id, device in list(self.devices.items()):
            if device.last_seen < cutoff and not device.waiting:
                log.info("http device %s expired", device_id)
                await self._drop(device_id)
            else:
                device.prune_clips()

    async def _drop(self, device_id: str) -> None:
        device = self.devices.pop(device_id, None)
        if device is None:
            return
        device.release()
        if device.session is not None:
            await device.session.close()

    # --- auth and device lookup ---

    @web.middleware
    async def _middleware(
        self, request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
    ) -> web.StreamResponse:
        if request.path != f"{API}/health" and not self._authorized(request):
            return _auth()
        try:
            return await handler(request)
        except web.HTTPNotFound:
            return _not_found()
        except web.HTTPMethodNotAllowed:
            return _error(405, "bad_request", "Wrong method for this path.")

    def _authorized(self, request: web.Request) -> bool:
        token = self.deps.config.token
        header = request.headers.get("Authorization", "")
        scheme, _, offered = header.partition(" ")
        if not token or scheme.lower() != "bearer" or not offered:
            return False
        return hmac.compare_digest(offered.strip().encode(), token.encode())

    def _device_id(self, request: web.Request) -> str | None:
        device_id = request.headers.get("X-Charm-Device", "")
        return device_id if DEVICE_ID.match(device_id) else None

    def _device(self, request: web.Request) -> Device | web.Response:
        device_id = self._device_id(request)
        if device_id is None:
            return _bad("X-Charm-Device must be 1-64 characters of A-Z a-z 0-9 . _ -")
        device = self.devices.get(device_id)
        if device is None or device.session is None:
            return _no_session()
        if device.last_seen < self.clock() - self.session_ttl:
            return _no_session()  # expired; the sweeper hasn't got to it yet
        device.touch()
        return device

    @staticmethod
    async def _json(request: web.Request) -> dict[str, Any] | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    # --- endpoints ---

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "server": SERVER_ID})

    async def hello(self, request: web.Request) -> web.Response:
        device_id = self._device_id(request)
        if device_id is None:
            return _bad("X-Charm-Device must be 1-64 characters of A-Z a-z 0-9 . _ -")
        body = await self._json(request)
        if body is None:
            return _bad("The body must be a JSON object.")
        if body.get("device_id") != device_id:
            return _bad("device_id must match the X-Charm-Device header.")
        device = self.devices.get(device_id)
        if device is not None and device.last_seen < self.clock() - self.session_ttl:
            await self._drop(device_id)
            device = None
        if device is None:
            device = Device(
                device_id,
                self.clock,
                log_size=self.log_size,
                max_clips=self.max_clips,
                clip_ttl_s=self.clip_ttl_s,
            )
            device.session = Session(
                send_raw=device.send_raw,
                deps=replace(self.deps, speech_lead_s=None),  # no real-time pacing over HTTP
                device_id=device_id,
            )
            self.devices[device_id] = device
            log.info(
                "http device %s hello (app=%s version=%s caps=%s)",
                device_id,
                body.get("app"),
                body.get("version"),
                body.get("caps"),
            )
        device.touch()
        session = device.session
        assert session is not None
        cursor = device.end
        await session.open()  # the greeting lands in the log after `cursor`
        tz = self.deps.config.tz
        return web.json_response(
            {
                "server": SERVER_ID,
                "time": datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds"),
                "tz": tz,
                "agent": session.agent,
                "cursor": cursor,
            }
        )

    async def turns(self, request: web.Request) -> web.Response:
        found = self._device(request)
        if isinstance(found, web.Response):
            return found
        session = found.session
        assert session is not None
        if request.content_type not in WAV_TYPES:
            return _audio_format("Send the recording as Content-Type: audio/wav.")
        if request.content_length is not None and request.content_length > MAX_TURN_BODY:
            return _too_long()
        try:
            body = await request.read()
        except web.HTTPRequestEntityTooLarge:
            return _too_long()
        try:
            pcm = wav_pcm(body)
        except WavError as exc:
            return _audio_format(f"I need a 16 kHz, mono, 16-bit PCM WAV ({exc}).")
        if len(pcm) > p.MAX_AUDIO_BYTES:
            return _too_long()
        if session.busy:
            return _error(409, "busy", "I'm still on the last one. Cancel it or wait a moment.")
        # The WebSocket path's own job: audio_start, the PCM in frames, audio_end{released}.
        start = {"type": "audio_start", "rate": p.SAMPLE_RATE, "format": p.SAMPLE_FORMAT}
        await session.handle_text(json.dumps({**start, "channels": p.CHANNELS}))
        for frame in p.chunk_pcm(pcm):
            await session.handle_binary(frame)
        await session.handle_text(json.dumps({"type": "audio_end", "reason": "released"}))
        return web.json_response({"turn_id": uuid.uuid4().hex}, status=202)

    async def actions(self, request: web.Request) -> web.Response:
        found = self._device(request)
        if isinstance(found, web.Response):
            return found
        body = await self._json(request)
        if body is None:
            return _bad("The body must be a JSON object.")
        card_id, action, held = body.get("card_id"), body.get("action"), body.get("held_ms")
        if not isinstance(card_id, str) or not card_id or not isinstance(action, str):
            return _bad("card_id and action are required strings.")
        if held is not None and (not isinstance(held, int) or isinstance(held, bool)):
            return _bad("held_ms must be an integer.")
        message: dict[str, Any] = {"type": "action", "card_id": card_id, "action": action}
        if held is not None:
            message["held_ms"] = held
        assert found.session is not None
        await found.session.handle_text(json.dumps(message))
        return web.json_response({}, status=202)

    async def requests(self, request: web.Request) -> web.Response:
        found = self._device(request)
        if isinstance(found, web.Response):
            return found
        body = await self._json(request)
        if body is None:
            return _bad("The body must be a JSON object.")
        what = body.get("what")
        if what not in p.REQUEST_WHATS:
            return _bad(f"what must be one of {', '.join(p.REQUEST_WHATS)}.")
        assert found.session is not None
        await found.session.handle_text(json.dumps({"type": "request", "what": what}))
        return web.json_response({}, status=202)

    async def cancel(self, request: web.Request) -> web.Response:
        found = self._device(request)
        if isinstance(found, web.Response):
            return found
        assert found.session is not None
        await found.session.handle_text(json.dumps({"type": "cancel"}))
        return web.json_response({}, status=202)

    async def events(self, request: web.Request) -> web.Response:
        found = self._device(request)
        if isinstance(found, web.Response):
            return found
        try:
            after = int(request.query.get("after", "0"))
            wait = float(request.query.get("wait", str(MAX_WAIT_S)))
        except ValueError:
            return _bad("after must be an integer and wait a number of seconds.")
        if after < 0 or not math.isfinite(wait):
            return _bad("after must be >= 0 and wait a number of seconds.")
        page = await found.poll(after, max(0.0, min(wait, MAX_WAIT_S)))  # wait is 0-25 s
        found.touch()
        return web.json_response(page)

    async def speech(self, request: web.Request) -> web.Response:
        found = self._device(request)
        if isinstance(found, web.Response):
            return found
        match = CLIP_PATH.match(request.match_info["name"])
        wav = found.clip(match.group(1)) if match else None
        if wav is None:
            return _not_found()
        return web.Response(body=wav, content_type="audio/wav")


@dataclass
class HttpServer:
    api: HttpApi
    runner: web.AppRunner
    port: int

    async def close(self) -> None:
        await self.runner.cleanup()


async def start(deps: Deps, host: str, port: int, **options: Any) -> HttpServer:
    """Serve the HTTP API on host:port (0 picks a free port, for tests)."""
    api = HttpApi(deps, **options)
    runner = web.AppRunner(api.app(), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    bound = runner.addresses[0][1] if runner.addresses else port
    return HttpServer(api=api, runner=runner, port=int(bound))
