"""Speech to text. `WhisperSTT` is the real engine; tests plug in a fake `STT`."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from .protocol import MIN_AUDIO_SECONDS, SAMPLE_RATE

log = logging.getLogger(__name__)

SILENCE_RMS = 0.001  # Same floor Margin uses for "I couldn't hear you".


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str  # ISO 639-1, e.g. "en" or "es"


class TooShort(Exception):
    """Less than 0.5 s of audio, or silence."""


class STT(Protocol):
    async def transcribe(self, pcm: bytes) -> Transcript: ...


def pcm_to_float(pcm: bytes) -> np.ndarray[Any, np.dtype[np.float32]]:
    return np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float32) / 32768.0


def check_audio(pcm: bytes) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Raise TooShort for <0.5 s or silent audio; return float samples otherwise."""
    samples = pcm_to_float(pcm)
    if len(samples) < SAMPLE_RATE * MIN_AUDIO_SECONDS:
        raise TooShort("That was too short. Hold the button while you talk.")
    rms = float(np.sqrt(np.mean(samples * samples)))
    if rms < SILENCE_RMS:
        raise TooShort("I only heard silence. Hold me closer and try again.")
    return samples


class WhisperSTT:
    """faster-whisper `base`, int8 on CPU, VAD on, language auto-detected."""

    def __init__(self, model: str = "base") -> None:
        self._model_name = model
        self._model: Any = None
        self._lock = threading.Lock()

    def load(self) -> Any:
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                log.info("loading faster-whisper %s (int8, cpu)", self._model_name)
                self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")
            return self._model

    def _run(self, pcm: bytes) -> Transcript:
        samples = check_audio(pcm)
        segments, info = self.load().transcribe(samples, beam_size=5, vad_filter=True)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return Transcript(text=text, language=str(info.language or "en"))

    async def transcribe(self, pcm: bytes) -> Transcript:
        return await asyncio.to_thread(self._run, pcm)
