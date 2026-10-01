"""The charm WebSocket server: `ws://<host>:<port>/charm` (docs/PROTOCOL.md)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hmac
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from zoneinfo import ZoneInfo

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from . import SERVER_ID
from . import protocol as p
from .agent import Agent, HermesAgent
from .books import BookStore
from .cards import CardValidator
from .coach import COACH_TIMEOUT_SECONDS, CoachDesk, ContainerLedger, Ledger
from .config import AGENT_BACKENDS, Config
from .hermes import HermesChannel
from .notestore import make_store
from .openai_compat import OpenAICompatAgent
from .session import Deps, Session
from .stt import WhisperSTT
from .tts import TTS, EdgeTTS, ElevenLabsTTS, FallbackTTS

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
        await session.greet()  # an active reading session outlives the connection
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


@dataclass
class Agents:
    """The agents one server talks to, built from the config (`CHARM_AGENT`)."""

    dex: Agent
    coach: Agent | None = None
    ledger: Ledger | None = None
    describe: str = ""
    warmups: list[Callable[[], Awaitable[object]]] = field(default_factory=list)
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)


def make_agents(config: Config) -> Agents:
    """`openai`: any OpenAI-compatible endpoint. `hermes`: a Hermes container over SSH."""
    backend = config.agent_backend
    if backend == "openai":
        if not config.agent_model:
            raise SystemExit(
                "CHARM_AGENT_MODEL is not set. Name the model your endpoint serves "
                "(see server/.env.example), or set CHARM_AGENT=hermes."
            )
        dex = OpenAICompatAgent(
            config.agent_model, config.agent_base_url, config.agent_api_key, name="Dex"
        )
        agents = Agents(dex=dex, describe=f"openai-compatible {config.agent_model}")
        agents.closers.append(dex.close)
        if config.coach_enabled:
            coach = OpenAICompatAgent(
                config.coach_model or config.agent_model,
                config.agent_base_url,
                config.agent_api_key,
                timeout=COACH_TIMEOUT_SECONDS,
                name="Coach",
            )
            agents.coach = coach
            agents.closers.append(coach.close)
        return agents
    if backend != "hermes":
        raise SystemExit(
            f"Unknown CHARM_AGENT {backend!r}: use one of {', '.join(AGENT_BACKENDS)}."
        )
    if config.hermes_channel:
        channel = HermesChannel(config.hermes_ssh_alias, config.hermes_container)
        agents = Agents(dex=channel, describe="hermes persistent channel")
        agents.warmups.append(channel.start)  # opens the SSH channel while Whisper loads
        agents.closers.append(channel.close)
    else:
        agents = Agents(
            dex=HermesAgent(config.hermes_ssh_alias, config.hermes_container),
            describe="hermes ssh per question",
        )
    # Coach Beard as a second Hermes profile: his own channel (same transport; his key read inside
    # the container from his profile's .env, his port), his read-only ledger for the fast path.
    if config.coach_enabled:
        coach_channel = HermesChannel(
            config.hermes_ssh_alias,
            config.hermes_container,
            timeout=COACH_TIMEOUT_SECONDS,
            name="Coach",
            env_file=config.coach_env_path,
            port=config.coach_port,
        )
        agents.coach = coach_channel
        agents.warmups.append(coach_channel.start)
        agents.closers.insert(0, coach_channel.close)
        if config.coach_ledger_path:
            agents.ledger = ContainerLedger(
                config.hermes_ssh_alias, config.hermes_container, config.coach_ledger_path
            )
    return agents


def make_tts(config: Config, edge_en: str, edge_es: str, voice_en: str, voice_es: str) -> TTS:
    """One character's voice: ElevenLabs in front of Edge when there's a key and a voice id for
    this character, else Edge alone."""
    edge = EdgeTTS(edge_en, edge_es)
    if not (config.elevenlabs_api_key and voice_en):
        return edge
    eleven = ElevenLabsTTS(config.elevenlabs_api_key, voice_en, voice_es, config.elevenlabs_model)
    return FallbackTTS(eleven, edge)


async def run(config: Config, warm: bool) -> None:
    stt = WhisperSTT(config.whisper_model)
    agents = make_agents(config)
    validator = CardValidator(config.schema_path)
    coach = CoachDesk(
        agents.coach,
        config.tz,
        path=config.coach_jobs_path,
        ledger=agents.ledger,
        validate=validator.check,
        persona=config.persona,
    )
    deps = Deps(
        config=config,
        stt=stt,
        agent=agents.dex,
        tts=make_tts(
            config,
            config.voice_en,
            config.voice_es,
            config.elevenlabs_voice_en,
            config.elevenlabs_voice_es,
        ),
        validator=validator,
        books=BookStore(config.books_path),
        notes=make_store(config.notes_backend, config.notes_dir),
        coach=coach,
        coach_tts=make_tts(
            config,
            config.coach_voice_en,
            config.coach_voice_es,
            config.elevenlabs_voice_coach_en,
            config.elevenlabs_voice_coach_es,
        ),
    )
    try:
        warmups: list[Awaitable[object]] = [start() for start in agents.warmups]
        if warm:
            warmups.append(asyncio.to_thread(stt.load))
        await asyncio.gather(*warmups)
        async with await start(deps, config.host, config.port) as server:
            log.info(
                "%s listening on ws://%s:%d%s (cards: %s, dex: %s, notes: %s, reading: %s, "
                "coach: %s)",
                SERVER_ID,
                config.host,
                config.port,
                p.PATH,
                config.cards_dir,
                agents.describe,
                config.notes_backend,
                deps.books.mode,
                "on" if agents.coach is not None else "off",
            )
            await server.serve_forever()
    finally:
        await coach.close()
        for close in agents.closers:
            await close()


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
