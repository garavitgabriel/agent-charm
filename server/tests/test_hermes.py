"""HermesChannel + the in-container WORKER, run locally against a stand-in chat-completions API.

The real WORKER script runs as a local subprocess (`python -u -c <bootstrap>`); only its two
CHARM_WORKER_* overrides point it at a temporary `.env` and a localhost HTTP server that plays
Hermes. Nothing touches SSH, the network or Hermes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from charm_server.agent import AgentError, AgentTimeout
from charm_server.hermes import WORKER, HermesChannel, ssh_command, worker_bootstrap

KEY = "test-api-key"


@dataclass
class FakeHermes:
    """What the stand-in API does next. `pieces` stream as SSE deltas, `gap` seconds apart."""

    pieces: list[str] = field(default_factory=lambda: ["Hello ", "there. ", "Second one."])
    gap: float = 0.0
    first_delay: float = 0.0
    mode: str = "sse"  # sse | json | http500 | sse_error
    requests: list[dict[str, Any]] = field(default_factory=list)
    auth: list[str] = field(default_factory=list)
    aborted: int = 0  # streams whose client went away before the end


def _handler(fake: FakeHermes) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fake.requests.append(body)
            fake.auth.append(self.headers.get("Authorization", ""))
            time.sleep(fake.first_delay)
            if fake.mode == "http500":
                self.send_response(500)
                self.end_headers()
                return
            if fake.mode == "json":
                data = json.dumps(
                    {"choices": [{"message": {"content": "".join(fake.pieces)}}]}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            pieces, gap = list(fake.pieces), fake.gap  # fixed per request
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                self.wfile.write(b": keepalive\n\n")
                for i, piece in enumerate(pieces):
                    if i:
                        time.sleep(gap)
                    event = {"choices": [{"index": 0, "delta": {"content": piece}}]}
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    self.wfile.flush()
                if fake.mode == "sse_error":
                    self.wfile.write(b'data: {"error": {"message": "boom"}}\n\n')
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                fake.aborted += 1

    return Handler


@pytest.fixture
def api() -> Iterator[tuple[FakeHermes, str]]:
    fake = FakeHermes()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake, f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
    finally:
        server.shutdown()
        server.server_close()


def worker_env(tmp_path: Path, url: str, key: str | None = KEY) -> dict[str, str]:
    env_file = tmp_path / "container.env"
    env_file.write_text(f'# hermes\nAPI_SERVER_KEY="{key}"\n' if key else "OTHER=1\n")
    return {"CHARM_WORKER_ENV_FILE": str(env_file), "CHARM_WORKER_URL": url}


def local_worker() -> list[str]:
    return [sys.executable, "-u", "-c", worker_bootstrap()]


@pytest.fixture
async def channel(tmp_path: Path, api: tuple[FakeHermes, str]) -> AsyncIterator[HermesChannel]:
    ch = HermesChannel(command=local_worker(), env=worker_env(tmp_path, api[1]), backoff=(0.05,))
    try:
        yield ch
    finally:
        await ch.close()


MESSAGES = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "¿hola?"}]


# --- the happy path --------------------------------------------------------------------------


async def test_warm_start_then_answers_stream_in_order(
    channel: HermesChannel, api: tuple[FakeHermes, str]
) -> None:
    fake, _ = api
    assert await channel.start() is True and channel.connected
    pieces = [piece async for piece in channel.stream(MESSAGES)]
    assert pieces == ["Hello ", "there. ", "Second one."]
    body = fake.requests[0]
    assert body == {"model": "hermes-agent", "messages": MESSAGES, "stream": True}
    assert fake.auth == [f"Bearer {KEY}"]  # the key is read on the worker's side only


async def test_one_worker_serves_every_question(
    channel: HermesChannel, api: tuple[FakeHermes, str]
) -> None:
    await channel.start()
    for _ in range(3):
        assert await channel.reply(MESSAGES) == "Hello there. Second one."
    assert channel.connects == 1 and len(api[0].requests) == 3


async def test_pieces_arrive_while_the_answer_is_still_being_written(
    channel: HermesChannel, api: tuple[FakeHermes, str]
) -> None:
    fake, _ = api
    fake.gap = 0.3
    await channel.start()
    started = time.monotonic()
    arrivals = [time.monotonic() - started async for _ in channel.stream(MESSAGES)]
    assert arrivals[0] < 0.25 and arrivals[-1] > 0.5


async def test_a_non_streaming_reply_is_one_piece(
    channel: HermesChannel, api: tuple[FakeHermes, str]
) -> None:
    api[0].mode = "json"
    assert [p async for p in channel.stream(MESSAGES)] == ["Hello there. Second one."]


async def test_connects_on_demand_without_warm_up(channel: HermesChannel) -> None:
    assert not channel.connected
    assert await channel.reply(MESSAGES) == "Hello there. Second one."
    assert channel.connects == 1


# --- errors ----------------------------------------------------------------------------------


async def test_http_error_becomes_agent_error_and_the_channel_survives(
    channel: HermesChannel, api: tuple[FakeHermes, str]
) -> None:
    fake, _ = api
    fake.mode = "http500"
    with pytest.raises(AgentError, match="HTTP 500"):
        await channel.reply(MESSAGES)
    fake.mode = "sse"
    assert await channel.reply(MESSAGES) == "Hello there. Second one."
    assert channel.connects == 1


async def test_stream_error_event_is_an_agent_error(
    channel: HermesChannel, api: tuple[FakeHermes, str]
) -> None:
    api[0].mode = "sse_error"
    with pytest.raises(AgentError, match="did not return a text answer"):
        await channel.reply(MESSAGES)


async def test_empty_answer_is_an_agent_error(
    channel: HermesChannel, api: tuple[FakeHermes, str]
) -> None:
    api[0].pieces = []
    with pytest.raises(AgentError, match="empty answer"):
        await channel.reply(MESSAGES)


async def test_missing_api_key_fails_honestly(tmp_path: Path, api: tuple[FakeHermes, str]) -> None:
    ch = HermesChannel(command=local_worker(), env=worker_env(tmp_path, api[1], key=None))
    try:
        assert await ch.start() is False
        with pytest.raises(AgentError, match="authentication is not configured"):
            await ch.reply(MESSAGES)
        assert api[0].requests == []
    finally:
        await ch.close()


async def test_unreachable_host_fails_honestly() -> None:
    code = "import sys; sys.stderr.write('ssh: connect refused\\n'); sys.exit(255)"
    ch = HermesChannel(command=[sys.executable, "-c", code], backoff=(0.05,))
    try:
        assert await ch.start() is False
        with pytest.raises(AgentError, match="Can't reach Dex"):
            await ch.reply(MESSAGES)
    finally:
        await ch.close()


async def test_a_channel_that_never_opens_times_out() -> None:
    ch = HermesChannel(
        command=[sys.executable, "-c", "import time; time.sleep(30)"], ready_timeout=0.3
    )
    try:
        with pytest.raises(AgentError, match="didn't open"):
            await ch.reply(MESSAGES)
    finally:
        await ch.close()


# --- timeout, cancel ---------------------------------------------------------------------------


async def test_per_request_timeout_and_the_late_answer_is_dropped(
    tmp_path: Path, api: tuple[FakeHermes, str]
) -> None:
    fake, url = api
    ch = HermesChannel(command=local_worker(), env=worker_env(tmp_path, url), timeout=0.5)
    try:
        await ch.start()
        fake.first_delay = 1.0
        with pytest.raises(AgentTimeout):
            await ch.reply(MESSAGES)
        fake.first_delay = 0.0
        fake.pieces = ["Fresh."]
        await asyncio.sleep(0.8)  # the timed-out answer lands now and must go nowhere
        assert [p async for p in ch.stream(MESSAGES)] == ["Fresh."]
        assert ch.connects == 1
    finally:
        await ch.close()


async def test_cancel_mid_stream_stops_the_worker_and_drops_late_pieces(
    channel: HermesChannel, api: tuple[FakeHermes, str]
) -> None:
    fake, _ = api
    fake.pieces = [f"piece {i}. " for i in range(8)]
    fake.gap = 0.15
    await channel.start()
    got: list[str] = []
    first = asyncio.Event()

    async def consume() -> None:
        async for piece in channel.stream(MESSAGES):
            got.append(piece)
            first.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert got == ["piece 0. "]
    fake.pieces, fake.gap = ["Next answer."], 0.0
    assert await channel.reply(MESSAGES) == "Next answer."
    await asyncio.sleep(1.4)  # long enough for the cancelled stream to have finished
    assert fake.aborted == 1  # the worker hung up on the cancelled request
    assert channel.connects == 1


# --- drops and reconnects ------------------------------------------------------------------------


async def test_reconnects_in_the_background_after_a_drop(
    channel: HermesChannel, api: tuple[FakeHermes, str]
) -> None:
    await channel.start()
    proc = channel._proc
    assert proc is not None
    proc.kill()  # the SSH link dies
    await asyncio.sleep(0.5)  # backoff is 0.05 s: the reconnect happens on its own
    assert channel.connects == 2 and channel.connected
    assert await channel.reply(MESSAGES) == "Hello there. Second one."


async def test_drop_mid_answer_is_an_error_and_the_next_question_works(
    channel: HermesChannel, api: tuple[FakeHermes, str]
) -> None:
    fake, _ = api
    fake.pieces = ["One. ", "Two. ", "Three."]
    fake.gap = 0.5
    await channel.start()
    got: list[str] = []
    with pytest.raises(AgentError, match="dropped mid-answer"):
        async for piece in channel.stream(MESSAGES):
            got.append(piece)
            assert channel._proc is not None
            channel._proc.kill()
    assert got == ["One. "]
    fake.gap = 0.0
    assert await channel.reply(MESSAGES) == "One. Two. Three."
    assert channel.connects >= 2


# A stand-in worker that dies on its first question (per spawn, counted in a file), so the
# channel's retry-once-before-any-text path runs against a fresh "SSH" process.
FLAKY = r"""
import json, sys
from pathlib import Path
count = Path(sys.argv[1]); n = int(count.read_text() or 0) + 1 if count.exists() else 1
count.write_text(str(n))
print(json.dumps({"type": "ready"}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if req.get("type") != "chat":
        continue
    if n == 1:
        sys.exit(255)
    print(json.dumps({"id": req["id"], "type": "delta", "text": "after retry"}), flush=True)
    print(json.dumps({"id": req["id"], "type": "done"}), flush=True)
"""


async def test_drop_before_any_text_is_retried_once_on_a_fresh_channel(tmp_path: Path) -> None:
    counter = tmp_path / "spawns"
    ch = HermesChannel(command=[sys.executable, "-c", FLAKY, str(counter)], backoff=(10.0,))
    try:
        await ch.start()
        assert await ch.reply(MESSAGES) == "after retry"
        assert counter.read_text() == "2"
    finally:
        await ch.close()


async def test_close_ends_the_worker(channel: HermesChannel) -> None:
    await channel.start()
    proc = channel._proc
    assert proc is not None
    await channel.close()
    assert proc.returncode is not None and not channel.connected


# --- the remote command --------------------------------------------------------------------------


def test_ssh_command_is_the_margin_path_with_keepalives() -> None:
    command = ssh_command("hermes", "hermes-agent")
    assert command[0] == "ssh" and "BatchMode=yes" in command
    assert "ServerAliveInterval=15" in command and command[-2] == "hermes"
    remote = command[-1]
    assert remote.startswith(
        "docker exec -i hermes-agent /opt/hermes/.venv/bin/python -u -c "
    )
    encoded = re.search(r"b64decode\('([A-Za-z0-9+/=]+)'\)", remote)
    assert encoded is not None and base64.b64decode(encoded.group(1)).decode() == WORKER
    # Only base64 inside the double quotes: nothing for the remote shell to expand.
    assert not re.search(r"[$`\\!]", remote)


def test_worker_reads_the_key_inside_the_container_and_calls_the_local_api() -> None:
    assert "'/opt/data/.env'" in WORKER and "API_SERVER_KEY" in WORKER
    assert "'http://127.0.0.1:8642/v1/chat/completions'" in WORKER
    assert "'stream': True" in WORKER
    assert "os._exit(0)" in WORKER  # it ends with its stdin: no daemon, no service


def test_local_command_skips_ssh_for_the_vps_deploy() -> None:
    command = ssh_command("local", "hermes-agent")
    assert command[:4] == ["docker", "exec", "-i", "hermes-agent"]
    assert "ssh" not in command
    assert command[-2] == "-c" and command[-1] == worker_bootstrap()
