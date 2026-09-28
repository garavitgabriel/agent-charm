"""A generic agent backend: any OpenAI-compatible `POST {base_url}/chat/completions`.

Point it at OpenAI, Anthropic's OpenAI-compatible endpoint, Ollama, LM Studio, vLLM, OpenRouter, a
Hermes API server, or anything else that speaks the chat-completions wire format:

    CHARM_AGENT=openai
    CHARM_AGENT_BASE_URL=https://api.openai.com/v1      # or http://127.0.0.1:11434/v1 (Ollama)
    CHARM_AGENT_API_KEY=sk-…                           # optional for local servers
    CHARM_AGENT_MODEL=<model name>

Answers stream (`stream: true`, server-sent events) when the endpoint supports it; an endpoint that
answers with one JSON body is handled too. `<think>…</think>` blocks that some local reasoning
models emit inline are dropped, so they're never spoken or shown.

Same contract as `HermesChannel`: `reply()` and `stream()` raise `AgentTimeout` / `AgentError`
with a human-readable message, which the session shows honestly.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .agent import AgentError, AgentTimeout, Message

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"


class ThinkFilter:
    """Drops `<think>…</think>` spans from streamed text (a tag may split across pieces)."""

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, text: str) -> str:
        self._buffer += text
        out: list[str] = []
        while self._buffer:
            tag = THINK_CLOSE if self._inside else THINK_OPEN
            index = self._buffer.find(tag)
            if index >= 0:
                if not self._inside:
                    out.append(self._buffer[:index])
                self._buffer = self._buffer[index + len(tag) :]
                self._inside = not self._inside
                continue
            # Keep a possible partial tag at the end for the next piece.
            keep = next(
                (n for n in range(len(tag) - 1, 0, -1) if self._buffer.endswith(tag[:n])), 0
            )
            cut = len(self._buffer) - keep
            ready, self._buffer = self._buffer[:cut], self._buffer[cut:]
            if not self._inside:
                out.append(ready)
            break
        return "".join(out)

    def finish(self) -> str:
        rest, self._buffer = ("" if self._inside else self._buffer), ""
        return rest


class _LeadingSpace:
    """Strips whitespace before the first visible text (what's left after a `<think>` block)."""

    def __init__(self) -> None:
        self.started = False

    def __call__(self, text: str) -> str:
        if not self.started:
            text = text.lstrip()
            self.started = bool(text)
        return text


def _content(choice: dict[str, Any]) -> str | None:
    for part in ("delta", "message"):
        text = (choice.get(part) or {}).get("content")
        if isinstance(text, str) and text:
            return text
    return None


class OpenAICompatAgent:
    """Chat completions over HTTP(S). One shared `httpx.AsyncClient`, no warm-up needed.

    `transport` is for tests (an `httpx.MockTransport`); nothing else in the tests touches the
    network.
    """

    def __init__(
        self,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        timeout: float = 120.0,
        name: str = "Dex",
        temperature: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.timeout = timeout
        self.name = name
        self.temperature = temperature
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=transport,
        )

    async def start(self) -> bool:
        return True  # nothing to warm up; the first request opens the connection

    async def close(self) -> None:
        await self._client.aclose()

    async def reply(self, messages: list[Message]) -> str:
        text = "".join([piece async for piece in self.stream(messages)]).strip()
        if not text:
            raise AgentError(f"{self.name} sent an empty answer.")
        return text

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": True}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        think = ThinkFilter()
        lead = _LeadingSpace()
        started = time.monotonic()
        try:
            async with self._client.stream(
                "POST", self.url, json=body, headers={"Accept": "text/event-stream"}
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    log.warning(
                        "%s endpoint HTTP %s: %s",
                        self.name,
                        response.status_code,
                        response.text[-300:],
                    )
                    code = response.status_code
                    raise AgentError(f"{self.name}'s endpoint returned HTTP {code}.")
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    await response.aread()
                    text = self._whole(response)
                    visible = lead(think.feed(text) + think.finish())
                    if visible:
                        yield visible
                    return
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if "error" in event:
                        raise AgentError(f"{self.name}'s endpoint reported an error.")
                    choices = event.get("choices") or []
                    piece = _content(choices[0]) if choices else None
                    if piece:
                        visible = lead(think.feed(piece))
                        if visible:
                            yield visible
                rest = lead(think.finish())
                if rest:
                    yield rest
        except httpx.TimeoutException as exc:
            raise AgentTimeout(
                f"{self.name} didn't answer within {self.timeout:g} seconds."
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentError(f"Can't reach {self.name} right now ({type(exc).__name__}).") from exc
        finally:
            log.debug("%s request took %.2fs", self.name, time.monotonic() - started)

    def _whole(self, response: httpx.Response) -> str:
        try:
            result = response.json()
        except ValueError as exc:
            raise AgentError(f"{self.name} sent something I couldn't read.") from exc
        choices = result.get("choices") if isinstance(result, dict) else None
        text = _content(choices[0]) if choices else None
        if not text or not text.strip():
            raise AgentError(f"{self.name} sent an empty answer.")
        return text
