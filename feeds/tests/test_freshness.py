"""Fresh, stale, failed, unreadable and missing feeds, section by section."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from conftest import FIXTURE_NOW, built, edit_feed, write_feed

from charm_feeds.cards import SECTIONS
from charm_feeds.schema import CardValidator
from charm_feeds.sources import FEEDS

FAR = "2027-01-01T00:00:00+00:00"


def _content(card: dict[str, Any]) -> list[Any]:
    data = card["data"]
    return [data.get("rows"), data.get("tiles"), data.get("moon")]


def _all_fresh(directory: Path) -> None:
    for spec in FEEDS:
        edit_feed(directory, spec.name, lambda p: p.update(fresh_until=FAR))


def test_all_fresh_carries_fresh_until_and_nothing_is_stale(
    feed_dir: Path, validator: CardValidator
) -> None:
    _all_fresh(feed_dir)
    cards = built(feed_dir, validator)
    assert list(cards) == list(SECTIONS)
    for section, card in cards.items():
        assert "stale" not in card, section
        assert "footer" not in card, section
        assert card["fresh_until"] == FAR, section
    assert cards["masthead"]["data"]["tiles"] == [{"value": "5 of 5", "label": "Desks fresh"}]
    # The sports card carries the desk's own filing time.
    assert cards["sports"]["created_at"] == "2026-09-25T13:31:01+00:00"


def test_stale_feed_keeps_content_with_plain_wording(
    feed_dir: Path, validator: CardValidator
) -> None:
    edit_feed(feed_dir, "sports", lambda p: p.update(fresh_until="2026-09-25T10:00:00+00:00"))
    card = built(feed_dir, validator)["sports"]
    assert card["stale"] is True
    assert card["footer"] == "Sports desk missed deadline — last filed Fri 08:31"
    assert card["fresh_until"] == "2026-09-25T10:00:00+00:00"
    assert card["data"]["rows"], "stale content is still shown, labeled"


def test_real_stale_digest_marks_its_sections(feed_dir: Path, validator: CardValidator) -> None:
    cards = built(feed_dir, validator)
    for section in ("masthead", "one_thing", "waiting"):
        assert cards[section]["stale"] is True, section
        assert cards[section]["footer"] == "Digest desk missed deadline — last filed Thu 22:33"
    assert "stale" not in cards["sports"]
    assert "stale" not in cards["almanac"]


def test_failed_feed_shows_no_content(feed_dir: Path, validator: CardValidator) -> None:
    edit_feed(feed_dir, "sports", lambda p: p.update(status="failed", fresh_until=FAR))
    card = built(feed_dir, validator)["sports"]
    assert card["stale"] is True
    assert card["body"] == "Sports desk missed deadline — last filed Fri 08:31"
    assert _content(card) == [None, None, None]


def test_unreadable_feed_says_so(feed_dir: Path, validator: CardValidator) -> None:
    (feed_dir / "almanac.json").write_text("{not json", encoding="utf-8")
    card = built(feed_dir, validator)["almanac"]
    assert card["stale"] is True
    assert card["body"] == "Almanac desk filing couldn't be read."
    assert _content(card) == [None, None, None]


def test_feed_without_generated_at_is_failed(feed_dir: Path, validator: CardValidator) -> None:
    edit_feed(feed_dir, "almanac", lambda p: p.pop("generated_at"))
    card = built(feed_dir, validator)["almanac"]
    assert card["stale"] is True
    assert _content(card) == [None, None, None]


def test_missing_feed_is_honest_empty(feed_dir: Path, validator: CardValidator) -> None:
    (feed_dir / "sports.json").unlink()
    cards = built(feed_dir, validator)
    card = cards["sports"]
    assert card["body"] == "No filing from the sports desk yet."
    assert _content(card) == [None, None, None]
    assert "stale" not in card
    assert "fresh_until" not in card
    rows = [r["text"] for r in cards["masthead"]["data"]["rows"]]
    assert "Sports desk · no filing" in rows


def test_nothing_pulled_gives_six_honest_cards(tmp_path: Path, validator: CardValidator) -> None:
    cards = built(tmp_path, validator)
    assert list(cards) == list(SECTIONS)
    assert cards["masthead"]["data"]["tiles"] == [{"value": "0 of 5", "label": "Desks fresh"}]
    assert cards["masthead"]["body"] == "No filing from the digest desk yet."
    for section in SECTIONS[1:]:
        card = cards[section]
        assert _content(card) == [None, None, None], section
        assert card["body"].startswith("No filing from the "), section
        assert card["created_at"] == FIXTURE_NOW.isoformat()


def test_empty_sections_say_nothing_was_filed(feed_dir: Path, validator: CardValidator) -> None:
    _all_fresh(feed_dir)
    edit_feed(feed_dir, "digest", lambda p: p.update(telegram_line="", sections={"decisions": []}))
    edit_feed(feed_dir, "almanac", lambda p: p.update(sections={}))
    cards = built(feed_dir, validator)
    assert cards["one_thing"]["body"] == "The digest desk filed nothing for this section."
    assert cards["waiting"]["body"] == "Nothing is waiting on you."
    assert "rows" not in cards["waiting"]["data"]
    assert cards["almanac"]["body"] == "The almanac desk filed nothing for this section."


def test_almanac_reading_is_labeled_with_its_time(
    feed_dir: Path, validator: CardValidator
) -> None:
    card = built(feed_dir, validator)["almanac"]
    labels = [t["label"] for t in card["data"]["tiles"]]
    assert labels[0] == "At 08:00"
    assert "Now" not in labels
    assert card["data"]["moon"] == "full_moon"


def test_wire_leaves_off_a_stale_desk_while_fresh_items_exist(
    feed_dir: Path, validator: CardValidator
) -> None:
    card = built(feed_dir, validator)["wire"]
    assert "stale" not in card
    assert card["footer"] == "Radar desk missed deadline — last filed Sun 14:02"
    assert all(r.get("stamp") != "Radar" for r in card["data"]["rows"])
    assert 1 <= len(card["data"]["rows"]) <= 12


def test_wire_runs_stale_items_labeled_when_nothing_fresh(
    feed_dir: Path, validator: CardValidator
) -> None:
    (feed_dir / "paper-feed.json").unlink()
    card = built(feed_dir, validator)["wire"]
    assert card["stale"] is True
    assert {r["stamp"] for r in card["data"]["rows"]} == {"Radar"}
    assert card["footer"] == "Radar desk missed deadline — last filed Sun 14:02"


def test_wire_honest_empty_when_no_source(feed_dir: Path, validator: CardValidator) -> None:
    (feed_dir / "paper-feed.json").unlink()
    (feed_dir / "radar.json").unlink()
    card = built(feed_dir, validator)["wire"]
    assert card["body"] == "No filing from the paper desk yet."
    assert _content(card) == [None, None, None]


def test_wire_prefers_a_desk_that_filed_nothing_over_a_missing_one(
    feed_dir: Path, validator: CardValidator
) -> None:
    (feed_dir / "radar.json").unlink()
    edit_feed(feed_dir, "paper-feed", lambda p: p.update(reading=[]))
    card = built(feed_dir, validator)["wire"]
    assert card["body"] == "The paper desk filed nothing for this section."
    assert "stale" not in card


def test_wire_never_carries_personal_mail(feed_dir: Path, validator: CardValidator) -> None:
    def life_only(p: dict[str, Any]) -> None:
        p["life"] = [{"from": "Bank <x@bank.example>", "subject": "Your transfer"}]
        p["reading"] = []

    edit_feed(feed_dir, "paper-feed", life_only)
    card = built(feed_dir, validator)["wire"]
    texts = [r["text"] for r in card["data"].get("rows", [])]
    assert "Your transfer" not in texts


def test_paper_feed_errors_mark_it_stale(feed_dir: Path, validator: CardValidator) -> None:
    (feed_dir / "radar.json").unlink()
    edit_feed(feed_dir, "paper-feed", lambda p: p.update(errors={"gmail": "quota"}))
    card = built(feed_dir, validator)["wire"]
    assert card["stale"] is True
    assert card["footer"] == "Paper desk filed with errors — last filed Fri 11:14"


def test_paper_feed_freshness_is_a_day_from_filing(
    feed_dir: Path, validator: CardValidator
) -> None:
    card = built(feed_dir, validator)["wire"]
    assert card["fresh_until"] == "2026-09-26T16:14:19+00:00"
    later = built(feed_dir, validator, FIXTURE_NOW + timedelta(days=1))["wire"]
    assert later["stale"] is True


def test_masthead_expires_when_the_first_fresh_desk_does(
    feed_dir: Path, validator: CardValidator
) -> None:
    cards = built(feed_dir, validator)
    assert cards["masthead"]["fresh_until"] == "2026-09-25T21:31:01+00:00"  # sports


def test_no_decision_cards_without_structured_items(
    feed_dir: Path, validator: CardValidator
) -> None:
    write_feed(feed_dir, "digest", {"generated_at": FIXTURE_NOW.isoformat(),
                                    "fresh_until": FAR, "status": "ok",
                                    "sections": {"decisions": ["Approve the thing?"]}})
    cards = built(feed_dir, validator)
    assert all(c["kind"] == "edition" for c in cards.values())
    assert "actions" not in cards["waiting"]
