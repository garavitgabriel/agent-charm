"""docs/HTTP.md over a real localhost aiohttp server, a real Session and the fake engines."""

from __future__ import annotations

import asyncio
import io
import json
import struct
import time
import wave
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from typing import Any

import aiohttp
import pytest

from charm_server import SERVER_ID
from charm_server import protocol as p
from charm_server.http_api import HttpServer, WavError, start, wav_bytes, wav_pcm
from charm_server.session import SAMPLE_ORDER_TEXT, Deps

from .conftest import TOKEN, FakeAgent, FakeTTS, fake, tone

DEVICE = "watch-1"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def wav(pcm: bytes, rate: int = 16000, channels: int = 1, bits: int = 16) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(bits // 8)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


@dataclass
class Http:
    server: HttpServer
    deps: Deps
    clock: FakeClock
    client: aiohttp.ClientSession

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.port}"

    def headers(self, device: str | None = DEVICE, token: str | None = TOKEN) -> dict[str, str]:
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if device is not None:
            headers["X-Charm-Device"] = device
        return headers

    async def call(
        self,
        method: str,
        path: str,
        *,
        device: str | None = DEVICE,
        token: str | None = TOKEN,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        headers = {**self.headers(device, token), **kwargs.pop("headers", {})}
        async with self.client.request(
            method, self.base + path, headers=headers, **kwargs
        ) as response:
            if response.content_type == "application/json":
                return response.status, await response.json()
            return response.status, await response.read()

    async def hello(self, device: str = DEVICE) -> int:
        status, body = await self.call(
            "POST",
            "/v1/hello",
            device=device,
            json={"device_id": device, "app": "test", "version": "0", "caps": ["mic"]},
        )
        assert status == 200, body
        return int(body["cursor"])

    async def ready(self, device: str = DEVICE) -> int:
        """Hello, then read past the greeting; returns the cursor after it."""
        page = await self.poll(await self.hello(device))
        assert page["events"][-1]["type"] == "state"
        return int(page["cursor"])

    async def post(self, path: str, body: Any = None) -> tuple[int, Any]:
        return await self.call("POST", path, json=body)

    async def turn(self, pcm: bytes, content_type: str = "audio/wav") -> tuple[int, Any]:
        return await self.call(
            "POST", "/v1/turns", data=wav(pcm), headers={"Content-Type": content_type}
        )

    async def poll(self, after: int, wait: float = 0) -> dict[str, Any]:
        status, body = await self.call("GET", f"/v1/events?after={after}&wait={wait}")
        assert status == 200, body
        assert isinstance(body, dict)
        return body

    async def until(
        self, after: int, done: Callable[[dict[str, Any]], bool], timeout: float = 5.0
    ) -> tuple[int, list[dict[str, Any]]]:
        """Long-poll events up to and including the first where done() is true."""
        events: list[dict[str, Any]] = []
        async with asyncio.timeout(timeout):
            while True:
                page = await self.poll(after, wait=2)
                assert "reset" not in page
                for event in page["events"]:
                    events.append(event)
                    if done(event):
                        return event["seq"], events
                after = page["cursor"]

    async def until_idle(self, after: int) -> tuple[int, list[dict[str, Any]]]:
        return await self.until(after, lambda e: e["type"] == "state" and e["value"] == "idle")


def kinds(events: list[dict[str, Any]]) -> list[str]:
    return [f"state:{e['value']}" if e["type"] == "state" else e["type"] for e in events]


@pytest.fixture
async def http(deps: Deps) -> AsyncIterator[Http]:
    clock = FakeClock()
    server = await start(deps, "127.0.0.1", 0, clock=clock)
    try:
        async with aiohttp.ClientSession() as client:
            yield Http(server=server, deps=deps, clock=clock, client=client)
    finally:
        await server.close()


# --- auth and errors -------------------------------------------------------------------------


async def test_health_needs_no_auth(http: Http) -> None:
    status, body = await http.call("GET", "/v1/health", device=None, token=None)
    assert status == 200 and body == {"ok": True, "server": SERVER_ID}


@pytest.mark.parametrize("token", [None, "wrong", ""])
@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/v1/hello"), ("GET", "/v1/events?after=0"), ("GET", "/v1/speech/x.wav")],
)
async def test_missing_or_wrong_token_is_401(
    http: Http, token: str | None, method: str, path: str
) -> None:
    status, body = await http.call(method, path, token=token, json={"device_id": DEVICE})
    assert status == 401 and body["code"] == "auth" and body["text"]


async def test_non_bearer_scheme_is_401(http: Http) -> None:
    status, body = await http.call(
        "POST", "/v1/hello", token=None, headers={"Authorization": f"Basic {TOKEN}"}, json={}
    )
    assert status == 401 and body["code"] == "auth"


async def test_empty_server_token_refuses_everyone(http: Http) -> None:
    http.deps.config = replace(http.deps.config, token="")
    status, body = await http.call("POST", "/v1/hello", token="", json={"device_id": DEVICE})
    assert status == 401 and body["code"] == "auth"


@pytest.mark.parametrize("device", [None, "", "has space", "x" * 65, "slash/no"])
async def test_bad_device_header_is_400(http: Http, device: str | None) -> None:
    status, body = await http.call(
        "POST", "/v1/hello", device=device, json={"device_id": device or ""}
    )
    assert status == 400 and body["code"] == "bad_request"


async def test_hello_body_must_match_the_header(http: Http) -> None:
    status, body = await http.call("POST", "/v1/hello", json={"device_id": "someone-else"})
    assert status == 400 and body["code"] == "bad_request"
    status, body = await http.call("POST", "/v1/hello", data=b"{nope")
    assert status == 400 and body["code"] == "bad_request"
    status, body = await http.call("POST", "/v1/hello", json=["a list"])
    assert status == 400 and body["code"] == "bad_request"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/actions"),
        ("POST", "/v1/requests"),
        ("POST", "/v1/cancel"),
        ("GET", "/v1/events?after=0"),
        ("GET", "/v1/speech/abc.wav"),
    ],
)
async def test_no_hello_is_404_no_session(http: Http, method: str, path: str) -> None:
    status, body = await http.call(method, path, json={})
    assert status == 404 and body["code"] == "no_session"


async def test_turn_without_hello_is_404_no_session(http: Http) -> None:
    status, body = await http.turn(tone(1.0))
    assert status == 404 and body["code"] == "no_session"


async def test_unknown_path_is_404_not_found(http: Http) -> None:
    status, body = await http.call("GET", "/v1/nope")
    assert status == 404 and body["code"] == "not_found"


async def test_bad_bodies_are_400(http: Http) -> None:
    await http.hello()
    for path, body in [
        ("/v1/requests", {"what": "everything"}),
        ("/v1/requests", None),
        ("/v1/actions", {"action": "confirm"}),
        ("/v1/actions", {"card_id": "c", "action": "confirm", "held_ms": "2100"}),
        ("/v1/actions", {"card_id": "c", "action": "confirm", "held_ms": True}),
    ]:
        status, reply = await http.post(path, body)
        assert status == 400 and reply["code"] == "bad_request", (path, body)
    for query in ("after=x", "after=-1", "wait=soon", "wait=nan"):
        status, reply = await http.call("GET", f"/v1/events?{query}")
        assert status == 400 and reply["code"] == "bad_request", query


# --- hello -----------------------------------------------------------------------------------


async def test_hello_greeting_arrives_after_the_returned_cursor(http: Http) -> None:
    status, body = await http.call(
        "POST", "/v1/hello", json={"device_id": DEVICE, "app": "t", "version": "0", "caps": []}
    )
    assert status == 200
    assert body["server"] == SERVER_ID and body["tz"] == "America/Lima" and "T" in body["time"]
    assert body["agent"] == "dex" and body["cursor"] == 0
    page = await http.poll(body["cursor"])
    events = page["events"]
    assert [e["type"] for e in events] == ["welcome", "state"]
    assert events[0]["server"] == SERVER_ID and events[0]["seq"] == 1
    assert events[1] == {"type": "state", "value": "idle", "agent": "dex", "seq": 2}
    assert page["cursor"] == 2


async def test_rehello_keeps_the_session_and_its_conversation(http: Http) -> None:
    _, agent, _ = fake(http.deps)
    cursor = await http.ready()
    status, _ = await http.turn(tone(1.2))
    assert status == 202
    cursor, _ = await http.until_idle(cursor)
    again = await http.hello()
    assert again == cursor  # the log carries on
    page = await http.poll(again)
    assert [e["type"] for e in page["events"]] == ["welcome", "state"]
    await http.turn(tone(1.2))
    await http.until_idle(page["cursor"])
    assert len(agent.calls) == 2
    assert len(agent.calls[1]) > len(agent.calls[0])  # the first Q/A is in the second's history


async def test_rehello_mid_turn_does_not_claim_idle(http: Http) -> None:
    http.deps.agent = FakeAgent(delay=0.5)
    cursor = await http.ready()
    await http.turn(tone(1.2))
    cursor, _ = await http.until(cursor, lambda e: e.get("value") == "working")
    cursor = await http.hello()
    page = await http.poll(cursor)
    assert page["events"][1]["type"] == "state" and page["events"][1]["value"] == "working"
    await http.until_idle(page["cursor"])


async def test_devices_have_separate_logs(http: Http) -> None:
    await http.hello("a")
    await http.hello("b")
    status, page = await http.call("GET", "/v1/events?after=0&wait=0", device="b")
    assert status == 200 and [e["seq"] for e in page["events"]] == [1, 2]


# --- turns -----------------------------------------------------------------------------------


async def test_full_turn_in_protocol_order_with_a_playable_clip(http: Http) -> None:
    stt, agent, tts = fake(http.deps)
    cursor = await http.ready()
    status, body = await http.turn(tone(1.2))
    assert status == 202 and isinstance(body["turn_id"], str) and body["turn_id"]
    _, events = await http.until_idle(cursor)
    assert kinds(events) == [
        "state:transcribing",
        "transcript",
        "state:working",
        "card",
        "state:speaking",
        "speech_start",
        "speech_clip",
        "speech_end",
        "state:idle",
    ]
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(cursor + 1, cursor + 1 + len(events)))
    assert events[1]["text"] == stt.text and events[1]["final"] is True
    card = events[3]["card"]
    assert card["kind"] == "answer" and card["body"] == agent.reply_text
    assert events[5]["card_id"] == card["id"]
    clip = events[6]
    assert clip["card_id"] == card["id"] and clip["seq_in_speech"] == 1
    assert clip["url"] == f"/v1/speech/{clip['clip_id']}.wav"
    assert clip["ms"] == round(len(tts.pcm) / 32)
    status, data = await http.call("GET", clip["url"])
    assert status == 200
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert w.readframes(w.getnframes()) == tts.pcm


async def test_long_speech_is_cut_into_ordered_clips(http: Http) -> None:
    tts = FakeTTS(pcm=tone(3.5))
    http.deps.tts = tts
    cursor = await http.ready()
    await http.turn(tone(1.2))
    _, events = await http.until_idle(cursor)
    clips = [e for e in events if e["type"] == "speech_clip"]
    assert len(clips) >= 2
    assert [c["seq_in_speech"] for c in clips] == list(range(1, len(clips) + 1))
    assert all(c["ms"] >= 1500 for c in clips[:-1])
    start = next(e for e in events if e["type"] == "speech_start")
    end = next(e for e in events if e["type"] == "speech_end")
    assert all(start["seq"] < c["seq"] < end["seq"] for c in clips)
    pcm = b""
    for c in clips:
        status, data = await http.call("GET", c["url"])
        assert status == 200
        pcm += wav_pcm(data)
    assert pcm == tts.pcm


async def test_too_short_turn_is_an_event_not_an_http_error(http: Http) -> None:
    cursor = await http.ready()
    status, _ = await http.turn(tone(0.2))
    assert status == 202
    _, events = await http.until_idle(cursor)
    assert kinds(events) == ["state:transcribing", "error", "state:idle"]
    assert events[1]["code"] == "too_short"


async def test_second_turn_while_one_runs_is_409(http: Http) -> None:
    http.deps.agent = FakeAgent(delay=0.5)
    cursor = await http.ready()
    assert (await http.turn(tone(1.2)))[0] == 202
    status, body = await http.turn(tone(1.2))
    assert status == 409 and body["code"] == "busy"
    _, events = await http.until_idle(cursor)
    assert not [e for e in events if e["type"] == "error"]  # the 409 isn't also an event


async def test_audio_over_27_seconds_is_413(http: Http) -> None:
    await http.hello()
    status, body = await http.turn(tone(27.5, amplitude=0.1))
    assert status == 413 and body["code"] == "too_long"
    status, body = await http.turn(tone(60, amplitude=0.1))  # over the body limit too
    assert status == 413 and body["code"] == "too_long"


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (wav(tone(1.0), rate=44100), "audio/wav"),
        (wav(tone(1.0) * 2, channels=2), "audio/wav"),
        (wav(b"\x00" * 16000, bits=8), "audio/wav"),
        (b"not a wav at all", "audio/wav"),
        (wav(tone(1.0)), "application/octet-stream"),
    ],
)
async def test_wrong_audio_format_is_415(http: Http, body: bytes, content_type: str) -> None:
    await http.hello()
    status, reply = await http.call(
        "POST", "/v1/turns", data=body, headers={"Content-Type": content_type}
    )
    assert status == 415 and reply["code"] == "audio_format"


def test_wav_parser_walks_chunks() -> None:
    pcm = tone(0.6)
    plain = wav_bytes(pcm)
    assert wav_pcm(plain) == pcm
    # A LIST chunk before data (as some recorders write) and a data size that overstates.
    extra = b"LIST" + struct.pack("<I", 5) + b"abcde" + b"\x00"
    with_list = plain[:36] + extra + plain[36:40] + struct.pack("<I", 0xFFFFFFFF) + pcm
    assert wav_pcm(with_list) == pcm
    with pytest.raises(WavError):
        wav_pcm(plain[:36])  # no data chunk


# --- actions, requests, cancel ---------------------------------------------------------------


async def pending(http: Http) -> int:
    cursor = await http.hello()
    status, _ = await http.post("/v1/requests", {"what": "pending"})
    assert status == 202
    cursor, events = await http.until(cursor, lambda e: e.get("value") == "attention")
    assert "order-001" in [e["card"]["id"] for e in events if e["type"] == "card"]
    return cursor


async def test_short_money_hold_is_an_error_event_and_orders_nothing(http: Http) -> None:
    cursor = await pending(http)
    status, body = await http.post(
        "/v1/actions", {"card_id": "order-001", "action": "confirm", "held_ms": 900}
    )
    assert status == 202 and body == {}
    page = await http.poll(cursor, wait=2)
    assert page["events"][0]["type"] == "error" and page["events"][0]["code"] == "too_short"
    entry = json.loads(http.deps.config.action_log.read_text().splitlines()[-1])
    assert entry["outcome"] == "rejected_short_hold" and entry["held_ms"] == 900
    assert entry["device_id"] == DEVICE


async def test_full_money_hold_matches_the_websocket_outcome(http: Http) -> None:
    cursor = await pending(http)
    await http.post("/v1/actions", {"card_id": "order-001", "action": "confirm", "held_ms": 2100})
    _, events = await http.until_idle(cursor)
    assert kinds(events) == ["card", "state:idle"]
    card = events[0]["card"]
    assert card["id"] == "order-001" and card["kind"] == "notice"
    assert card["title"] == "Sample order" and card["body"] == SAMPLE_ORDER_TEXT
    entry = json.loads(http.deps.config.action_log.read_text().splitlines()[-1])
    assert entry["outcome"] == "sample_ack" and entry["fixture"] is True
    assert entry["held_ms"] == 2100


async def test_decision_action_is_done_then_dismissed(http: Http) -> None:
    cursor = await pending(http)
    page = await http.poll(0)
    decision = next(
        e["card"] for e in page["events"] if e["type"] == "card" and e["card"]["kind"] == "decision"
    )
    await http.post("/v1/actions", {"card_id": decision["id"], "action": "approve"})
    _, events = await http.until(cursor, lambda e: e["type"] == "dismiss")
    assert kinds(events) == ["state:done", "dismiss"]


async def test_edition_and_status_requests(http: Http) -> None:
    cursor = await http.ready()
    await http.post("/v1/requests", {"what": "edition"})
    await http.post("/v1/requests", {"what": "status"})
    _, events = await http.until(cursor, lambda e: e["type"] == "state")
    cards = [e["card"] for e in events if e["type"] == "card"]
    assert cards and all(c["kind"] == "edition" for c in cards)
    assert events[-1]["value"] == "idle"


async def test_cancel_while_thinking_goes_idle(http: Http) -> None:
    http.deps.agent = FakeAgent(delay=5)
    cursor = await http.ready()
    await http.turn(tone(1.2))
    cursor, _ = await http.until(cursor, lambda e: e.get("value") == "working")
    status, body = await http.post("/v1/cancel")
    assert status == 202 and body == {}
    page = await http.poll(cursor)
    assert kinds(page["events"]) == ["state:idle"]
    assert (await http.turn(tone(1.2)))[0] == 202  # no longer busy


# --- long poll -------------------------------------------------------------------------------


async def test_poll_returns_early_when_an_event_lands(http: Http) -> None:
    cursor = await http.hello()
    cursor = (await http.poll(cursor))["cursor"]
    began = time.monotonic()
    waiting = asyncio.create_task(http.poll(cursor, wait=10))
    await asyncio.sleep(0.2)
    assert not waiting.done()
    await http.post("/v1/requests", {"what": "status"})
    page = await asyncio.wait_for(waiting, 3)
    assert time.monotonic() - began < 3
    assert kinds(page["events"]) == ["state:idle"] and page["cursor"] == cursor + 1


async def test_poll_is_empty_after_wait(http: Http) -> None:
    cursor = await http.hello()
    cursor = (await http.poll(cursor))["cursor"]
    began = time.monotonic()
    page = await http.poll(cursor, wait=0.3)
    assert time.monotonic() - began >= 0.25
    assert page == {"cursor": cursor, "events": []}


async def test_cursor_past_the_end_is_treated_as_the_end(http: Http) -> None:
    cursor = await http.hello()
    end = (await http.poll(cursor))["cursor"]
    page = await http.poll(end + 50)
    assert page == {"cursor": end, "events": []}


async def test_stale_cursor_gets_reset(http: Http) -> None:
    await http.hello()
    for _ in range(205):
        await http.post("/v1/requests", {"what": "status"})
    page = await http.poll(0)
    assert page == {"cursor": 207, "events": [], "reset": True}
    kept = await http.poll(7)  # the oldest kept event is seq 8
    assert len(kept["events"]) == 200 and kept["events"][0]["seq"] == 8


async def test_a_second_poll_completes_the_first(http: Http) -> None:
    cursor = await http.hello()
    cursor = (await http.poll(cursor))["cursor"]
    first = asyncio.create_task(http.poll(cursor, wait=10))
    await asyncio.sleep(0.2)
    second = asyncio.create_task(http.poll(cursor, wait=10))
    page = await asyncio.wait_for(first, 3)
    assert page == {"cursor": cursor, "events": []}
    assert not second.done()
    await http.post("/v1/requests", {"what": "status"})
    page = await asyncio.wait_for(second, 3)
    assert kinds(page["events"]) == ["state:idle"]


# --- clips and expiry ------------------------------------------------------------------------


async def turn_clip(http: Http, cursor: int) -> tuple[int, str]:
    await http.turn(tone(1.2))
    cursor, events = await http.until_idle(cursor)
    return cursor, next(e["url"] for e in events if e["type"] == "speech_clip")


async def test_expired_clip_is_404(http: Http) -> None:
    cursor = await http.ready()
    _, url = await turn_clip(http, cursor)
    assert (await http.call("GET", url))[0] == 200
    http.clock.now += 601
    status, body = await http.call("GET", url)
    assert status == 404 and body["code"] == "not_found"


async def test_only_the_20_most_recent_clips_are_kept(http: Http) -> None:
    cursor = await http.ready()
    urls = []
    for _ in range(21):
        cursor, url = await turn_clip(http, cursor)
        urls.append(url)
    assert (await http.call("GET", urls[0]))[0] == 404
    assert (await http.call("GET", urls[1]))[0] == 200
    assert (await http.call("GET", urls[-1]))[0] == 200


async def test_unknown_clip_is_404(http: Http) -> None:
    await http.hello()
    for path in ("/v1/speech/deadbeef.wav", "/v1/speech/not-a-wav.mp3"):
        status, body = await http.call("GET", path)
        assert status == 404 and body["code"] == "not_found"


async def test_clips_are_per_device(http: Http) -> None:
    cursor = await http.ready()
    _, url = await turn_clip(http, cursor)
    await http.hello("other")
    status, body = await http.call("GET", url, device="other")
    assert status == 404 and body["code"] == "not_found"


async def test_idle_session_expires_then_rehello_starts_fresh(http: Http) -> None:
    cursor = await http.hello()
    assert cursor == 0
    http.clock.now += http.deps.config.http_session_ttl + 1
    status, body = await http.call("GET", "/v1/events?after=0&wait=0")
    assert status == 404 and body["code"] == "no_session"
    await http.server.api.sweep()
    assert DEVICE not in http.server.api.devices
    assert await http.hello() == 0  # a new session, a new log


async def test_activity_keeps_a_session_alive(http: Http) -> None:
    await http.hello()
    ttl = http.deps.config.http_session_ttl
    for _ in range(3):
        http.clock.now += ttl * 0.6
        assert (await http.poll(0))["events"]
    await http.server.api.sweep()
    assert DEVICE in http.server.api.devices


# --- wiring ----------------------------------------------------------------------------------


def test_config_reads_the_http_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    from charm_server.config import Config

    monkeypatch.setenv("CHARM_HTTP_PORT", "0")
    monkeypatch.setenv("CHARM_HTTP_SESSION_TTL", "90")
    config = Config.from_env(env_file=None)
    assert config.http_port == 0 and config.http_session_ttl == 90.0
    monkeypatch.delenv("CHARM_HTTP_PORT")
    monkeypatch.delenv("CHARM_HTTP_SESSION_TTL")
    config = Config.from_env(env_file=None)
    assert config.http_port == 8766 and config.http_session_ttl == 3600.0


def test_max_audio_matches_the_contract() -> None:
    assert p.MAX_AUDIO_BYTES == 27 * p.BYTES_PER_SECOND
