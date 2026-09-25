"""Text to speech. `EdgeTTS` is the real engine; tests plug in a fake `TTS`."""

from __future__ import annotations

import asyncio
from typing import Protocol

from .protocol import CHANNELS, SAMPLE_RATE


class TTSError(Exception):
    pass


class TTS(Protocol):
    async def synthesize(self, text: str, language: str) -> bytes:
        """Return 16 kHz s16le mono PCM."""
        ...


async def decode_to_pcm(data: bytes, input_format: str | None = None) -> bytes:
    """Any audio ffmpeg understands -> 16 kHz s16le mono PCM."""
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if input_format:
        command += ["-f", input_format]
    command += ["-i", "pipe:0", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS)]
    command += ["pipe:1"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
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
    """edge-tts MP3, decoded through ffmpeg. The voice follows the detected language."""

    def __init__(self, voice_en: str, voice_es: str) -> None:
        self.voices = {"en": voice_en, "es": voice_es}

    def voice_for(self, language: str) -> str:
        return self.voices.get(language, self.voices["en"])

    async def synthesize(self, text: str, language: str) -> bytes:
        import edge_tts

        mp3 = bytearray()
        communicate = edge_tts.Communicate(text, self.voice_for(language))
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                mp3.extend(chunk["data"])
        if not mp3:
            raise TTSError("edge-tts returned no audio")
        return await decode_to_pcm(bytes(mp3), input_format="mp3")
