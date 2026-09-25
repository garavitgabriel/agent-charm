"""`charm-feeds scrub`: turn a pulled cache into committable fixtures.

What gets removed, and why, is written up in `feeds/fixtures/SCRUBBING.md`. The rules here are the
source of truth for that file; `tests/test_scrub.py` checks the committed fixtures against them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from charm_feeds.sources import FEEDS_BY_NAME

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_TAIL = re.compile(r"(https?://[^\s?#\"'<>]+)[?#][^\s\"'<>]*")
PHONE = re.compile(
    r"\+\d{1,3}[\s-]?\(?\d{1,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}"
    r"|\(\d{3}\)\s?\d{3}-\d{4}"
    r"|\b\d{3}[\s.]\d{3}[\s.]\d{4}\b"
)
MONEY = re.compile(
    r"[$€£]\s?\d[\d.,]*[kKmM]?"
    r"|\b\d[\d.,]*\s?(?:COP|USD|MXN|EUR|ARS|pesos|dólares|dollars)\b",
    re.IGNORECASE,
)
LONG_NUMBER = re.compile(r"\b\d{7,}\b")
TOKENISH = re.compile(r"\b(?:sk|pk|ghp|gho|xox[abp]|eyJ)[A-Za-z0-9_-]{16,}")
INSTITUTIONS = re.compile(r"\bExample Bank\b")

REDACTED_EMAIL = "redacted@example.invalid"


def scrub_text(text: str) -> str:
    text = EMAIL.sub(REDACTED_EMAIL, text)
    text = URL_TAIL.sub(r"\1", text)
    text = TOKENISH.sub("[token]", text)
    text = PHONE.sub("[phone]", text)
    text = MONEY.sub("[amount]", text)
    text = LONG_NUMBER.sub("[number]", text)
    return INSTITUTIONS.sub("[bank]", text)


def _walk(value: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_walk(v, fn) for v in value]
    if isinstance(value, dict):
        return {k: _walk(v, fn) for k, v in value.items()}
    return value


def _replace_names(value: Any, names: dict[str, str]) -> Any:
    # Longest first, so "Team A 2.0" goes before "Team A".
    ordered = sorted((n for n in names if n), key=len, reverse=True)

    def fn(text: str) -> str:
        for name in ordered:
            text = text.replace(name, names[name])
        return text

    return _walk(value, fn)


def _sports(payload: dict[str, Any]) -> dict[str, Any]:
    """Other managers' team names, league headlines, the league's name and id, owners and budget
    amounts go; public NFL players,
    and the public reporters quoted in injury notes, stay (they're the content)."""
    sections = payload.get("sections") or {}
    today = sections.get("today") or {}
    own_team = today.get("team")
    names: dict[str, str] = {}
    league = today.get("league")
    if isinstance(league, str):
        names[league] = "Sample League"

    others: list[object] = []
    overview = (sections.get("league_overview") or {}).get("structuredContent") or {}
    others += [r.get("team") for r in overview.get("rosters") or [] if isinstance(r, dict)]
    rankings = (sections.get("power_rankings") or {}).get("structuredContent") or {}
    others += [r.get("team") for r in rankings.get("rankings") or [] if isinstance(r, dict)]
    matchup = (sections.get("matchup_preview") or {}).get("structuredContent") or {}
    for side in ("home", "away"):
        others.append((matchup.get(side) or {}).get("team"))
    for team in others:
        if isinstance(team, str) and team and team != own_team and team not in names:
            names[team] = f"Team {len(names)}"

    def strip(value: Any) -> Any:
        if isinstance(value, list):
            return [strip(v) for v in value]
        if not isinstance(value, dict):
            return value
        out: dict[str, Any] = {}
        for key, v in value.items():
            if key == "text" and "structuredContent" in value:
                continue  # a JSON dump duplicating structuredContent
            if key in ("owner", "league_id"):
                out[key] = None if key == "owner" else "0"
                continue
            if key == "headlines" and isinstance(v, list):
                # Headlines name other teams by nickname, which the name map can't catch.
                out[key] = [{**h, "title": "[headline]"} if isinstance(h, dict) else h for h in v]
                continue
            if key == "faabNote":
                out[key] = "[amount]"  # the auction budget, money-shaped
                continue
            out[key] = strip(v)
        return out

    return dict(_replace_names(strip(payload), names))


def _paper(payload: dict[str, Any]) -> dict[str, Any]:
    """Mail bodies, ids, links and senders go. Reading-pile subjects (public newsletter headlines)
    stay; personal (`life`) mail loses its subject too. Calendar events keep only their times."""
    out = dict(payload)
    if "account" in out:
        out["account"] = REDACTED_EMAIL
    for pile in ("life", "reading"):
        mails = []
        for mail in out.get(pile) or []:
            if not isinstance(mail, dict):
                continue
            kept = {k: mail[k] for k in ("from", "subject", "date", "labels") if k in mail}
            if pile == "life":
                kept["from"] = "[personal sender]"
                kept["subject"] = "[personal mail]"
            elif "from" in kept:
                kept["from"] = "[sender]"  # display names are often a person's name
            mails.append(kept)
        out[pile] = mails
    events = []
    for event in out.get("events") or []:
        if isinstance(event, dict):
            kept = {k: event[k] for k in ("start", "end", "time", "all_day") if k in event}
            kept["summary"] = "[event]"
            events.append(kept)
    out["events"] = events
    return out


PER_FEED: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "sports": _sports,
    "paper-feed": _paper,
}


def scrub_feed(name: str, payload: Any) -> Any:
    if isinstance(payload, dict) and name in PER_FEED:
        payload = PER_FEED[name](payload)
    return _walk(payload, scrub_text)


def scrub_dir(src: Path, dst: Path) -> list[str]:
    """Scrub every allowlisted feed found in `src` into `dst`. Returns the names written."""
    dst.mkdir(parents=True, exist_ok=True)
    written = []
    for name in FEEDS_BY_NAME:
        path = src / f"{name}.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        clean = scrub_feed(name, payload)
        (dst / path.name).write_text(
            json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(name)
    return written
