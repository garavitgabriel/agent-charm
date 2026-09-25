"""Feed -> card mapping for the six pocket-edition sections.

Honesty rules, applied to every card:

- A fresh feed gives content, with its `fresh_until` carried into the card.
- A stale feed still gives its content, marked `stale: true`, and the footer says
  "<Desk> missed deadline — last filed <when>".
- A failed or unreadable feed gives no content, only that plain wording, marked stale.
- A missing feed gives an honest-empty card: no rows, no tiles, just "No filing from …".

Nothing here makes up content. When a feed has no field for something a section wants, the card
leaves it out (see the gaps table in feeds/README.md).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Any

from charm_feeds.sources import Feed, State
from charm_feeds.text import clip, iso, local_clock, stamp

SECTIONS = ("masthead", "one_thing", "sports", "almanac", "waiting", "wire")

TITLE_MAX, BODY_MAX, BODY_WORDS, FOOTER_MAX = 60, 420, 60, 80
ROW_MAX, STAMP_MAX, ROWS_MAX = 80, 20, 12
TILE_VALUE_MAX, TILE_LABEL_MAX, TILES_MAX = 10, 14, 4
MOON_MAX = 20

Card = dict[str, Any]


@dataclass(frozen=True)
class Context:
    now: datetime
    tz: tzinfo


# ---------------------------------------------------------------- wording


def _desk(feed: Feed) -> str:
    return feed.spec.desk[0].upper() + feed.spec.desk[1:]


def trouble_note(feed: Feed, ctx: Context) -> str:
    """Plain wording for a feed that isn't fresh."""
    desk = _desk(feed)
    if feed.state is State.MISSING:
        return f"No filing from the {feed.spec.desk} yet."
    if feed.generated_at is None:
        return f"{desk} filing couldn't be read."
    when = stamp(feed.generated_at, ctx.tz, ctx.now)
    if feed.state is State.STALE and feed.payload and feed.payload.get("errors"):
        return clip(f"{desk} filed with errors — last filed {when}", FOOTER_MAX)
    return clip(f"{desk} missed deadline — last filed {when}", FOOTER_MAX)


def _nothing_filed(feed: Feed) -> str:
    return f"The {feed.spec.desk} filed nothing for this section."


# ---------------------------------------------------------------- card assembly


def _skeleton(section: str, title: str, source: str) -> Card:
    return {
        "id": f"ed-{section}",
        "kind": "edition",
        "title": clip(title, TITLE_MAX),
        "source": source,
        "data": {"section": section},
    }


def _has_content(card: Card) -> bool:
    data = card["data"]
    return bool(card.get("body") or data.get("rows") or data.get("tiles") or data.get("moon"))


def _strip_content(card: Card) -> None:
    card.pop("body", None)
    for key in ("rows", "tiles", "moon"):
        card["data"].pop(key, None)


def _finish(card: Card, feed: Feed, ctx: Context) -> Card:
    """Apply one source feed's freshness to a card whose content is already filled in."""
    if feed.state is State.MISSING:
        _strip_content(card)
        card["body"] = trouble_note(feed, ctx)
        card["created_at"] = iso(ctx.now)
        return card
    if feed.state is State.FAILED:
        _strip_content(card)
        card["body"] = trouble_note(feed, ctx)
        card["stale"] = True
    elif not _has_content(card):
        card["body"] = _nothing_filed(feed)
    if feed.state is State.STALE:
        card["stale"] = True
        card["footer"] = trouble_note(feed, ctx)
    card["created_at"] = iso(feed.generated_at or ctx.now)
    if feed.fresh_until is not None:
        card["fresh_until"] = iso(feed.fresh_until)
    return card


def _rows(items: Iterable[tuple[str, str | None]], limit: int = ROWS_MAX) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for text, when in items:
        text = clip(text, ROW_MAX)
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        row = {"text": text}
        if when and (when := clip(when, STAMP_MAX)):
            row["stamp"] = when
        rows.append(row)
        if len(rows) == limit:
            break
    return rows


def _tile(value: str, label: str) -> dict[str, str]:
    return {"value": clip(value, TILE_VALUE_MAX), "label": clip(label, TILE_LABEL_MAX)}


def _str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


# ---------------------------------------------------------------- sections


def masthead(feeds: dict[str, Feed], ctx: Context) -> Card:
    """Weekday, tonight's verdict (the digest's summary line), and which desks have filed."""
    weekday = ctx.now.astimezone(ctx.tz).strftime("%A")
    card = _skeleton("masthead", f"{weekday} edition", "edition")
    digest = feeds["digest"]
    verdict = _str(digest.payload.get("summary_line")) if digest.usable and digest.payload else ""

    status_words = {
        State.FRESH: "filed",
        State.STALE: "missed deadline",
        State.FAILED: "failed",
        State.MISSING: "no filing",
    }
    card["data"]["rows"] = _rows(
        (
            f"{_desk(f)} · {status_words[f.state]}",
            stamp(f.generated_at, ctx.tz, ctx.now) if f.generated_at else None,
        )
        for f in feeds.values()
    )
    fresh = [f for f in feeds.values() if f.state is State.FRESH]
    card["data"]["tiles"] = [_tile(f"{len(fresh)} of {len(feeds)}", "Desks fresh")]

    card["body"] = clip(verdict, BODY_MAX, BODY_WORDS) if verdict else trouble_note(digest, ctx)
    if digest.state is not State.FRESH and digest.state is not State.MISSING:
        card["stale"] = True
        if verdict:
            card["footer"] = trouble_note(digest, ctx)

    card["created_at"] = iso(ctx.now)
    # The desk rows stop being true as soon as the first fresh desk goes stale.
    deadlines = [f.fresh_until for f in fresh if f.fresh_until is not None]
    if deadlines:
        card["fresh_until"] = iso(min(deadlines))
    return card


def one_thing(feeds: dict[str, Feed], ctx: Context) -> Card:
    """The single priority: the digest's telegram line, which names what comes first."""
    digest = feeds["digest"]
    card = _skeleton("one_thing", "Today's one thing", "dex")
    if digest.usable and digest.payload:
        line = _str(digest.payload.get("telegram_line"))
        if line:
            card["body"] = clip(line, BODY_MAX, BODY_WORDS)
    return _finish(card, digest, ctx)


def sports(feeds: dict[str, Feed], ctx: Context) -> Card:
    """Coach Beard's verdict, up to 3 do-now rows with deadlines, and the week's numbers."""
    feed = feeds["sports"]
    card = _skeleton("sports", "Sports desk", "coach")
    if feed.usable and feed.payload:
        sections = feed.sections()
        today = _dict(sections.get("today"))
        verdict = _str(feed.payload.get("summary_line")) or _str(today.get("say"))
        if verdict:
            card["body"] = clip(verdict, BODY_MAX, BODY_WORDS)
        rows = _rows(
            ((_str(item.get("headline")), _str(item.get("deadline")) or None)
             for item in map(_dict, _list(today.get("do_now")))),
            limit=3,
        )
        if rows:
            card["data"]["rows"] = rows
        tiles = []
        numbers = _dict(today.get("numbers"))
        projected = _number(numbers.get("projected_points"))
        if projected is not None:
            tiles.append(_tile(f"{projected:g}", "Projected"))
        win = _number(numbers.get("win_probability"))
        if win is not None:
            percent = win * 100 if win <= 1 else win
            tiles.append(_tile(f"{percent:.0f}%", "Win odds"))
        roster = _dict(_dict(sections.get("my_roster")).get("structuredContent"))
        record = _str(roster.get("record"))
        if record:
            tiles.append(_tile(record, "Record"))
        if tiles:
            card["data"]["tiles"] = tiles
    return _finish(card, feed, ctx)


def _moon_slug(name: str) -> str:
    return "_".join(name.lower().replace("-", " ").split())[:MOON_MAX]


def _degrees(value: object) -> str | None:
    number = _number(value)
    return None if number is None else f"{round(number)}°"


def almanac(feeds: dict[str, Feed], ctx: Context) -> Card:
    """Temperature, a 4-day strip, sunrise/sunset and the moon phase."""
    feed = feeds["almanac"]
    card = _skeleton("almanac", "Almanac", "edition")
    if feed.usable:
        sections = feed.sections()
        tiles = []
        current = _dict(sections.get("now"))
        if (temp := _degrees(current.get("temperature_2m"))) is not None:
            # "Now" would lie once the reading ages; label it with the time it was taken.
            clock = local_clock(current.get("time"))
            tiles.append(_tile(temp, f"At {clock}" if clock else "Latest"))
        today = _dict(sections.get("today"))
        for key, label in (("sunrise", "Sunrise"), ("sunset", "Sunset")):
            if clock := local_clock(today.get(key)):
                tiles.append(_tile(clock, label))
        if tiles:
            card["data"]["tiles"] = tiles[:TILES_MAX]

        days = []
        for day in map(_dict, _list(sections.get("four_day"))[:4]):
            try:
                name = date.fromisoformat(_str(day.get("date"))).strftime("%a")
            except ValueError:
                continue
            low, high = _degrees(day.get("temp_min_c")), _degrees(day.get("temp_max_c"))
            if low and high:
                days.append(f"{name} {low.rstrip('°')}\N{EN DASH}{high}")
            elif high:
                days.append(f"{name} {high}")
        if days:
            card["data"]["rows"] = _rows([(" · ".join(days), None)])

        moon = _str(_dict(sections.get("moon_phase")).get("name"))
        if moon:
            card["data"]["moon"] = _moon_slug(moon)
    return _finish(card, feed, ctx)


def waiting(feeds: dict[str, Feed], ctx: Context) -> Card:
    """What the owner owes: the digest's open decisions, as rows."""
    digest = feeds["digest"]
    card = _skeleton("waiting", "Waiting on you", "dex")
    if digest.usable:
        decisions = digest.sections().get("decisions")
        if isinstance(decisions, list):
            rows = _rows((_str(item), None) for item in decisions)
            if rows:
                card["data"]["rows"] = rows
                count = len(rows)
                card["body"] = f"{count} thing{'s' if count != 1 else ''} waiting on you."
            else:
                card["body"] = "Nothing is waiting on you."
    return _finish(card, digest, ctx)


def _wire_items(feed: Feed) -> list[tuple[str, str | None]]:
    if feed.spec.name == "paper-feed" and feed.payload:
        # Only the reading pile goes on a glanceable ticker; `life` mail is personal.
        items = []
        for mail in map(_dict, _list(feed.payload.get("reading"))):
            sender = _str(mail.get("from")).split("<")[0].strip().strip('"')
            items.append((_str(mail.get("subject")), sender or None))
        return items
    if feed.spec.name == "radar":
        saves = map(_dict, _list(feed.sections().get("saves")))
        return [(_str(save.get("title")), "Radar") for save in saves]
    return []


def wire(feeds: dict[str, Feed], ctx: Context) -> Card:
    """The ticker: the reading pile's headlines plus the radar's saves.

    Fresh desks fill the wire. A stale desk is left off while any fresh desk has items, and the
    footer says so; if nothing fresh has items, the stale items run with the stale label.
    """
    sources = [feeds["paper-feed"], feeds["radar"]]
    card = _skeleton("wire", "The Wire", "edition")
    with_items = [f for f in sources if f.usable and _wire_items(f)]
    chosen = [f for f in with_items if f.state is State.FRESH] or with_items
    if not chosen:
        # Nothing to run. A desk that filed (but had no items) beats a failed one, which beats
        # a missing one; ties go to the primary desk.
        rank = {State.FRESH: 0, State.STALE: 1, State.FAILED: 2, State.MISSING: 3}
        return _finish(card, min(sources, key=lambda f: rank[f.state]), ctx)

    card["data"]["rows"] = _rows(item for f in chosen for item in _wire_items(f))
    if any(f.state is State.STALE for f in chosen):
        card["stale"] = True
    # Say why the rows are stale first; otherwise name a desk that was left off.
    ordered = sorted(sources, key=lambda f: f not in chosen)
    notes = [trouble_note(f, ctx) for f in ordered if f.state is not State.FRESH]
    if notes:
        card["footer"] = notes[0]
    card["created_at"] = iso(max(f.generated_at or ctx.now for f in chosen))
    deadlines = [f.fresh_until for f in chosen if f.fresh_until is not None]
    if deadlines:
        card["fresh_until"] = iso(min(deadlines))
    return card


BUILDERS: dict[str, Callable[[dict[str, Feed], Context], Card]] = {
    "masthead": masthead,
    "one_thing": one_thing,
    "sports": sports,
    "almanac": almanac,
    "waiting": waiting,
    "wire": wire,
}


def edition(feeds: dict[str, Feed], ctx: Context) -> list[Card]:
    """All six edition cards, in the protocol's section order."""
    return [BUILDERS[section](feeds, ctx) for section in SECTIONS]
