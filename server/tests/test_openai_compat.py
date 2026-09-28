"""The generic OpenAI-compatible backend, against an in-process fake endpoint (no network)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from charm_notes import Book, Note

from charm_server.agent import AgentError, AgentTimeout, Persona, persona_prompt, system_messages
from charm_server.coach import coach_persona
from charm_server.config import Config
from charm_server.hermes import HermesChannel
from charm_server.notestore import FileNoteStore, make_store
from charm_server.openai_compat import OpenAICompatAgent, ThinkFilter
from charm_server.reading import reading_messages
from charm_server.server import make_agents

MESSAGES = [{"role": "user", "content": "hi"}]


def sse(*pieces: str) -> bytes:
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}) for piece in pieces
    ]
    return ("\n\n".join([*lines, "data: [DONE]"]) + "\n\n").encode()


def agent_with(handler: httpx.MockTransport, **kwargs: object) -> OpenAICompatAgent:
    return OpenAICompatAgent(
        "test-model",
        "http://llm.test/v1/",
        api_key="secret-key",
        transport=handler,
        **kwargs,  # type: ignore[arg-type]
    )


async def test_streams_deltas_and_sends_the_request() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse("Hello", " there.", " Bye."),
        )

    agent = agent_with(httpx.MockTransport(handle))
    pieces = [piece async for piece in agent.stream(MESSAGES)]
    await agent.close()
    assert "".join(pieces) == "Hello there. Bye."
    assert len(pieces) == 3  # streamed, not buffered
    request = seen[0]
    assert str(request.url) == "http://llm.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret-key"
    body = json.loads(request.content)
    assert body == {"model": "test-model", "messages": MESSAGES, "stream": True}


async def test_no_key_sends_no_auth_header() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    agent = OpenAICompatAgent("m", "http://local.test/v1", transport=httpx.MockTransport(handle))
    assert await agent.reply(MESSAGES) == "ok"
    await agent.close()
    assert "authorization" not in seen[0].headers


async def test_non_streaming_json_answer() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": "  Whole answer.  "}}]}
        )
    )
    agent = agent_with(transport)
    assert await agent.reply(MESSAGES) == "Whole answer."
    await agent.close()


async def test_think_blocks_are_never_yielded() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse("<thi", "nk>secret plan</th", "ink>\n\nThe", " answer."),
        )
    )
    agent = agent_with(transport)
    text = "".join([piece async for piece in agent.stream(MESSAGES)])
    await agent.close()
    assert text == "The answer."


def test_think_filter_keeps_plain_text_and_partial_lookalikes() -> None:
    f = ThinkFilter()
    assert f.feed("a <b> c <") + f.feed("x") + f.finish() == "a <b> c <x"


@pytest.mark.parametrize("status", [401, 404, 500])
async def test_http_errors_are_agent_errors(status: int) -> None:
    agent = agent_with(httpx.MockTransport(lambda request: httpx.Response(status, text="nope")))
    with pytest.raises(AgentError, match=f"HTTP {status}"):
        await agent.reply(MESSAGES)
    await agent.close()


async def test_empty_answer_is_an_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse()
        )
    )
    agent = agent_with(transport)
    with pytest.raises(AgentError, match="empty"):
        await agent.reply(MESSAGES)
    await agent.close()


async def test_timeout_and_connection_errors() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    agent = agent_with(httpx.MockTransport(slow), timeout=3.0)
    with pytest.raises(AgentTimeout, match="3 seconds"):
        await agent.reply(MESSAGES)
    await agent.close()
    agent = agent_with(httpx.MockTransport(down))
    with pytest.raises(AgentError, match="Can't reach Dex"):
        await agent.reply(MESSAGES)
    await agent.close()


# --- config → agents --------------------------------------------------------------------------


def test_make_agents_openai(config: Config) -> None:
    config = replace(config, agent_backend="openai", agent_model="m", coach_enabled=True)
    agents = make_agents(config)
    assert isinstance(agents.dex, OpenAICompatAgent) and agents.dex.model == "m"
    assert isinstance(agents.coach, OpenAICompatAgent) and agents.coach.name == "Coach"
    assert agents.ledger is None and not agents.warmups


def test_make_agents_openai_needs_a_model(config: Config) -> None:
    with pytest.raises(SystemExit, match="CHARM_AGENT_MODEL"):
        make_agents(replace(config, agent_backend="openai", agent_model=""))


def test_make_agents_hermes(config: Config) -> None:
    agents = make_agents(replace(config, agent_backend="hermes", coach_enabled=True))
    assert isinstance(agents.dex, HermesChannel) and isinstance(agents.coach, HermesChannel)
    assert agents.ledger is None  # no COACH_LEDGER_PATH: no fast path, said honestly
    assert len(agents.warmups) == 2
    with_ledger = make_agents(
        replace(config, agent_backend="hermes", coach_enabled=True, coach_ledger_path="/x.jsonl")
    )
    assert with_ledger.ledger is not None


def test_make_agents_unknown_backend(config: Config) -> None:
    with pytest.raises(SystemExit, match="Unknown CHARM_AGENT"):
        make_agents(replace(config, agent_backend="nope"))


# --- personas ---------------------------------------------------------------------------------


def test_personas_are_neutral_by_default() -> None:
    for text in (persona_prompt(), coach_persona()):
        assert "the owner" not in text and "Telegram" not in text
    assert "a personal agent" in persona_prompt()
    assert "your main chat" in persona_prompt()


def test_personas_use_the_configured_owner() -> None:
    persona = Persona(owner="Sam", main_chat="Signal")
    assert system_messages("en", persona)[0]["content"].startswith("You are Dex, Sam's agent")
    assert "needs Signal for now" in persona_prompt(persona)
    assert "which Sam puts down" in coach_persona(persona, "Europe/Madrid")
    assert "Europe/Madrid time" in coach_persona(persona, "Europe/Madrid")
    reading = reading_messages(Book("Dune", None, "2"), "en", [], persona)
    assert "Sam is reading a book" in reading[0]["content"]


# --- the local file note store ----------------------------------------------------------------


async def test_file_note_store_writes_new_files(tmp_path: Path) -> None:
    store = make_store("file", tmp_path / "notes")
    assert isinstance(store, FileNoteStore)
    note = Note("Foxes know many things", datetime(2026, 1, 2, tzinfo=UTC), "en")
    first = await store.save(note)
    second = await store.save(note)
    assert first.ok and second.ok and first.where != second.where
    assert first.where is not None and Path(first.where).name.startswith("2026-01-02-charm-foxes")
    assert "Foxes know many things" in Path(first.where).read_text()  # noqa: ASYNC240


async def test_file_note_store_fails_honestly(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    receipt = await FileNoteStore(blocker / "notes").save(
        Note("x", datetime(2026, 1, 2, tzinfo=UTC), "en")
    )
    assert not receipt.ok and receipt.error
