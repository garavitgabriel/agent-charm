"""HermesAgent against a local stand-in for `ssh hermes docker exec …`. No network."""

from __future__ import annotations

import base64
import json
import re
import sys

import pytest

from charm_server.agent import (
    PERSONA,
    AgentError,
    AgentTimeout,
    HermesAgent,
    build_remote_script,
    parse_reply,
    system_messages,
)

# Reads the REMOTE script from stdin like the container's python would, pulls out the payload,
# and echoes the last user message back as Hermes' "answer".
ECHO = r"""
import base64, json, re, sys
script = sys.stdin.read()
payload = json.loads(base64.b64decode(re.search(r"b64decode\('([^']+)'\)", script).group(1)))
assert payload["model"] == "hermes-agent" and payload["stream"] is False
print(json.dumps({"text": "echo: " + payload["messages"][-1]["content"]}))
"""


def stand_in(code: str) -> list[str]:
    return [sys.executable, "-c", code]


async def test_reply_round_trips_through_the_remote_script() -> None:
    agent = HermesAgent(command=stand_in(ECHO))
    messages = [*system_messages("en"), {"role": "user", "content": "¿hola?"}]
    assert await agent.reply(messages) == "echo: ¿hola?"


async def test_remote_error_becomes_agent_error() -> None:
    code = (
        "import json,sys; sys.stdin.read(); "
        "print(json.dumps({'error':'Hermes returned HTTP 502.'})); sys.exit(1)"
    )
    with pytest.raises(AgentError, match="HTTP 502"):
        await HermesAgent(command=stand_in(code)).reply([{"role": "user", "content": "x"}])


async def test_ssh_failure_becomes_agent_error() -> None:
    code = "import sys; sys.stdin.read(); sys.stderr.write('ssh: connect refused'); sys.exit(255)"
    with pytest.raises(AgentError, match="connection to Dex failed"):
        await HermesAgent(command=stand_in(code)).reply([{"role": "user", "content": "x"}])


async def test_slow_hermes_times_out_and_the_process_is_killed() -> None:
    code = "import sys,time; sys.stdin.read(); time.sleep(30)"
    agent = HermesAgent(command=stand_in(code), timeout=0.5)
    with pytest.raises(AgentTimeout):
        await agent.reply([{"role": "user", "content": "x"}])


def test_remote_script_carries_the_payload_and_reads_the_key_in_the_container() -> None:
    messages = [{"role": "user", "content": "hi"}]
    script = build_remote_script(messages, http_timeout=110)
    encoded = re.search(r"b64decode\('([^']+)'\)", script)
    assert encoded is not None
    assert json.loads(base64.b64decode(encoded.group(1)))["messages"] == messages
    assert "/opt/data/.env" in script and "127.0.0.1:8642/v1/chat/completions" in script
    assert "timeout=110" in script


def test_default_command_is_the_margin_pattern() -> None:
    agent = HermesAgent("hermes", "hermes-agent")
    assert agent.command[0] == "ssh" and "BatchMode=yes" in agent.command
    assert agent.command[-2] == "hermes"
    assert agent.command[-1].startswith("docker exec -i hermes-agent ")


@pytest.mark.parametrize(
    ("stdout", "code", "message"),
    [
        ("", 255, "connection to Dex failed"),
        ("[1]", 0, "couldn't read"),
        ('{"text": "  "}', 0, "empty answer"),
        ('{"error": "nope"}', 1, "nope"),
    ],
)
def test_parse_reply_failures(stdout: str, code: int, message: str) -> None:
    with pytest.raises(AgentError, match=message):
        parse_reply(stdout, code)


def test_parse_reply_uses_the_last_line() -> None:
    assert parse_reply('warning: noise\n{"text": "Hi."}\n', 0) == "Hi."


def test_persona_is_conversation_only_and_language_matched() -> None:
    # Read, don't act (2026-09-28): lookups allowed, every action class forbidden.
    assert "LOOK THINGS UP" in PERSONA and "must NOT take any action" in PERSONA
    for forbidden in ("orders", "messages", "files", "cron", "memories"):
        assert forbidden in PERSONA, forbidden
    assert "same language" in PERSONA
    assert system_messages("es")[1]["content"] == "The question was spoken in Spanish."
    assert len(system_messages("fr")) == 1
