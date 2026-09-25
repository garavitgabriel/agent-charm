"""Text to speech. `EdgeTTS` is the real engine; tests plug in a fake `TTS`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Protocol

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
            try:
                communicate = edge_tts.Communicate(text, self.voice_for(language))
                async for chunk in communicate.stream():
                    if chunk.get("type") == "audio":
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
