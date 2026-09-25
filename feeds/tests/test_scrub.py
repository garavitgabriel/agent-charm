"""The scrubber's rules, and a sweep of the committed fixtures for anything that slipped through."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import CARDS, RAW

from charm_feeds.scrub import REDACTED_EMAIL, scrub_feed, scrub_text

COMMITTED = sorted(RAW.glob("*.json")) + sorted(CARDS.glob("*.json"))

LEAKS = {
    "email": re.compile(r"[\w.+-]+@(?!example\.invalid)[\w-]+(?:\.[\w-]+)+"),
    "url with query or fragment": re.compile(r"https?://[^\s\"]*[?#]"),
    "gmail link": re.compile(r"mail\.google\.com"),
    "money": re.compile(r"[$€£]\s?\d|\d\s?(?:COP|USD|MXN|EUR)\b"),
    "long number": re.compile(r"\b\d{7,}\b"),
    "phone": re.compile(r"\+\d{1,3}[\s-]?\(?\d{1,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}"),
    "token": re.compile(r"\b(?:sk|ghp|xox[abp])[-_][A-Za-z0-9_-]{10,}|\beyJ[A-Za-z0-9_-]{16,}"),
}


@pytest.mark.parametrize("path", COMMITTED, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_committed_fixture_has_no_leaks(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for kind, pattern in LEAKS.items():
        hit = pattern.search(text)
        assert hit is None, f"{kind}: {hit.group(0) if hit else ''}"


def test_paper_fixture_drops_mail_bodies_ids_and_senders() -> None:
    paper = json.loads((RAW / "paper-feed.json").read_text(encoding="utf-8"))
    assert paper["account"] == REDACTED_EMAIL
    for pile in ("life", "reading"):
        for mail in paper[pile]:
            assert set(mail) <= {"from", "subject", "date", "labels"}
            assert mail["from"] in ("[sender]", "[personal sender]")
    assert {m["subject"] for m in paper["life"]} == {"[personal mail]"}


def test_sports_fixture_has_no_league_identity() -> None:
    sports = json.loads((RAW / "sports.json").read_text(encoding="utf-8"))
    text = json.dumps(sports)
    assert '"league_id": "0"' in text
    assert "Sample League" in text
    headlines = sports["sections"]["power_rankings"]["structuredContent"]["headlines"]
    assert {h["title"] for h in headlines} == {"[headline]"}


def test_scrub_text_rules() -> None:
    assert scrub_text("mail ana@corp.co now") == f"mail {REDACTED_EMAIL} now"
    assert scrub_text("see https://x.io/a/b?token=abc#frag ok") == "see https://x.io/a/b ok"
    assert scrub_text("call +57 300 123 4567") == "call [phone]"
    assert scrub_text("spent $49 and 51.300 COP") == "spent [amount] and [amount]"
    assert scrub_text("ticket 14922514") == "ticket [number]"
    assert scrub_text("2026-09-25T13:00:50+00:00") == "2026-09-25T13:00:50+00:00"
    assert scrub_text("Projected 118.6, 2-0") == "Projected 118.6, 2-0"


def test_scrub_feed_replaces_other_teams_everywhere() -> None:
    payload = {
        "sections": {
            "today": {"team": "Mine", "league": "Friends League", "say": "Mine vs Rivals"},
            "league_overview": {
                "structuredContent": {"rosters": [{"team": "Rivals", "owner": "Bob"},
                                                  {"team": "Mine", "owner": "me"}]},
                "text": '{"team": "Rivals"}',
            },
        }
    }
    out = json.dumps(scrub_feed("sports", payload))
    assert "Rivals" not in out and "Bob" not in out and "Friends League" not in out
    assert "Mine" in out
