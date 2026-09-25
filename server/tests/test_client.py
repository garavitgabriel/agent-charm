"""charm-client against the fake-engine server (ffmpeg converts the input like it would live)."""

from __future__ import annotations

import argparse
import json
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from charm_server import client
from charm_server.config import Config

from .conftest import EXAMPLES, Harness, fake

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "say": None,
        "wav": None,
        "mic": False,
        "voice": None,
        "edition": False,
        "pending": False,
        "action": None,
        "held_ms": None,
        "no_play": True,
        "url": None,
        "token": None,
        "device_id": "test-client",
        "timeout": 10.0,
    }
    return argparse.Namespace(**(base | overrides))


def _config(harness: Harness) -> Config:
    return harness.deps.config


@needs_ffmpeg
async def test_wav_round_trip(
    harness: Harness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stt, _, _ = fake(harness.deps)
    wav = tmp_path / "q.wav"
    t = np.arange(int(44100 * 1.5)) / 44100
    mono = (np.sin(2 * np.pi * 440 * t) * 0.3 * 32767).astype("<i2")
    with wave.open(str(wav), "wb") as w:  # 44.1 kHz stereo on purpose: the client resamples
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(np.repeat(mono, 2).tobytes())
    code = await client.run(_args(wav=wav, url=harness.url), _config(harness))
    out = capsys.readouterr().out
    assert code == 0
    assert f'heard: "{stt.text}"' in out
    assert "[answer]" in out and "speech_end" in out
    assert "timings (client-observed): stt" in out and "total" in out


async def test_edition_and_money_hold(harness: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    code = await client.run(
        _args(edition=True, action="order-001:confirm", held_ms=2100, url=harness.url),
        _config(harness),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.index("ed-sports") < out.index("ed-almanac")
    assert "Sample order: nothing was charged." in out
    log = [json.loads(x) for x in harness.deps.config.action_log.read_text().splitlines()]
    assert log[-1]["outcome"] == "sample_ack"


async def test_short_hold_is_reported_as_an_error(harness: Harness) -> None:
    code = await client.run(
        _args(action="order-001:confirm", held_ms=500, url=harness.url), _config(harness)
    )
    assert code == 1


async def test_bad_token_exits_2(harness: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    code = await client.run(_args(edition=True, url=harness.url, token="nope"), _config(harness))
    assert code == 2 and "Not paired" in capsys.readouterr().out


async def test_unreachable_server_exits_3() -> None:
    cfg = Config.from_env(None)
    code = await client.run(_args(edition=True, url="ws://127.0.0.1:9/charm"), cfg)
    assert code == 3


def test_format_card_money() -> None:
    card = json.loads((EXAMPLES / "money.json").read_text())
    text = client.format_card(card)
    assert "(sample)" in text and "hold 2000ms" in text and "Corner Bistro" in text


def test_marks_summary() -> None:
    marks = client.Marks(
        audio_end=1, transcript=2, working=2.1, card=5, speech_start=6, speech_end=9
    )
    summary = marks.summary()
    assert "stt 1.00s" in summary and "agent 2.90s" in summary and "tts 1.00s" in summary
    assert "total 8.00s" in summary
