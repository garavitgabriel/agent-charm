"""Who answers: Dex or Coach Beard (docs/PROTOCOL.md § Agents). Rule-based, EN + ES, no model call.

`route(text, reading)` returns a `Route`:

- **Coach, by wake word:** "Coach, …" / "Coach Beard, …" / "Entrenador, …" at the start. "Coach"
  must be followed by a comma (or colon) or by a question/command word, so "Coach Carter is a
  great movie" stays Dex. The wake word is removed from the question Coach gets.
- **Coach, by topic:** a clearly fantasy/NFL question (lineup, start/sit, waivers, a trade or
  "my team" with football words around it, the NFL itself, an injury status for the week).
  Outside reading mode only: a book about football stays with Dex while reading.
- **The fast path:** "What's Coach's latest call?" / "¿Cuál es la última jugada de Coach?" reads
  his ledger instead of asking him (`Route.latest_call`).
- Everything else goes to Dex.

The rules lean narrow on purpose: a question wrongly sent to Coach costs a 3-minute walk-away
job; a fantasy question that reaches Dex still gets an answer.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

DEX = "dex"
COACH = "coach"
AGENTS = (DEX, COACH)


@dataclass(frozen=True)
class Route:
    agent: str  # "dex" | "coach"
    question: str  # what the agent is asked (the wake word removed)
    reason: str  # "default" | "wake" | "topic" | "latest" (logged, never the transcript)
    latest_call: bool = False


def _fold(text: str) -> str:
    """Lowercase and without accents, punctuation kept: "¿Cuál?" -> "¿cual?"."""
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _words(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w' ]+", " ", _fold(text))).strip()


# --- the wake word ------------------------------------------------------------------------------

_LEAD = r"(?:(?:hey|hi|ok|okay|oye|ey|so|and|y|bueno|vale|yo)[\s,]+)*"
_NAME = r"(?:coach(?:\s+beard)?|entrenador)"
# Words that make "Coach <word> …" an address, not a name ("Coach Carter", "coach class").
_ADDRESS_WORDS = (
    "should shall would will can could do does did is are was were who whom whose what which "
    "when where why how give tell start sit bench drop add pick trade help check look any "
    "quick i my me we let lets let's thoughts "
    "debo deberia puedo pongo quien que cual cuales cuando donde como por dame dime ayudame "
    "revisa mira tengo hay es esta estan mi mis me alguna algun"
)
_WAKE = re.compile(
    rf"^\W*{_LEAD}{_NAME}\b\s*(?:[,:;.!?—-]+\s*|(?=(?:{'|'.join(_ADDRESS_WORDS.split())})\b))",
)


def strip_wake(text: str) -> str | None:
    """The question after a Coach wake word, or None when the text doesn't start with one."""
    folded = _fold(text)
    match = _WAKE.match(folded)
    if match is None:
        return None
    # Accents don't change length in NFKD-folded text only for precomposed letters, so cut the
    # original by counting the folded prefix's words instead of by index.
    prefix_words = len(folded[: match.end()].split())
    rest = text.split(maxsplit=prefix_words)
    question = rest[prefix_words] if len(rest) > prefix_words else ""
    question = question.lstrip(" ,:;.!?-—")
    return question[:1].upper() + question[1:] if question else ""


# --- the topic ----------------------------------------------------------------------------------

# One of these alone makes it a fantasy/NFL question.
_STRONG = re.compile(
    r"\b(?:"
    r"nfl|fantasy (?:football|team|league|lineup|roster|draft|points|matchup|week)|"
    r"(?:mi |el )?(?:equipo|liga|alineacion) de fantasy|fantasy de (?:la )?nfl|"
    r"waivers?(?: wire)?|faab|start(?: or | ?/ ?| and )sit|start sit|sit or start|"
    r"(?:my|the) (?:fantasy )?lineup|my starting lineup|mi alineacion|la alineacion|"
    r"alineacion (?:de|para) (?:esta semana|el domingo|la semana)|zone read|pick ?'?em|"
    r"quarterback|mariscal de campo|running back|wide receiver|tight end|d ?/ ?st|touchdowns?|"
    r"injury report|reporte de lesiones|super bowl|monday night football|sunday night football|"
    r"thursday night football"
    r")\b"
)
# Football words that make a weak phrase ("my team", "trade", "start X or Y") clear.
# Only words that don't have an everyday meaning ("bench", "points", "bills" and "hurts" do).
_FOOTBALL = re.compile(
    r"\b(?:qb|rb|wr|te|flex|kicker|ppr|td|touchdowns?|projected|proyectado|matchup|"
    r"week \d+|semana \d+|monday night|thursday night|sunday night|"
    r"purdy|mahomes|maye|lamar|niners|49ers|steelers|patriots|cowboys|bengals|ravens|packers|"
    r"dolphins|broncos|seahawks|vikings|commanders|buccaneers|texans|jaguars)\b"
)
_WEAK = re.compile(
    r"\b(?:my team|mi equipo|trade|intercambio|cambio|start|sit|bench|banca|titular|drop|"
    r"pick up|pickup|add|injur(?:y|ed)|lesion(?:ado|ada)?|questionable|doubtful|ruled out|"
    r"playing|play)\b"
)
_NOT_FOOTBALL = re.compile(
    r"\b(?:trade deficit|trade war|trade school|start the (?:car|meeting|timer|oven)|"
    r"fantasy (?:novel|book|books|series|movie|film|author))\b"
)


def is_fantasy_question(text: str) -> bool:
    words = _words(text)
    if not words or _NOT_FOOTBALL.search(words):
        return False
    if _STRONG.search(words):
        return True
    return bool(_WEAK.search(words) and _FOOTBALL.search(words))


# --- the fast path ------------------------------------------------------------------------------

_CALL = r"(?:call|decision|pick|verdict|jugada|llamada|decision|recomendacion)"
_RECENT_EN = r"(?:latest|last|most recent|newest)"
_RECENT_ES = r"(?:ultima|mas reciente)"
_WHO = r"(?:coach(?: beard)?|entrenador)"
# Naming Coach: works whoever it's addressed to.
_LATEST = re.compile(
    rf"\b(?:{_WHO}'?s? {_RECENT_EN} {_CALL}|{_RECENT_EN} {_CALL} (?:from|by|of) {_WHO}|"
    rf"what did {_WHO} (?:call|decide|pick)|"
    rf"{_RECENT_ES} {_CALL} (?:de|del) {_WHO}|que (?:decidio|dijo) (?:el )?{_WHO})\b"
)
# After "Coach, …": "what's your latest call?" / "¿cuál es tu última jugada?".
_LATEST_YOURS = re.compile(
    rf"\b(?:your {_RECENT_EN} {_CALL}|what did you (?:call|decide|pick) last|"
    rf"(?:tu|su) {_RECENT_ES} {_CALL})\b"
)


def is_latest_call(text: str, addressed: bool = False) -> bool:
    """The fast path. `addressed`: the text followed a Coach wake word ("your" means Coach)."""
    words = _words(text)
    return bool(_LATEST.search(words) or (addressed and _LATEST_YOURS.search(words)))


# --- all together -------------------------------------------------------------------------------


def route(text: str, reading: bool = False) -> Route:
    """Who answers `text`. The fast path first, then the wake word, then the topic."""
    after_wake = strip_wake(text)
    if is_latest_call(text) or (
        after_wake is not None and is_latest_call(after_wake, addressed=True)
    ):
        return Route(COACH, after_wake or text, "latest", latest_call=True)
    if after_wake is not None:
        return Route(COACH, after_wake or text, "wake")
    if not reading and is_fantasy_question(text):
        return Route(COACH, text, "topic")
    return Route(DEX, text, "default")
