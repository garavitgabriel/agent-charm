"""A local fake of the OS knowledge service (gabe-os-service): scripted replies, recorded requests."""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TOKEN = "tok-SECRET-5f3a9c-do-not-leak"


@dataclass
class Fake:
    """Scripted reply for the next requests, plus a record of what arrived."""

    status: int = 200
    body: bytes = b'{"ok": true, "path": "inbox/2026-09-27-charm-foxes.md"}'
    delay: float = 0.0
    headers: dict[str, str] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)


@contextmanager
def serve() -> Iterator[tuple[Fake, str]]:
    state = Fake()

    class Handler(BaseHTTPRequestHandler):
        def _reply(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            state.requests.append({"method": self.command, "path": self.path,
                                   "headers": dict(self.headers),
                                   "body": self.rfile.read(length)})
            if state.delay:
                time.sleep(state.delay)
            try:
                self.send_response(state.status)
                for k, v in state.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(state.body)))
                self.end_headers()
                self.wfile.write(state.body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the client already gave up (timeout test)

        do_GET = do_POST = _reply

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    yield state, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
