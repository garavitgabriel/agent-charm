"""Text clipping, and that oversized feed content still yields contract-valid cards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import built, edit_feed

from charm_feeds.schema import CardValidator
from charm_feeds.text import ELLIPSIS, clean, clip


def test_clip_leaves_short_text_alone() -> None:
    assert clip("  Bench   Kittle  ", 80) == "Bench Kittle"


def test_clip_cuts_on_a_word_boundary_with_ellipsis() -> None:
    out = clip("alpha beta gamma delta epsilon", 17)
    assert out == "alpha beta" + ELLIPSIS
    assert len(out) <= 17


def test_clip_word_limit() -> None:
    assert clip("one two three four", 100, max_words=2) == "one two" + ELLIPSIS


def test_clip_hard_cuts_a_single_long_word() -> None:
    out = clip("x" * 50, 10)
    assert len(out) == 10 and out.endswith(ELLIPSIS)


def test_clean_drops_emoji_and_markdown() -> None:
    assert clean("☕ **Why** did `today` ⚙️ run? 😺") == "Why did today run?"
    assert clean("Springfield 19°C — ok") == "Springfield 19°C — ok"


def test_oversized_content_still_validates(feed_dir: Path, validator: CardValidator) -> None:
    long = "word " * 400

    def bloat_sports(p: dict[str, Any]) -> None:
        p["summary_line"] = long
        p["sections"]["today"]["do_now"] = [
            {"headline": f"{i} {long}", "deadline": long} for i in range(10)
        ]
        p["sections"]["today"]["numbers"] = {"projected_points": 123456789.123,
                                             "win_probability": 0.674}

    def bloat_digest(p: dict[str, Any]) -> None:
        p["summary_line"] = p["telegram_line"] = long
        p["sections"]["decisions"] = [f"{i} {long}" for i in range(40)]

    def bloat_paper(p: dict[str, Any]) -> None:
        p["reading"] = [{"from": long, "subject": f"{i} {long}"} for i in range(40)]

    def bloat_almanac(p: dict[str, Any]) -> None:
        p["sections"]["moon_phase"]["name"] = long

    edit_feed(feed_dir, "sports", bloat_sports)
    edit_feed(feed_dir, "digest", bloat_digest)
    edit_feed(feed_dir, "paper-feed", bloat_paper)
    edit_feed(feed_dir, "almanac", bloat_almanac)
    cards = built(feed_dir, validator)  # raises if any card breaks the contract
    assert len(cards["sports"]["data"]["rows"]) == 3
    assert len(cards["waiting"]["data"]["rows"]) == 12
    assert len(cards["wire"]["data"]["rows"]) == 12
    assert len(cards["sports"]["body"].split()) <= 60
    assert {"value": "67%", "label": "Win odds"} in cards["sports"]["data"]["tiles"]


def test_wrong_types_in_a_feed_do_not_crash(feed_dir: Path, validator: CardValidator) -> None:
    edit_feed(feed_dir, "sports", lambda p: p.update(sections={"today": ["not", "a", "dict"]},
                                                     summary_line=7))
    edit_feed(feed_dir, "almanac", lambda p: p["sections"].update(four_day="soon", now=None))
    cards = built(feed_dir, validator)
    assert cards["sports"]["body"] == "The sports desk filed nothing for this section."
