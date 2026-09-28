"""The agent protocols, the charm persona, and `HermesAgent` (the Hermes backend, per question).

Provenance: the SSH -> `docker exec` -> container-local `/v1/chat/completions` pattern and the
in-container script below are adapted from Margin, the author's earlier reading-companion
prototype (same author, contributed under this repo's license). The API key is read inside the
container and never leaves the host.

Read and converse only: this module sends chat messages and reads the reply. It never changes
Hermes config, crons, skills or the charter, and the persona forbids tools and actions.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

Message = dict[str, str]

LANGUAGE_NAMES = {"en": "English", "es": "Spanish"}


@dataclass(frozen=True)
class Persona:
    """Who the agents work for, and where actions go instead. Both optional.

    `owner` (`CHARM_OWNER_NAME`): the person's first name, used in the prompts ("You are Dex,
    Sam's agent"). Empty: a neutral wording. `main_chat` (`CHARM_MAIN_CHAT`): the channel where
    actions *can* happen (e.g. "Telegram"). Empty: "your main chat".
    """

    owner: str = ""
    main_chat: str = ""

    @property
    def who(self) -> str:
        """The owner's name, or a neutral stand-in (sentence-internal)."""
        return self.owner.strip() or "the person you work for"

    @property
    def possessive(self) -> str:
        """ "Sam's agent" / "a personal agent"."""
        owner = self.owner.strip()
        return f"{owner}'s agent" if owner else "a personal agent"

    @property
    def chat(self) -> str:
        return self.main_chat.strip() or "your main chat"


DEFAULT_PERSONA = Persona()


def read_only_rule(persona: Persona = DEFAULT_PERSONA) -> str:
    """The charm's authority: "read, don't act". Lookups yes, actions no, from a microphone that
    can mishear. Behavioral: the agent's toolset may be broader, so the prompt says it too."""
    chat = persona.chat
    return (
        f"You may use your tools to LOOK THINGS UP, as you would in {chat}: web search and "
        "reading pages, reading your notes and files, your memory and past sessions, today's "
        "feeds and read-only skills. You must NOT take any action from this channel: no orders "
        "or checkouts, no messages or emails to anyone, no writing, patching or deleting files, "
        "no commands or code that change anything, no cron jobs, no delegated tasks, no "
        "saving or editing memories, no image generation. The microphone can mishear, so when a "
        "request needs an action, say in one sentence what you would do and that it needs "
        f"{chat} for now. Keep lookups quick, a couple of tool calls at most; if it needs deep "
        f"research, say so in one sentence and suggest asking in {chat}."
    )


def persona_prompt(persona: Persona = DEFAULT_PERSONA) -> str:
    return (
        f"You are Dex, {persona.possessive}, speaking through the Dex Charm: a small pocket "
        "device with a tiny screen and a speaker. " + read_only_rule(persona) + " Answer in "
        "plain text with no markdown, lists or emoji. Lead with the answer. Keep it to 2 or 3 "
        "short sentences, at most 60 words; the first two sentences are spoken aloud, so they "
        "must stand alone. Always reply in the same language as the question. Do not praise the "
        "question and do not invent facts."
    )


READ_ONLY_RULE = read_only_rule()
PERSONA = persona_prompt()

# Runs inside the Hermes container (adapted from Margin, the author's earlier prototype).
REMOTE = r"""
import base64,json,urllib.request,urllib.error
from pathlib import Path
settings={}
for line in Path('/opt/data/.env').read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key,value=line.split('=',1)
        settings[key.strip()]=value.strip().strip(chr(34)+chr(39))
key=settings.get('API_SERVER_KEY')
if not key:
    print(json.dumps({'error':'Hermes API authentication is not configured.'}))
    raise SystemExit(1)
payload=base64.b64decode('__PAYLOAD__')
request=urllib.request.Request('http://127.0.0.1:8642/v1/chat/completions',
    data=payload,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
try:
    with urllib.request.urlopen(request,timeout=__HTTP_TIMEOUT__) as response:
        result=json.load(response)
    choices=result.get('choices',[])
    text=choices[0].get('message',{}).get('content') if choices else None
    if not isinstance(text,str) or not text.strip():
        raise ValueError('No text answer')
    print(json.dumps({'text':text.strip()},ensure_ascii=False))
except urllib.error.HTTPError as exc:
    print(json.dumps({'error':'Hermes returned HTTP '+str(exc.code)+'.'}))
    raise SystemExit(1)
except Exception as exc:
    print(json.dumps({'error':'Hermes did not return a text answer ('+type(exc).__name__+').'}))
    raise SystemExit(1)
"""


class AgentTimeout(Exception):
    pass


class AgentError(Exception):
    pass


class Agent(Protocol):
    async def reply(self, messages: list[Message]) -> str: ...


@runtime_checkable
class StreamingAgent(Protocol):
    """An agent that can also hand over its answer piece by piece as it's generated."""

    async def reply(self, messages: list[Message]) -> str: ...

    def stream(self, messages: list[Message]) -> AsyncIterator[str]: ...


async def answer_stream(agent: Agent, messages: list[Message]) -> AsyncIterator[str]:
    """The answer as text pieces: streamed when the agent can, else the whole reply at once."""
    if isinstance(agent, StreamingAgent):
        async for piece in agent.stream(messages):
            yield piece
        return
    yield await agent.reply(messages)


def system_messages(language: str, persona: Persona = DEFAULT_PERSONA) -> list[Message]:
    name = LANGUAGE_NAMES.get(language)
    messages = [{"role": "system", "content": persona_prompt(persona)}]
    if name:
        messages.append({"role": "system", "content": f"The question was spoken in {name}."})
    return messages


def build_remote_script(messages: list[Message], http_timeout: float) -> str:
    payload = json.dumps({"model": "hermes-agent", "messages": messages, "stream": False})
    encoded = base64.b64encode(payload.encode()).decode()
    return REMOTE.replace("__PAYLOAD__", encoded).replace("__HTTP_TIMEOUT__", str(http_timeout))


def parse_reply(stdout: str, returncode: int) -> str:
    try:
        reply = json.loads(stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise AgentError("The connection to Dex failed.") from exc
    if not isinstance(reply, dict):
        raise AgentError("Dex sent something I couldn't read.")
    if returncode or "error" in reply:
        raise AgentError(str(reply.get("error", "Dex could not answer.")))
    text = reply.get("text")
    if not isinstance(text, str) or not text.strip():
        raise AgentError("Dex sent an empty answer.")
    return text.strip()


class HermesAgent:
    """`ssh <alias> docker exec -i <container> python -` with the REMOTE script on stdin.

    `command` can be overridden (tests point it at a local stand-in; nothing touches Hermes).
    Cancelling the awaiting task kills the SSH process, so a cancelled question leaves nothing
    running locally.
    """

    def __init__(
        self,
        ssh_alias: str = "hermes",
        container: str = "hermes-agent",
        timeout: float = 120.0,
        command: list[str] | None = None,
    ) -> None:
        self.timeout = timeout
        local = ["docker", "exec", "-i", container, "/opt/hermes/.venv/bin/python", "-"]
        self.command = command or (
            local
            if ssh_alias == "local"  # on the Hermes host itself: same path, no SSH hop
            else [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                ssh_alias,
                f"docker exec -i {container} /opt/hermes/.venv/bin/python -",
            ]
        )

    async def reply(self, messages: list[Message]) -> str:
        script = build_remote_script(messages, http_timeout=max(5.0, self.timeout - 10))
        proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(script.encode()), timeout=self.timeout
            )
        except TimeoutError as exc:
            raise AgentTimeout("Dex didn't answer within 120 seconds.") from exc
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        if proc.returncode and stderr:
            log.warning("hermes ssh exited %s: %s", proc.returncode, stderr.decode()[-300:])
        return parse_reply(stdout.decode(errors="replace"), proc.returncode or 0)
