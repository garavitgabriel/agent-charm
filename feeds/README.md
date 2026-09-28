# feeds: Dex's desk feeds → charm cards

`charm-feeds` reads the structured desk feeds Dex already publishes for the evening paper and turns
them into the six pocket-edition cards (`contract/card.schema.json`, `kind: "edition"`). The output
directory can be used directly as the server's `CHARM_CARDS_DIR`.

## Commands

```sh
cd feeds
uv sync

uv run charm-feeds pull                       # read-only copy from Hermes into .cache/ (gitignored)
uv run charm-feeds build --out ../out/cards   # 01-masthead.json … 06-wire.json
uv run charm-feeds scrub --dst fixtures/raw   # only when refreshing fixtures; see fixtures/SCRUBBING.md

uv run ruff check . && uv run mypy src && uv run pytest -q
```

`build` options:

| Option | Default | Meaning |
|---|---|---|
| `--src DIR` | `.cache/` | Directory of pulled feeds. |
| `--now ISO` | the current time | Time to judge freshness at. It needs an offset. |
| `--tz ZONE` | `$CHARM_TZ`, else `UTC` | Zone for the weekday and "last filed" stamps. |
| `--schema FILE` | `../contract/card.schema.json` (or `CHARM_CARD_SCHEMA`) | Card schema to validate against. |

Every card is validated before anything is written. A build then replaces the `NN-*.json` files
it owns in `--out` (other files are left alone), so a card that no longer applies can't linger.

`pull` options: `--ssh-alias` (`HERMES_SSH_ALIAS`, default `hermes`), `--container`
(`HERMES_CONTAINER`, default `hermes-agent`), and `--cache`.

## Read-only pull

`pull` runs exactly one remote command per feed:
`ssh hermes docker exec -i <container> cat <path>`. The paths are an allowlist (`sources.FEEDS`):

- `/opt/data/board/feeds/{sports,almanac,digest,radar}.json`
- `/opt/data/board/paper-feed.json`

`spend-pulse.json` is refused by name and never requested. Nothing is written on the VPS.

A failed pull (ssh error, or a reply that isn't JSON) leaves the previous cached copy untouched and
exits 1. The next build shows that old filing, labeled stale once its deadline passes.

## Freshness and honesty

This follows the rule Dex's own board uses (`build-daily-board-payload.js`, `freshFeed`).

| Feed state | What decides it | Card |
|---|---|---|
| fresh | `status != "failed"` and `now < fresh_until` | Content. `fresh_until` is carried over, and `created_at` is the desk's `generated_at`. |
| stale | `now ≥ fresh_until`, no `fresh_until` at all, or non-empty `errors` | Same content, plus `stale: true` and a footer: "Sports desk missed deadline — last filed Fri 08:31" (or "filed with errors"). |
| failed | `status: "failed"`, no readable `generated_at`, or an unreadable file | **No content.** The body is the same wording, with `stale: true`. |
| missing | The file was never pulled | **Honest-empty:** "No filing from the sports desk yet." No rows, no tiles, no `stale`. |

A usable feed that has nothing for a section gives "The digest desk filed nothing for this
section." The builder never fills a gap with made-up content.

`paper-feed.json` publishes no `fresh_until`. Its sweep window is `newer_than:1d`, so it counts as
fresh for 24 h after `generated_at`.

## Feed → card mapping

| Section (card `id`) | Source | Mapping |
|---|---|---|
| **masthead** (`ed-masthead`, source `edition`) | digest + every desk's state | Title `"<Weekday> edition"` (build time, `--tz`). `body` = `digest.summary_line` (tonight's verdict). `rows` = one per desk: `"Sports desk · filed / missed deadline / failed / no filing"`, stamped with its filing time. `tiles` = `"N of 5" / "Desks fresh"`. `stale` follows the digest. `fresh_until` = the earliest deadline among fresh desks, because that's when the rows stop being true. |
| **one_thing** (`ed-one_thing`, source `dex`) | digest | `body` = `digest.telegram_line`, Dex's own line naming what comes first. |
| **sports** (`ed-sports`, source `coach`) | sports | `body` = `summary_line` (falling back to `sections.today.say`). `rows` = up to 3 `sections.today.do_now[]`: `text` = `headline`, `stamp` = `deadline`. `tiles` = `numbers.projected_points` "Projected", `numbers.win_probability` "Win odds" (when not null), `my_roster.structuredContent.record` "Record". |
| **almanac** (`ed-almanac`, source `edition`) | almanac | `tiles` = `now.temperature_2m`, labeled **"At HH:MM"** from `now.time` (never "Now", since the reading ages), plus `today.sunrise` and `today.sunset`. `rows` = one 4-day strip from `four_day[]`: `"Fri 13–22° · Sat 12–23° · …"`. `moon` = `moon_phase.name` as snake_case (`full_moon`). |
| **waiting** (`ed-waiting`, source `dex`) | digest | `rows` = `digest.sections.decisions[]` (what the owner owes). `body` = `"N things waiting on you."`, or "Nothing is waiting on you." when the list is empty. |
| **wire** (`ed-wire`, source `edition`) | paper-feed + radar | `rows` (at most 12, deduplicated): the subject of each `paper-feed.reading[]` mail, stamped with the sender's display name, then `radar.sections.saves[].title` stamped "Radar". Only fresh desks run while any fresh desk has items; a stale desk is left off and named in the footer. If nothing fresh has items, the stale items run with `stale: true`. `life` mail (bank, delivery and account notices) never goes on the ticker. |

All strings are cleaned of markdown and emoji, which the device font can't draw, and clipped on
word boundaries to the schema limits: body ≤ 420 characters and 60 words, rows ≤ 80, stamps ≤ 20,
footer ≤ 80, tiles 10/14.

## Gaps (what a section wants that no feed provides)

| Wanted | Status |
|---|---|
| **Decision cards** for pending one-tap items | **None produced.** No feed exposes structured pending items with an id, a default and a deadline, which `kind: "decision"` requires. `digest.sections.decisions[]` is prose ("the owner still owes…"), so it becomes `waiting` rows with no actions. Inventing a default or deadline would break the honesty rules. It needs a structured `pending[]` in a desk feed, which is a Hermes-side change this project can't make. |
| `edition_no` (masthead) | Not in any feed; left out. The paper's edition number lives only in the rendered board. |
| ✓ / ✗ / snooze on the one thing | There's no item id to act on, so the card carries no `actions`. |
| Sports: an explicit one-line verdict | The desk's `summary_line` is the closest thing; it repeats the rows. |
| A weather condition word ("drizzle") | Only numeric `weather_code`s; not mapped. |
| Wire freshness | Radar is weekly (its last `fresh_until` was 2026-09-22), so in practice the wire is the reading pile. |
| Calendar/docket | `paper-feed.events` exists but has no section on the charm. |

## Layout

```
src/charm_feeds/
  sources.py  feed allowlist + freshness state (fresh / stale / failed / missing)
  cards.py    feed → card mapping for the six sections
  build.py    build + validate + write NN-<section>.json
  schema.py   contract validation (plus an RFC 3339 check that jsonschema skips)
  pull.py     read-only ssh pull
  scrub.py    fixture scrubbing
  text.py     cleaning, clipping, time stamps
  cli.py      charm-feeds
fixtures/raw/     one scrubbed pull of each feed (see fixtures/SCRUBBING.md)
fixtures/cards/   the cards built from them at 2026-09-25T17:30Z (the digest and radar are really stale then)
```
