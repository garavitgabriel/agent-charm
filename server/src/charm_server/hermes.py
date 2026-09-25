"""A persistent channel to Dex: one long-lived worker in the Hermes container, JSON lines over SSH.

`HermesAgent` (agent.py) opens `ssh … docker exec … python -` once per question. Measured on
2026-09-25, the SSH handshake, `docker exec` and interpreter start alone take 3.2-4.1 s of every
question. `HermesChannel` pays that once: at server start it launches `WORKER` through the same
path (`ssh <alias> docker exec -i <container> python -u -c …`) and keeps it open. Each question is
one JSON line in; the answer streams back as JSON lines while Hermes generates it.

The worker is an ordinary process, not a service. It reads `API_SERVER_KEY` from the container's
`/opt/data/.env` (the key never leaves the VPS), calls the container-local chat completions API
with `stream: true`, and exits when its stdin closes, which happens when the server stops or the
SSH connection drops. Nothing here changes Hermes config, crons, skills or the charter.
Provenance: the SSH → docker exec → local API path and the key handling are Margin's
(`margin/bridge.py`, see agent.py).

Wire (one JSON object per line):

    server → worker   {"type":"chat","id":N,"messages":[…],"timeout":S}
                      {"type":"cancel","id":N}     {"type":"ping"}
    worker → server   {"type":"ready"} | {"type":"fatal","error":…}   (once, at start)
                      {"id":N,"type":"delta","text":…}   … then
                      {"id":N,"type":"done"} | {"id":N,"type":"error","error":…}
                      {"type":"pong"}
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import time
from collections import deque
from collections.abc import AsyncIterator, Sequence
from typing import Any

from .agent import AgentError, AgentTimeout, Message

log = logging.getLogger(__name__)

# Runs inside the Hermes container. Standard library only (the container's Python). The two
# CHARM_WORKER_* overrides exist for the local tests; in the container they're unset.
WORKER = r"""
import json, os, sys, threading, urllib.error, urllib.request
from pathlib import Path

ENV_FILE = os.environ.get('CHARM_WORKER_ENV_FILE', '/opt/data/.env')
URL = os.environ.get('CHARM_WORKER_URL', 'http://127.0.0.1:8642/v1/chat/completions')
out_lock = threading.Lock()
cancelled = set()


def emit(obj):
    line = json.dumps(obj, ensure_ascii=False)
    with out_lock:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()


def api_key():
    settings = {}
    for line in Path(ENV_FILE).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            settings[key.strip()] = value.strip().strip(chr(34) + chr(39))
    return settings.get('API_SERVER_KEY')


def content_of(choice):
    for part in ('delta', 'message'):
        text = (choice.get(part) or {}).get('content')
        if isinstance(text, str) and text:
            return text
    return None


def chat(request, key):
    rid = request['id']
    body = json.dumps({'model': 'hermes-agent', 'messages': request['messages'], 'stream': True})
    http = urllib.request.Request(URL, data=body.encode(), method='POST', headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
        'Accept': 'text/event-stream'})
    sent = False
    try:
        with urllib.request.urlopen(http, timeout=float(request.get('timeout', 110))) as response:
            if 'text/event-stream' not in response.headers.get('Content-Type', ''):
                result = json.load(response)  # the API answered without streaming
                choices = result.get('choices') or []
                text = content_of(choices[0]) if choices else None
                if text and text.strip():
                    emit({'id': rid, 'type': 'delta', 'text': text})
                    sent = True
            else:
                for raw in response:
                    if rid in cancelled:
                        return
                    line = raw.decode('utf-8', 'replace').strip()
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        break
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get('error'):
                        raise RuntimeError('stream error')
                    for choice in event.get('choices') or []:
                        text = content_of(choice)
                        if text:
                            emit({'id': rid, 'type': 'delta', 'text': text})
                            sent = True
        if rid in cancelled:
            return
        if sent:
            emit({'id': rid, 'type': 'done'})
        else:
            emit({'id': rid, 'type': 'error', 'error': 'Dex sent an empty answer.'})
    except urllib.error.HTTPError as exc:
        emit({'id': rid, 'type': 'error', 'error': 'Hermes returned HTTP ' + str(exc.code) + '.'})
    except Exception as exc:
        emit({'id': rid, 'type': 'error',
              'error': 'Hermes did not return a text answer (' + type(exc).__name__ + ').'})
    finally:
        cancelled.discard(rid)


def main():
    try:
        key = api_key()
    except Exception as exc:
        key = None
    if not key:
        emit({'type': 'fatal', 'error': 'Hermes API authentication is not configured.'})
        return
    emit({'type': 'ready'})
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
        except ValueError:
            continue
        kind = request.get('type')
        if kind == 'ping':
            emit({'type': 'pong'})
        elif kind == 'cancel':
            cancelled.add(request.get('id'))
        elif kind == 'chat':
            threading.Thread(target=chat, args=(request, key), daemon=True).start()


main()
os._exit(0)  # stdin closed: the channel is gone, so is the worker (daemon threads included)
"""


def worker_bootstrap() -> str:
    """A `python -c` argument that runs WORKER; base64 keeps the remote shell out of the quoting."""
    encoded = base64.b64encode(WORKER.encode()).decode()
    return f"import base64;exec(base64.b64decode('{encoded}'))"


def ssh_command(ssh_alias: str, container: str) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        # Notice a dead link within ~45 s even while idle; the worker then exits with stdin.
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        ssh_alias,
        f'docker exec -i {container} /opt/hermes/.venv/bin/python -u -c "{worker_bootstrap()}"',
    ]


_DROPPED: dict[str, Any] = {"type": "dropped"}


class HermesChannel:
    """Dex over one long-lived worker. Implements `Agent` and `StreamingAgent`.

    - `start()` warms the channel (called at server start); every request also connects on
      demand, so a cold or dropped channel costs one reconnect, never a failed question.
    - After an unexpected drop it reconnects in the background with backoff, so the next
      question finds it warm again.
    - A request that drops before any text arrives is retried once on a fresh channel (Dex is
      read-and-converse only, so asking twice is harmless). A drop mid-answer is an error.
    - Each request has its own deadline (`timeout`, 120 s); cancelling the consumer tells the
      worker to stop, and any late lines for that request are dropped.

    `command` overrides the SSH command (tests run the worker locally; nothing touches Hermes).
    """

    def __init__(
        self,
        ssh_alias: str = "hermes",
        container: str = "hermes-agent",
        timeout: float = 120.0,
        command: Sequence[str] | None = None,
        env: dict[str, str] | None = None,
        ready_timeout: float = 30.0,
        backoff: Sequence[float] = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0),
    ) -> None:
        self.timeout = timeout
        self.command = list(command or ssh_command(ssh_alias, container))
        self.env = env
        self.ready_timeout = ready_timeout
        self.backoff = tuple(backoff)
        self.connects = 0  # how many workers were started (tests, logs)
        self._proc: asyncio.subprocess.Process | None = None
        self._ready: asyncio.Future[None] | None = None
        self._pending: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self._next_id = 0
        self._connect_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._reconnect: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=5)
        self._closing = False

    # --- lifecycle -----------------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return (
            self._proc is not None
            and self._proc.returncode is None
            and self._ready is not None
            and self._ready.done()
            and not self._ready.cancelled()
            and self._ready.exception() is None
        )

    async def start(self) -> bool:
        """Warm up: connect now. Returns whether it worked (failure is logged, not raised)."""
        started = time.monotonic()
        try:
            await self._ensure()
        except AgentError as exc:
            log.warning("hermes channel warm-up failed: %s (will retry on demand)", exc)
            return False
        log.info("hermes channel ready in %.2fs", time.monotonic() - started)
        return True

    async def close(self) -> None:
        self._closing = True
        if self._reconnect is not None:
            self._reconnect.cancel()
        await self._kill()
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(BaseException):
                await task

    async def _ensure(self) -> None:
        async with self._connect_lock:
            if self.connected:
                return
            await self._kill()
            await self._spawn()
            assert self._ready is not None
            try:
                await asyncio.wait_for(asyncio.shield(self._ready), self.ready_timeout)
            except TimeoutError as exc:
                await self._kill()
                raise AgentError("Can't reach Dex right now (the channel didn't open).") from exc

    async def _spawn(self) -> None:
        env = {**os.environ, **self.env} if self.env else None
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                limit=1 << 20,
            )
        except OSError as exc:
            raise AgentError(f"Can't reach Dex right now ({exc.strerror or exc}).") from exc
        self.connects += 1
        self._proc = proc
        self._ready = asyncio.get_running_loop().create_future()
        self._spawn_task(self._read_stdout(proc, self._ready), "hermes-stdout")
        self._spawn_task(self._read_stderr(proc), "hermes-stderr")
        log.info("hermes channel: worker started (connect #%d)", self.connects)

    def _spawn_task(self, coro: Any, name: str) -> None:
        task: asyncio.Task[None] = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        if proc.stdin is not None:
            proc.stdin.close()  # the worker exits on EOF
        try:
            await asyncio.wait_for(proc.wait(), 2.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()

    async def _read_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr is not None
        while line := await proc.stderr.readline():
            text = line.decode(errors="replace").rstrip()
            self._stderr_tail.append(text)
            log.debug("hermes worker stderr: %s", text)

    async def _read_stdout(
        self, proc: asyncio.subprocess.Process, ready: asyncio.Future[None]
    ) -> None:
        assert proc.stdout is not None
        try:
            while line := await proc.stdout.readline():
                try:
                    message = json.loads(line)
                except ValueError:
                    log.debug("hermes worker noise: %r", line[:200])
                    continue
                if not isinstance(message, dict):
                    continue
                kind = message.get("type")
                if kind == "ready":
                    if not ready.done():
                        ready.set_result(None)
                elif kind == "fatal":
                    if not ready.done():
                        ready.set_exception(AgentError(str(message.get("error", "Dex failed."))))
                elif kind == "pong":
                    pass
                else:
                    queue = self._pending.get(message.get("id", -1))
                    if queue is not None:  # else: a late line for a cancelled request
                        queue.put_nowait(message)
        finally:
            await proc.wait()
            dropped = self._proc is proc or self._proc is None
            if not ready.done():
                tail = " | ".join(self._stderr_tail)
                log.warning("hermes channel failed to open (exit %s): %s", proc.returncode, tail)
                ready.set_exception(AgentError("Can't reach Dex right now (the channel closed)."))
            if dropped:
                for queue in self._pending.values():
                    queue.put_nowait(_DROPPED)
                if not self._closing and ready.exception() is None:
                    log.warning("hermes channel dropped (exit %s); reconnecting", proc.returncode)
                    self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._reconnect is None or self._reconnect.done():
            self._reconnect = asyncio.create_task(self._reconnect_loop(), name="hermes-reconnect")

    async def _reconnect_loop(self) -> None:
        for delay in (*self.backoff, *([self.backoff[-1]] * 1000)):
            await asyncio.sleep(delay)
            if self._closing or self.connected:
                return
            try:
                await self._ensure()
                log.info("hermes channel reconnected")
                return
            except AgentError as exc:
                log.warning("hermes channel reconnect failed: %s", exc)

    # --- requests ------------------------------------------------------------------------------

    def _write(self, message: dict[str, Any]) -> bool:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.returncode is not None:
            return False
        try:
            proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        except (BrokenPipeError, ConnectionResetError, RuntimeError):
            return False
        return True

    async def reply(self, messages: list[Message]) -> str:
        text = "".join([piece async for piece in self.stream(messages)]).strip()
        if not text:
            raise AgentError("Dex sent an empty answer.")
        return text

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        deadline = time.monotonic() + self.timeout
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            try:
                await asyncio.wait_for(self._ensure(), max(0.01, remaining))
            except TimeoutError as exc:
                raise AgentTimeout("Dex didn't answer within 120 seconds.") from exc
            self._next_id += 1
            rid = self._next_id
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._pending[rid] = queue
            finished = False
            got_text = False
            try:
                request = {
                    "type": "chat",
                    "id": rid,
                    "messages": messages,
                    "timeout": max(5.0, self.timeout - 10),
                }
                if not self._write(request):
                    message: dict[str, Any] = _DROPPED
                else:
                    message = {}
                while message is not _DROPPED:
                    remaining = deadline - time.monotonic()
                    try:
                        message = await asyncio.wait_for(queue.get(), max(0.0, remaining))
                    except TimeoutError as exc:
                        raise AgentTimeout("Dex didn't answer within 120 seconds.") from exc
                    kind = message.get("type")
                    if kind == "delta":
                        text = message.get("text")
                        if isinstance(text, str) and text:
                            got_text = True
                            yield text
                    elif kind == "done":
                        finished = True
                        return
                    elif kind == "error":
                        finished = True
                        raise AgentError(str(message.get("error") or "Dex could not answer."))
                finished = True  # dropped: nothing left to cancel on this worker
                if got_text or attempt:
                    raise AgentError("The connection to Dex dropped mid-answer.")
                log.warning("hermes channel dropped before the answer; retrying once")
            finally:
                self._pending.pop(rid, None)
                if not finished:
                    self._write({"type": "cancel", "id": rid})
        raise AgentError("The connection to Dex failed.")  # pragma: no cover (loop returns)
