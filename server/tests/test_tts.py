from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from charm_server.config import Config
from charm_server.server import make_tts
from charm_server.tts import EdgeTTS, ElevenLabsTTS, FallbackTTS, TTSError


class ChunkedPCM(httpx.AsyncByteStream):
    """A response body delivered in the given (odd-sized) pieces."""

    def __init__(self, pieces: list[bytes]) -> None:
        self.pieces = pieces

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for piece in self.pieces:
            yield piece


def eleven(handler: httpx.MockTransport, **kwargs: str) -> ElevenLabsTTS:
    client = httpx.AsyncClient(transport=handler)
    return ElevenLabsTTS("sk-test", "voice-en", kwargs.get("voice_es", "voice-es"), client=client)


async def collect(stream: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in stream]


async def test_elevenlabs_asks_for_16k_pcm_and_keeps_samples_whole() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, stream=ChunkedPCM([b"\x01\x02\x03", b"\x04\x05", b"\x06"]))

    chunks = await collect(eleven(httpx.MockTransport(handler)).stream("Hola", "es"))

    assert b"".join(chunks) == b"\x01\x02\x03\x04\x05\x06"
    assert all(len(chunk) % 2 == 0 for chunk in chunks)
    request = seen[0]
    assert request.url.path == "/v1/text-to-speech/voice-es/stream"
    assert request.url.params["output_format"] == "pcm_16000"
    assert request.headers["xi-api-key"] == "sk-test"
    assert json.loads(request.content) == {
        "text": "Hola",
        "model_id": "eleven_flash_v2_5",
        "language_code": "es",
    }


async def test_elevenlabs_spanish_defaults_to_the_english_voice() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, content=b"\x00\x00")

    await collect(eleven(httpx.MockTransport(handler), voice_es="").stream("Hola", "es"))
    assert paths == ["/v1/text-to-speech/voice-en/stream"]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401, json={"detail": "invalid_api_key"}), "elevenlabs 401"),
        (httpx.Response(200, content=b""), "no audio"),
    ],
)
async def test_elevenlabs_failures_are_tts_errors(response: httpx.Response, message: str) -> None:
    tts = eleven(httpx.MockTransport(lambda request: response))
    with pytest.raises(TTSError, match=message):
        await collect(tts.stream("Hi", "en"))


async def test_elevenlabs_network_error_is_a_tts_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(TTSError, match="request failed"):
        await collect(eleven(httpx.MockTransport(handler)).stream("Hi", "en"))


class Scripted:
    def __init__(self, chunks: list[bytes], fail_after: int | None = None) -> None:
        self.chunks = chunks
        self.fail_after = fail_after
        self.calls = 0

    async def stream(self, text: str, language: str) -> AsyncIterator[bytes]:
        self.calls += 1
        for i, chunk in enumerate(self.chunks):
            if self.fail_after == i:
                raise TTSError("boom")
            yield chunk
        if self.fail_after == len(self.chunks):
            raise TTSError("boom")


async def test_fallback_takes_over_when_the_primary_fails_before_audio() -> None:
    primary, fallback = Scripted([], fail_after=0), Scripted([b"ed", b"ge"])
    assert await collect(FallbackTTS(primary, fallback).stream("Hi", "en")) == [b"ed", b"ge"]
    assert fallback.calls == 1


async def test_fallback_is_unused_when_the_primary_works() -> None:
    primary, fallback = Scripted([b"el", b"ev"]), Scripted([b"edge"])
    assert await collect(FallbackTTS(primary, fallback).stream("Hi", "en")) == [b"el", b"ev"]
    assert fallback.calls == 0


async def test_fallback_does_not_mix_voices_midway() -> None:
    primary, fallback = Scripted([b"el", b"ev"], fail_after=1), Scripted([b"edge"])
    with pytest.raises(TTSError):
        await collect(FallbackTTS(primary, fallback).stream("Hi", "en"))
    assert fallback.calls == 0


def test_make_tts_is_edge_without_a_key(config: Config) -> None:
    assert isinstance(make_tts(config, "en-A", "es-A", "voice", ""), EdgeTTS)


def test_make_tts_is_edge_for_a_character_without_a_voice(config: Config) -> None:
    keyed = replace(config, elevenlabs_api_key="sk-test")
    assert isinstance(make_tts(keyed, "en-A", "es-A", "", ""), EdgeTTS)


def test_make_tts_puts_elevenlabs_in_front_of_edge(config: Config) -> None:
    keyed = replace(config, elevenlabs_api_key="sk-test")
    tts = make_tts(keyed, "en-A", "es-A", "voice-en", "")
    assert isinstance(tts, FallbackTTS)
    assert isinstance(tts.primary, ElevenLabsTTS)
    assert tts.primary.voices == {"en": "voice-en", "es": "voice-en"}
    assert isinstance(tts.fallback, EdgeTTS)


def test_elevenlabs_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("ELEVENLABS_MODEL", "ELEVENLABS_VOICE_ES", "ELEVENLABS_VOICE_COACH_ES"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", " sk-env ")
    monkeypatch.setenv("ELEVENLABS_VOICE_EN", "dex-voice")
    monkeypatch.setenv("ELEVENLABS_VOICE_COACH_EN", "coach-voice")
    config = Config.from_env(None)
    assert config.elevenlabs_api_key == "sk-env"
    assert config.elevenlabs_model == "eleven_flash_v2_5"
    assert (config.elevenlabs_voice_en, config.elevenlabs_voice_es) == ("dex-voice", "")
    assert config.elevenlabs_voice_coach_en == "coach-voice"
