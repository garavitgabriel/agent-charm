# Fixture scrubbing

**The committed fixtures are synthetic.** `fixtures/raw/` keeps the *shape* of one real pull of each
feed (2026-09-25, ~17:20 UTC), which went through `charm-feeds scrub`; every free-text field
(digest and radar lines, reading-pile subjects, links, the team and city names) was then replaced
with invented content, so nothing in them is from a real inbox, league or project. The public NFL
players, teams and injury notes in `sports.json` are kept as-is.

What follows describes `charm-feeds scrub` (`src/charm_feeds/scrub.py`), which you should run on
any pull of your own before committing it. The code is the source of truth; this file says what
it removes. `tests/test_scrub.py` sweeps every committed fixture (raw and cards) for leaks.

`spend-pulse.json` was never pulled and has no fixture: finance data stays on the VPS.

## Removed from every feed

| What | Replaced with |
|---|---|
| Email addresses | `redacted@example.invalid` |
| URL query strings and fragments (where tokens and tracking IDs live) | the bare URL |
| Token-shaped strings (`sk-…`, `ghp_…`, `xox…`, JWTs) | `[token]` |
| Phone numbers | `[phone]` |
| Money amounts (`$49`, `51.300 COP`, …) | `[amount]` |
| Digit runs of 7 or more (account, ticket and league IDs) | `[number]` |
| The bank's name | `[bank]` |

## Per feed

- **paper-feed** (the Gmail/Calendar sweep). This is the sensitive one.
  - The `account` address is redacted.
  - Every mail loses its `body`, `id`, `thread_id` and `gmail_url`.
  - Every `from` is replaced: `[sender]` in the reading pile, since display names are often a
    person's name, and `[personal sender]` in `life`.
  - `life` subjects become `[personal mail]`; they're bank, delivery and account notices.
  - Reading-pile subjects stay. They're public newsletter headlines, and the wire is built from them.
  - Calendar events keep only their times; the summary becomes `[event]`, and attendees, location and
    description go. The pull had no events.
- **sports** (Coach Beard's fantasy desk):
  - The league name becomes `Sample League`, and `league_id` becomes `"0"`.
  - Other managers' team names become `Team N`, everywhere they appear.
  - `owner` fields become `null`.
  - The power-ranking headlines become `[headline]`, because they name teams by nickname.
  - The FAAB budget note becomes `[amount]`.
  - Each `text` field (a JSON dump duplicating its `structuredContent`) is dropped.
  - Kept: your own team name, and the public NFL players and reporters in the injury notes. They
    are the content, and public.
- **digest**, **radar**, **almanac**: the global rules only. Radar keeps its public GitHub and blog
  links, which carry no tokens. The almanac keeps the city.

## Regenerating

```sh
uv run charm-feeds pull                    # into the gitignored .cache/
uv run charm-feeds scrub --dst fixtures/raw
uv run charm-feeds build --src fixtures/raw --out fixtures/cards --now 2026-09-25T17:30:00+00:00
```

Read the diff before committing. The leak sweep catches patterns, not meaning.
