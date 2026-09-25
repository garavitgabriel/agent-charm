"""The charm WebSocket server: `ws://<host>:<port>/charm` (docs/PROTOCOL.md)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hmac
import json
import logging
from datetime import datetime
from http import HTTPStatus
from zoneinfo import ZoneInfo

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from . import SERVER_ID
from . import protocol as p
from .agent import HermesAgent
from .cards import CardValidator
from .config import Config
from .session import Deps, Session
from .stt import WhisperSTT
from .tts import EdgeTTS

log = logging.getLogger("charm_server")

HELLO_TIMEOUT_S = 10.0


def _check_path(connection: ServerConnection, request: Request) -> Response | None:
    if request.path != p.PATH:
        return connection.respond(HTTPStatus.NOT_FOUND, "Not found: use /charm\n")
    return None


async def _refuse(ws: ServerConnection, reason: str) -> None:
    log.warning("auth refused: %s", reason)
    await ws.send(p.encode(p.error("auth", "This charm isn't paired with the server.")))
    await ws.close(p.AUTH_CLOSE_CODE, "auth")


async def _authenticate(ws: ServerConnection, token: str) -> dict[str, object] | None:
    """Return the hello frame if its token matches CHARM_TOKEN, else refuse with 4401."""
    try:
        first = await asyncio.wait_for(ws.recv(), timeout=HELLO_TIMEOUT_S)
    except TimeoutError:
        await _refuse(ws, "no hello")
        return None
    try:
        hello = json.loads(first) if isinstance(first, str) else None
    except ValueError:
        hello = None
    if not isinstance(hello, dict) or hello.get("type") != "hello":
        await _refuse(ws, "first frame was not hello")
        return None
    offered = hello.get("token")
    if not token:
        await _refuse(ws, "CHARM_TOKEN is not set on the server")
        return None
    if not isinstance(offered, str) or not hmac.compare_digest(offered.encode(), token.encode()):
        await _refuse(ws, "bad token")
        return None
    return hello


async def handle(ws: ServerConnection, deps: Deps) -> None:
    hello = await _authenticate(ws, deps.config.token)
    if hello is None:
        return
    device_id = str(hello.get("device_id", "?"))
    log.info("device %s connected (fw=%s caps=%s)", device_id, hello.get("fw"), hello.get("caps"))

    async def send_raw(frame: str | bytes) -> None:
        await ws.send(frame)

    session = Session(send_raw=send_raw, deps=deps, device_id=device_id)
    try:
        await session.send(
            {
                "type": "welcome",
                "server": SERVER_ID,
                "time": datetime.now(ZoneInfo(deps.config.tz)).isoformat(timespec="seconds"),
                "tz": deps.config.tz,
            }
        )
        await session.send_state("idle")
        async for frame in ws:
            if isinstance(frame, bytes):
                await session.handle_binary(frame)
            else:
                await session.handle_text(frame)
    except ConnectionClosed:
        pass
    finally:
        await session.close()
        log.info("device %s disconnected", device_id)


async def start(deps: Deps, host: str, port: int) -> Server:
    async def handler(ws: ServerConnection) -> None:
        await handle(ws, deps)

    return await serve(
        handler,
        host,
        port,
        process_request=_check_path,
        max_size=4 * p.MAX_TEXT_FRAME,
        compression=None,  # audio doesn't compress and the ESP32 client won't negotiate it
    )


async def run(config: Config, warm: bool) -> None:
    stt = WhisperSTT(config.whisper_model)
    deps = Deps(
        config=config,
        stt=stt,
        agent=HermesAgent(config.hermes_ssh_alias, config.hermes_container),
        tts=EdgeTTS(config.voice_en, config.voice_es),
        validator=CardValidator(config.schema_path),
    )
    if warm:
        await asyncio.to_thread(stt.load)
    async with await start(deps, config.host, config.port) as server:
        log.info(
            "%s listening on ws://%s:%d%s (cards: %s)",
            SERVER_ID,
            config.host,
            config.port,
            p.PATH,
            config.cards_dir,
        )
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dex Charm server")
    parser.add_argument("--host", help="override CHARM_HOST")
    parser.add_argument("--port", type=int, help="override CHARM_PORT")
    parser.add_argument("--no-warm", action="store_true", help="load Whisper on first use")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    config = Config.from_env()
    if args.host or args.port:
        from dataclasses import replace

        config = replace(config, host=args.host or config.host, port=args.port or config.port)
    if not config.token:
        raise SystemExit("CHARM_TOKEN is not set. Put it in server/.env (see .env.example).")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(config, warm=not args.no_warm))


if __name__ == "__main__":
    main()
