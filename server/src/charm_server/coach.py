"""Coach Beard on the charm: his persona appendix, his cards, his ledger and his walk-away jobs.

Coach is an optional second agent: an example of giving the charm more than one character. With
`CHARM_AGENT=hermes` he's a separate Hermes profile reached over his own `HermesChannel` (his own
port and key file inside the container; his profile's config can enforce a read-only toolset).
With `CHARM_AGENT=openai` he's the same OpenAI-compatible endpoint with his own persona and,
optionally, his own model. The persona below asks for read-only either way. See
docs/PROTOCOL.md § Agents and docs/COACH.md.

- `coach_messages` / `parse_reply`: the charm format, and his reply → a **call** (a `decision` card
  from `source:"coach"`) when it carries a verdict line, else an answer card.
- `ContainerLedger`: his latest *delivered* call, read-only (`docker exec … tail`), for the fast
  path. Nothing is ever written there.
- `CoachDesk`: walk-away jobs. They outlive the connection that asked; results wait (persisted in
  `server/.local/coach-jobs.json`) until a device is there to take them. Nothing is invented: a
  failed or timed-out job becomes a notice saying so.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import shlex
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .agent import (
    DEFAULT_PERSONA,
    LANGUAGE_NAMES,
    Agent,
    AgentError,
    AgentTimeout,
    Message,
    Persona,
)
from .cards import (
    ANSWER_MAX_WORDS,
    BODY_MAX_CHARS,
    Card,
    _clip_chars,
    now_iso,
    plain_text,
    say_text,
    title_from_question,
)

log = logging.getLogger(__name__)

COACH_TIMEOUT_SECONDS = 300.0
HISTORY_TURNS = 6
RESULTS_KEPT = 12

ON_IT = {"en": "Coach is on it", "es": "Coach está en eso"}
FOOTER_TRUNCATED = {
    "en": "Shortened. Ask Coach for the rest.",
    "es": "Resumida. Pídele a Coach el resto.",
}
ACTION_LABELS = {
    "en": {"hear": "Hear it", "why": "Why?", "later": "Later"},
    "es": {"hear": "Escuchar", "why": "¿Por qué?", "later": "Luego"},
}


def coach_persona(persona: Persona = DEFAULT_PERSONA, tz: str = "") -> str:
    """Coach's charm persona. `tz` names the zone his deadlines are given in."""
    who = persona.owner.strip() or "your manager"
    zone = f"{tz} time" if tz else "local time"
    return (
        "You are Coach Beard, a fantasy-football coach, answering through the Dex Charm: a small "
        f"pocket device with a tiny screen and a speaker, which {who} puts down while you work "
        "and picks up later. Your tools on this channel are read-only: research and your "
        "fantasy and NFL data. You never set a lineup, file a claim, make a trade or message "
        f"anyone from here; if something needs doing, say what {who} should do. Answer in plain "
        "text with no markdown, lists, labels or emoji. Lead with the call. At most 60 words; "
        "the first two sentences are spoken aloud, so they must stand alone. Reply in the "
        "language of the question. Never invent a stat, an injury designation or a time. "
        "When your answer is a decision (start/sit, add/drop, a trade, hold), end with ONE extra "
        "line for the device, exactly: "
        f"CALL: <the verdict in at most 6 words> | BY: <the lock or deadline in {zone}, like "
        "Sun 12:00> | FLIP: <the one fact that flips it, at most 12 words>. "
        "Leave that line out when there is no decision."
    )


COACH_PERSONA = coach_persona()


def coach_messages(
    language: str,
    history: Sequence[Message],
    persona: Persona = DEFAULT_PERSONA,
    tz: str = "",
) -> list[Message]:
    messages: list[Message] = [{"role": "system", "content": coach_persona(persona, tz)}]
    name = LANGUAGE_NAMES.get(language)
    if name:
        messages.append({"role": "system", "content": f"The question was spoken in {name}."})
    return [*messages, *history]


def why_question(card: Card, language: str) -> str:
    verdict = card.get("data", {}).get("default") or card.get("title", "")
    body = card.get("body", "")
    if language == "es":
        return f"¿Por qué? Explícame el razonamiento de tu jugada: {verdict}. {body}"
    return f"Why? Give me the reasoning behind your call: {verdict}. {body}"


# --- his reply → a call or an answer ------------------------------------------------------------

_CALL_LINE = re.compile(r"^\s*\**\s*CALL\s*:\s*(?P<rest>.+)$", re.IGNORECASE | re.MULTILINE)
_FIELD = re.compile(r"\|\s*(?P<key>BY|FLIP)\s*:\s*", re.IGNORECASE)


@dataclass(frozen=True)
class Verdict:
    default: str
    deadline: str | None
    flip_if: str | None


def split_call(reply: str) -> tuple[str, Verdict | None]:
    """The reply without its `CALL: … | BY: … | FLIP: …` line, and that line parsed (if any)."""
    match = _CALL_LINE.search(reply)
    if match is None:
        return reply.strip(), None
    body = (reply[: match.start()] + reply[match.end() :]).strip()
    rest = match.group("rest").strip().rstrip("*").strip()
    parts = _FIELD.split(rest)
    fields = {"CALL": parts[0]}
    for i in range(1, len(parts) - 1, 2):
        fields[parts[i].upper()] = parts[i + 1]

    def clean(value: str | None) -> str | None:
        text = plain_text(value or "").strip(" |.")
        return text or None

    default = clean(fields.get("CALL"))
    if default is None:
        return body, None
    return body, Verdict(default, clean(fields.get("BY")), clean(fields.get("FLIP")))


def _actions(language: str, why: bool) -> list[dict[str, str]]:
    labels = ACTION_LABELS.get(language, ACTION_LABELS["en"])
    ids = ("hear", "why", "later") if why else ("hear", "later")
    styles = {"hear": "primary"}
    return [{"id": i, "label": labels[i], "style": styles.get(i, "secondary")} for i in ids]


def _body(text: str, language: str) -> tuple[str, str | None]:
    words = plain_text(text).split()
    body = " ".join(words[:ANSWER_MAX_WORDS])
    truncated = len(words) > ANSWER_MAX_WORDS or len(body) > BODY_MAX_CHARS
    if truncated:
        body = _clip_chars(body, BODY_MAX_CHARS, force=True)
    footer = FOOTER_TRUNCATED.get(language, FOOTER_TRUNCATED["en"]) if truncated else None
    return body, footer


def call_card(
    card_id: str,
    title: str,
    body: str,
    verdict: Verdict,
    language: str,
    tz: str,
    created_at: str | None = None,
    footer: str | None = None,
) -> Card:
    no_deadline = "Sin hora" if language == "es" else "Not stated"
    data: dict[str, Any] = {
        "default": _clip_chars(verdict.default, 40),
        "deadline": _clip_chars(verdict.deadline or no_deadline, 40),
    }
    if verdict.flip_if:
        data["flip_if"] = _clip_chars(verdict.flip_if, 80)
    card: Card = {
        "id": card_id[:64],
        "kind": "decision",
        "title": _clip_chars(title, 60),
        "body": body or verdict.default,
        "source": "coach",
        "created_at": created_at or now_iso(tz),
        "data": data,
        "actions": _actions(language, why=True),
    }
    if footer:
        card["footer"] = _clip_chars(footer, 80)
    return card


def result_card(question: str, reply: str, language: str, tz: str) -> tuple[Card, str]:
    """His reply as a card (a call when it has a verdict line), and the words `hear` speaks."""
    text, verdict = split_call(reply)
    body, footer = _body(text, language)
    if not body and verdict is not None:
        body = verdict.default
    card_id = f"coach-{uuid.uuid4().hex[:10]}"
    title = title_from_question(question)
    if verdict is not None:
        card = call_card(card_id, title, body, verdict, language, tz, footer=footer)
    else:
        card = {
            "id": card_id,
            "kind": "answer",
            "title": title,
            "body": body,
            "source": "coach",
            "created_at": now_iso(tz),
            "actions": _actions(language, why=False),
        }
        if footer:
            card["footer"] = footer
    return card, say_text(text) or say_text(body)


def job_card(card_id: str, question: str, language: str, tz: str) -> Card:
    asked = _clip_chars(plain_text(question), 200)
    if language == "es":
        body = f"Preguntaste: {asked} Déjalo; su jugada aparece aquí."
    else:
        body = f"You asked: {asked} Put it down; his call shows up here."
    return {
        "id": card_id,
        "kind": "job",
        "title": ON_IT.get(language, ON_IT["en"]),
        "body": _clip_chars(body, BODY_MAX_CHARS),
        "source": "coach",
        "created_at": now_iso(tz),
        "data": {"status": "running"},
    }


def failed_card(card_id: str, reason: str, language: str, tz: str) -> Card:
    """Replaces the job card. It says what happened; nothing was decided."""
    if language == "es":
        title, tail = "Coach no terminó", "No hay jugada. Pregúntale de nuevo."
    else:
        title, tail = "Coach didn't finish", "No call was made. Ask him again."
    return {
        "id": card_id,
        "kind": "notice",
        "title": title,
        "body": _clip_chars(f"{reason.strip()} {tail}".strip(), BODY_MAX_CHARS),
        "source": "coach",
        "created_at": now_iso(tz),
    }


def coach_notice(card_id: str, title: str, body: str, tz: str, stale: bool = False) -> Card:
    card: Card = {
        "id": card_id[:64],
        "kind": "notice",
        "title": _clip_chars(title, 60),
        "body": _clip_chars(body, BODY_MAX_CHARS),
        "source": "coach",
        "created_at": now_iso(tz),
    }
    if stale:
        card["stale"] = True
    return card


# --- the ledger: his latest delivered call (the fast path) ------------------------------------


class LedgerError(Exception):
    """The ledger couldn't be read (not the same as "no call yet")."""


class Ledger(Protocol):
    async def tail(self) -> str:
        """The last lines of his decision ledger (JSON lines). Raises LedgerError."""
        ...


@dataclass
class ContainerLedger:
    """`docker exec <container> tail -n N <path>` (over SSH unless alias is `local`). Read-only."""

    ssh_alias: str
    container: str
    path: str
    lines: int = 200
    timeout: float = 15.0
    command: list[str] | None = None  # tests

    def _command(self) -> list[str]:
        if self.command is not None:
            return self.command
        remote = ["docker", "exec", self.container, "tail", "-n", str(self.lines), self.path]
        if self.ssh_alias == "local":
            return remote
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            self.ssh_alias,
            shlex.join(remote),
        ]

    async def tail(self) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._command(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise LedgerError(f"can't reach the Hermes host ({exc.strerror or exc})") from exc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), self.timeout)
        except TimeoutError as exc:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise LedgerError("the ledger read timed out") from exc
        if proc.returncode:
            log.warning("coach ledger read exited %s: %s", proc.returncode, stderr.decode()[-200:])
            raise LedgerError("his ledger couldn't be read")
        return stdout.decode(errors="replace")


@dataclass(frozen=True)
class LedgerCall:
    call: str
    decided_at: datetime
    deadline: datetime | None
    flip_if: str | None
    kind: str
    week: int | None
    decision_id: str


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def latest_delivered(text: str) -> LedgerCall | None:
    """The newest ledger entry that was delivered to the owner and names a call."""
    for raw in reversed(text.splitlines()):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("delivered") is not True:
            continue
        call = entry.get("call")
        decided = _parse_time(entry.get("decided_at"))
        if not isinstance(call, str) or not call.strip() or decided is None:
            continue
        flip = entry.get("flip_condition")
        week = entry.get("week")
        return LedgerCall(
            call=call.strip(),
            decided_at=decided,
            deadline=_parse_time(entry.get("deadline")),
            flip_if=flip.strip() if isinstance(flip, str) and flip.strip() else None,
            kind=str(entry.get("kind") or "call"),
            week=week if isinstance(week, int) and not isinstance(week, bool) else None,
            decision_id=str(entry.get("decision_id") or uuid.uuid4().hex[:12]),
        )
    return None


_WEEKDAYS = {
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "es": ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"),
}


def local_stamp(when: datetime, tz: str, language: str) -> str:
    local = when.astimezone(ZoneInfo(tz))
    day = _WEEKDAYS.get(language, _WEEKDAYS["en"])[local.weekday()]
    return f"{day} {local:%H:%M}"


def age_text(seconds: float, language: str) -> str:
    minutes = max(0, int(seconds // 60))
    if minutes < 1:
        span = "<1 min"
    elif minutes < 60:
        span = f"{minutes} min"
    elif minutes < 48 * 60:
        span = f"{minutes // 60} h"
    else:
        span = f"{minutes // (24 * 60)} d"
    return f"Hace {span}" if language == "es" else f"{span} ago"


def _verdict_of(call: str) -> str:
    """A short verdict from the ledger's sentence: its last clause when that's short enough."""
    clauses = [c.strip(" .") for c in re.split(r"[;:]", call) if c.strip(" .")]
    for clause in (clauses[-1:] + clauses[:1]) if clauses else []:
        if len(clause) <= 40:
            return clause[:1].upper() + clause[1:]
    return _clip_chars(call.rstrip("."), 40)


_KIND_TITLES = {
    "en": {"lineup": "lineup", "waiver": "waivers", "trade": "trade", "hold": "hold"},
    "es": {"lineup": "alineación", "waiver": "waivers", "trade": "intercambio", "hold": "espera"},
}


def ledger_card(entry: LedgerCall, language: str, tz: str, now: datetime) -> Card:
    """His latest call as a Coach's call card; the footer says how old it is."""
    kinds = _KIND_TITLES.get(language, _KIND_TITLES["en"])
    what = kinds.get(entry.kind, entry.kind)
    if entry.week is not None:
        title = f"Semana {entry.week}: {what}" if language == "es" else f"Week {entry.week} {what}"
    else:
        title = "Última jugada de Coach" if language == "es" else "Coach's latest call"
    age = age_text((now - entry.decided_at).total_seconds(), language)
    called = f"Jugada: {age.lower()}" if language == "es" else f"Called {age}"
    deadline = local_stamp(entry.deadline, tz, language) if entry.deadline else None
    passed = entry.deadline is not None and entry.deadline < now
    if passed:
        called += " · ya pasó la hora" if language == "es" else " · deadline passed"
    body, _ = _body(entry.call, language)
    card = call_card(
        f"coach-call-{entry.decision_id}"[:64],
        title,
        body,
        Verdict(_verdict_of(entry.call), deadline, entry.flip_if),
        language,
        tz,
        created_at=entry.decided_at.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds"),
        footer=called,
    )
    if passed:
        card["stale"] = True
    return card


# --- walk-away jobs -----------------------------------------------------------------------------

Listener = Callable[["Delivery"], Awaitable[None]]


@dataclass
class Delivery:
    """A finished job: the card that replaces the job card, and what `hear` would say."""

    job_id: str
    card: Card
    say: str
    language: str
    ok: bool
    displayed: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "card": self.card,
            "say": self.say,
            "language": self.language,
            "ok": self.ok,
            "displayed": self.displayed,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Delivery:
        return cls(
            job_id=str(raw["job_id"]),
            card=dict(raw["card"]),
            say=str(raw.get("say", "")),
            language=str(raw.get("language", "en")),
            ok=bool(raw.get("ok", False)),
            displayed=bool(raw.get("displayed", False)),
        )


@dataclass
class Job:
    card: Card  # the "Coach is on it" job card
    question: str
    language: str
    started: float = field(default_factory=time.monotonic)

    @property
    def id(self) -> str:
        return str(self.card["id"])


class CoachDesk:
    """Coach's walk-away jobs, shared by every connection (one device in v0).

    `agent` None means Coach is disabled. One job at a time. Results are persisted before they
    are offered to a listener, so a device that disconnected mid-job gets them on reconnect.
    """

    def __init__(
        self,
        agent: Agent | None,
        tz: str,
        path: Path | None = None,
        timeout: float = COACH_TIMEOUT_SECONDS,
        ledger: Ledger | None = None,
        validate: Callable[[Card], Card] | None = None,
        persona: Persona = DEFAULT_PERSONA,
    ) -> None:
        self.agent = agent
        self.tz = tz
        self.persona = persona
        self.path = path
        self.timeout = timeout
        self.ledger = ledger
        self.validate = validate or (lambda card: card)
        self.history: list[Message] = []
        self.jobs: dict[str, Job] = {}
        self.results: list[Delivery] = []
        self.last_timing: float | None = None  # seconds, the last finished job (logs, tests)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._listeners: list[Listener] = []
        self._load()

    @property
    def enabled(self) -> bool:
        return self.agent is not None

    @property
    def busy(self) -> bool:
        return bool(self.jobs)

    # --- listeners (connected sessions) ---

    def attach(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def detach(self, listener: Listener) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(listener)

    # --- jobs ---

    def submit(self, question: str, language: str) -> Card:
        """Start a walk-away job now; returns its job card. The caller checks `busy` first."""
        if self.agent is None:
            raise RuntimeError("Coach is disabled")
        card_id = f"coach-job-{uuid.uuid4().hex[:10]}"
        card = self.validate(job_card(card_id, question, language, self.tz))
        job = Job(card=card, question=question, language=language)
        self.jobs[job.id] = job
        self._save()
        self._tasks[job.id] = asyncio.create_task(self._run(job), name=f"coach-{job.id}")
        log.info("coach job %s started", job.id)
        return card

    async def _run(self, job: Job) -> None:
        assert self.agent is not None
        question: Message = {"role": "user", "content": job.question}
        messages = [*coach_messages(job.language, self.history, self.persona, self.tz), question]
        delivery: Delivery
        try:
            async with asyncio.timeout(self.timeout):
                reply = (await self.agent.reply(messages)).strip()
            if not reply:
                raise AgentError("Coach sent an empty answer.")
            card, say = result_card(job.question, reply, job.language, self.tz)
            delivery = Delivery(job.id, self.validate(card), say, job.language, ok=True)
            self.history = [*self.history, question, {"role": "assistant", "content": reply}]
            self.history = self.history[-2 * HISTORY_TURNS :]
        except (TimeoutError, AgentTimeout):
            minutes = f"{self.timeout / 60:g}"
            reason = (
                f"Coach no respondió en {minutes} minutos."
                if job.language == "es"
                else f"Coach didn't answer within {minutes} minutes."
            )
            delivery = self._failure(job, reason)
        except AgentError as exc:
            delivery = self._failure(job, str(exc) or "Coach couldn't answer.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a bug must still end the job honestly
            log.exception("coach job %s crashed", job.id)
            delivery = self._failure(job, f"Coach's job failed ({type(exc).__name__}).")
        self.last_timing = time.monotonic() - job.started
        log.info("coach job %s finished ok=%s in %.1fs", job.id, delivery.ok, self.last_timing)
        self.jobs.pop(job.id, None)
        self._tasks.pop(job.id, None)
        self.results = [*self.results, delivery][-RESULTS_KEPT:]
        self._save()
        for listener in list(self._listeners):
            try:
                await listener(delivery)
            except Exception:
                log.exception("coach delivery to a listener failed; it stays pending")

    def _failure(self, job: Job, reason: str) -> Delivery:
        log.warning("coach job %s failed: %s", job.id, reason)
        card = self.validate(failed_card(job.id, reason, job.language, self.tz))
        return Delivery(job.id, card, "", job.language, ok=False)

    # --- delivered cards ---

    def undelivered(self) -> list[Delivery]:
        return [d for d in self.results if not d.displayed]

    def find(self, card_id: str) -> Delivery | None:
        return next((d for d in reversed(self.results) if d.card["id"] == card_id), None)

    def mark_displayed(self, card_id: str) -> None:
        delivery = self.find(card_id)
        if delivery is not None and not delivery.displayed:
            delivery.displayed = True
            self._save()

    def forget(self, card_id: str) -> None:
        before = len(self.results)
        self.results = [d for d in self.results if d.card["id"] != card_id]
        if len(self.results) != before:
            self._save()

    # --- persistence ---

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text())
            self.results = [Delivery.from_json(r) for r in raw.get("results", [])]
            interrupted = [dict(j) for j in raw.get("jobs", [])]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning("coach jobs file unreadable (%s); starting empty", exc)
            self.results = []
            return
        for job in interrupted:  # the server stopped mid-job: say so, don't pretend
            language = str(job.get("language", "en"))
            reason = (
                "El servidor se reinició mientras Coach trabajaba."
                if language == "es"
                else "The server restarted while Coach was working."
            )
            card_id = str(job.get("id") or f"coach-job-{uuid.uuid4().hex[:10]}")
            card = failed_card(card_id, reason, language, self.tz)
            self.results.append(Delivery(card_id, card, "", language, ok=False))
        self.results = self.results[-RESULTS_KEPT:]
        if interrupted:
            self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        state = {
            "jobs": [
                {"id": j.id, "question": j.question, "language": j.language, "card": j.card}
                for j in self.jobs.values()
            ],
            "results": [d.to_json() for d in self.results],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        tmp.replace(self.path)

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(BaseException):
                await task
