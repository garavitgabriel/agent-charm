"""Text to speech. `EdgeTTS` (free, the default) and `ElevenLabsTTS` (an API key) are the real
engines; `FallbackTTS` puts one in front of the other. Tests plug in a fake `TTS`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from .protocol import CHANNELS, SAMPLE_RATE

log = logging.getLogger(__name__)


class TTSError(Exception):
    pass


class TTS(Protocol):
    def stream(self, text: str, language: str) -> AsyncIterator[bytes]:
        """Yield 16 kHz s16le mono PCM as it's synthesized (chunks of any size)."""
        ...


def _ffmpeg_to_pcm(input_format: str | None) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if input_format:
        command += ["-f", input_format]
    command += ["-i", "pipe:0", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS)]
    return [*command, "pipe:1"]


async def decode_to_pcm(data: bytes, input_format: str | None = None) -> bytes:
    """Any audio ffmpeg understands -> 16 kHz s16le mono PCM."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *_ffmpeg_to_pcm(input_format),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise TTSError("ffmpeg is not installed") from exc
    stdout, stderr = await proc.communicate(data)
    if proc.returncode:
        raise TTSError(f"ffmpeg failed: {stderr.decode(errors='replace')[-200:]}")
    return stdout


class EdgeTTS:
    """edge-tts MP3, decoded through ffmpeg while it downloads. The voice follows the language.

    Speech starts as soon as the first MP3 chunk is decoded instead of after the whole reply is
    synthesized (Edge's first chunk alone can take several seconds).
    """

    def __init__(self, voice_en: str, voice_es: str) -> None:
        self.voices = {"en": voice_en, "es": voice_es}

    def voice_for(self, language: str) -> str:
        return self.voices.get(language, self.voices["en"])

    async def stream(self, text: str, language: str) -> AsyncIterator[bytes]:
        import edge_tts

        try:
            proc = await asyncio.create_subprocess_exec(
                *_ffmpeg_to_pcm("mp3"),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise TTSError("ffmpeg is not installed") from exc
        assert proc.stdin is not None and proc.stdout is not None
        stdin = proc.stdin
        mp3_bytes = 0

        async def feed() -> None:
            nonlocal mp3_bytes
            asked = time.monotonic()
            try:
                communicate = edge_tts.Communicate(text, self.voice_for(language))
                async for chunk in communicate.stream():
                    if chunk.get("type") == "audio":
                        if not mp3_bytes:
                            log.info("edge-tts first chunk in %.2fs", time.monotonic() - asked)
                        mp3_bytes += len(chunk["data"])
                        stdin.write(chunk["data"])
                        await stdin.drain()
            finally:
                stdin.close()

        log.info("edge-tts voice %s (%s)", self.voice_for(language), language)
        feeder = asyncio.create_task(feed(), name="edge-tts")
        try:
            while data := await proc.stdout.read(8192):
                yield data
            try:
                await feeder
            except Exception as exc:
                raise TTSError(f"edge-tts failed: {exc}") from exc
            if await proc.wait():
                raise TTSError("ffmpeg could not decode the speech")
            if not mp3_bytes:
                raise TTSError("edge-tts returned no audio")
        finally:
            feeder.cancel()
            with contextlib.suppress(BaseException):
                await feeder
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()


class ElevenLabsTTS:
    """ElevenLabs streaming speech, asked for raw 16 kHz s16le PCM, so there's no decoder.

    One voice id per language; the Flash v2.5 model is multilingual, so the same voice can serve
    both. The HTTP client is kept between replies (each sentence is its own call, and a warm
    connection saves the TLS handshake).
    """

    def __init__(
        self,
        api_key: str,
        voice_en: str,
        voice_es: str = "",
        model: str = "eleven_flash_v2_5",
        *,
        base_url: str = "https://api.elevenlabs.io",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.voices = {"en": voice_en, "es": voice_es or voice_en}
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = client

    def voice_for(self, language: str) -> str:
        return self.voices.get(language, self.voices["en"])

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))
        return self._client

    async def stream(self, text: str, language: str) -> AsyncIterator[bytes]:
        voice = self.voice_for(language)
        url = f"{self.base_url}/v1/text-to-speech/{voice}/stream"
        body = {"text": text, "model_id": self.model, "language_code": language}
        asked = time.monotonic()
        carry = b""  # s16le samples are 2 bytes: never split one across chunks
        total = 0
        log.info("elevenlabs voice %s model %s (%s)", voice, self.model, language)
        try:
            async with self._http().stream(
                "POST",
                url,
                params={"output_format": f"pcm_{SAMPLE_RATE}"},
                headers={"xi-api-key": self.api_key},
                json=body,
            ) as response:
                if response.status_code != 200:
                    detail = (await response.aread()).decode(errors="replace")[:200]
                    raise TTSError(f"elevenlabs {response.status_code}: {detail}")
                async for chunk in response.aiter_bytes():
                    if not total and chunk:
                        log.info("elevenlabs first chunk in %.2fs", time.monotonic() - asked)
                    total += len(chunk)
                    data = carry + chunk
                    cut = len(data) & ~1
                    carry = data[cut:]
                    if cut:
                        yield data[:cut]
        except httpx.HTTPError as exc:
            raise TTSError(f"elevenlabs request failed: {exc}") from exc
        if not total:
            raise TTSError("elevenlabs returned no audio")


class FallbackTTS:
    """The primary engine, or the fallback when the primary fails before its first byte.

    A failure after audio has started can't be papered over (part of the reply already played
    in one voice), so it propagates like any TTS failure.
    """

    def __init__(self, primary: TTS, fallback: TTS) -> None:
        self.primary = primary
        self.fallback = fallback

    async def stream(self, text: str, language: str) -> AsyncIterator[bytes]:
        started = False
        try:
            async for chunk in self.primary.stream(text, language):
                started = True
                yield chunk
            return
        except TTSError as exc:
            if started:
                raise
            log.warning("primary TTS failed before any audio (%s); using the fallback", exc)
        async for chunk in self.fallback.stream(text, language):
            yield chunk
