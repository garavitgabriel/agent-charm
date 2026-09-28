"""Fakes and a live localhost server. Tests never touch the network, Hermes or Edge TTS."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from charm_notes import FakeNoteStore
from websockets.asyncio.client import ClientConnection, connect

from charm_server.agent import Message
from charm_server.books import BookStore
from charm_server.cards import CardValidator
from charm_server.config import REPO_DIR, Config
from charm_server.server import start
from charm_server.session import Deps
from charm_server.stt import Transcript, check_audio

TOKEN = "test-token"
EXAMPLES = REPO_DIR / "contract" / "examples"
SCHEMA = REPO_DIR / "contract" / "card.schema.json"


def tone(seconds: float, amplitude: float = 0.3) -> bytes:
    t = np.arange(int(16000 * seconds)) / 16000
    return (np.sin(2 * np.pi * 440 * t) * amplitude * 32767).astype("<i2").tobytes()


@dataclass
class FakeSTT:
    text: str = "What is a metaphor?"
    language: str = "en"
    calls: int = 0

    async def transcribe(self, pcm: bytes) -> Transcript:
        self.calls += 1
        check_audio(pcm)  # the real too-short / silence gate
        return Transcript(self.text, self.language)


@dataclass
class FakeAgent:
    reply_text: str = "A metaphor says one thing is another. He is a lion. It commits harder."
    delay: float = 0.0
    error: Exception | None = None
    calls: list[list[Message]] = field(default_factory=list)
    finished: int = 0

    async def reply(self, messages: list[Message]) -> str:
        self.calls.append(messages)
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        self.finished += 1
        return self.reply_text


@dataclass
class FakeTTS:
    pcm: bytes = field(default_factory=lambda: tone(0.5))
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def stream(self, text: str, language: str) -> AsyncIterator[bytes]:
        self.calls.append((text, language))
        # Odd-sized pieces, like a decoder pipe delivers them.
        for i in range(0, len(self.pcm), 3001):
            yield self.pcm[i : i + 3001]


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        token=TOKEN,
        host="127.0.0.1",
        port=0,
        hermes_ssh_alias="unused",
        hermes_container="unused",
        cards_dir=EXAMPLES,
        schema_path=SCHEMA,
        action_log=tmp_path / "actions.jsonl",
        tz="America/Chicago",
        voice_en="en-voice",
        voice_es="es-voice",
        whisper_model="unused",
    )


@pytest.fixture
def validator() -> CardValidator:
    return CardValidator(SCHEMA)


@pytest.fixture
def books_path(tmp_path: Path) -> Path:
    return tmp_path / ".local" / "books.json"


@pytest.fixture
def deps(config: Config, validator: CardValidator, books_path: Path) -> Deps:
    return Deps(
        config=config,
        stt=FakeSTT(),
        agent=FakeAgent(),
        tts=FakeTTS(),
        validator=validator,
        speech_lead_s=None,
        books=BookStore(books_path),
        notes=FakeNoteStore(),
    )


class Client:
    """A minimal raw device for protocol tests."""

    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws

    async def send(self, message: dict[str, Any]) -> None:
        await self.ws.send(json.dumps(message))

    async def recv(self, timeout: float = 3.0) -> dict[str, Any] | bytes:
        frame = await asyncio.wait_for(self.ws.recv(), timeout)
        return frame if isinstance(frame, bytes) else json.loads(frame)

    async def until(
        self, done: Callable[[dict[str, Any]], bool], timeout: float = 5.0
    ) -> list[dict[str, Any] | bytes]:
        """Collect frames up to and including the first text frame where done() is true."""
        frames: list[dict[str, Any] | bytes] = []
        async with asyncio.timeout(timeout):
            while True:
                frame = await self.recv(timeout)
                frames.append(frame)
                if isinstance(frame, dict) and done(frame):
                    return frames

    async def until_idle(
        self, timeout: float = 5.0, agent: str = "dex"
    ) -> list[dict[str, Any] | bytes]:
        idle = {"type": "state", "value": "idle", "agent": agent}
        return await self.until(lambda m: m == idle, timeout)

    async def silent_for(self, seconds: float) -> list[dict[str, Any] | bytes]:
        frames: list[dict[str, Any] | bytes] = []
        try:
            while True:
                frames.append(await self.recv(seconds))
        except TimeoutError:
            return frames

    async def talk(self, pcm: bytes, reason: str = "released") -> None:
        await self.send({"type": "audio_start", "rate": 16000, "format": "s16le", "channels": 1})
        for i in range(0, len(pcm), 4096):
            await self.ws.send(pcm[i : i + 4096])
        await self.send({"type": "audio_end", "reason": reason})


def texts(frames: list[dict[str, Any] | bytes]) -> list[dict[str, Any]]:
    return [f for f in frames if isinstance(f, dict)]


def types(frames: list[dict[str, Any] | bytes]) -> list[str]:
    out = []
    for f in frames:
        if isinstance(f, bytes):
            if not out or out[-1] != "<pcm>":
                out.append("<pcm>")
        elif f["type"] == "state":
            out.append(f"state:{f['value']}")
        else:
            out.append(f["type"])
    return out


@dataclass
class Harness:
    deps: Deps
    url: str

    def with_deps(self, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(self.deps, key, value)

    async def raw(self) -> ClientConnection:
        return await connect(self.url, compression=None)

    async def device(self) -> Client:
        client = Client(await self.raw())
        await client.send(
            {"type": "hello", "device_id": "t", "fw": "test", "token": TOKEN, "caps": []}
        )
        welcome = await client.recv()
        assert isinstance(welcome, dict) and welcome["type"] == "welcome"
        assert await client.recv() == {"type": "state", "value": "idle", "agent": "dex"}
        return client


@pytest.fixture
async def harness(deps: Deps) -> AsyncIterator[Harness]:
    server = await start(deps, "127.0.0.1", 0)
    port = next(iter(server.sockets)).getsockname()[1]
    try:
        yield Harness(deps=deps, url=f"ws://127.0.0.1:{port}/charm")
    finally:
        server.close()
        await server.wait_closed()


def fake(deps: Deps) -> tuple[FakeSTT, FakeAgent, FakeTTS]:
    assert isinstance(deps.stt, FakeSTT)
    assert isinstance(deps.agent, FakeAgent)
    assert isinstance(deps.tts, FakeTTS)
    return deps.stt, deps.agent, deps.tts
