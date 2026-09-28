# notes — reading notes store ("save this thought")

Saves your **verbatim** thoughts, with book/chapter context, to a notes-vault inbox via an HTTP
knowledge service, "the OS knowledge service" below (`POST /submit` → `inbox/<date>-charm-<slug>.md`,
new file only). You don't need it to run the charm: the server's default note store
(`CHARM_NOTES=file`) writes the same Markdown files to a local folder.
The charm server depends on this package through the `NoteStore` interface in
`src/charm_notes/__init__.py` (a chief-owned contract, like `docs/PROTOCOL.md`).

## Stores

| Store | Module | Use |
|---|---|---|
| `FakeNoteStore` | `charm_notes` (contract) | tests, `CHARM_NOTES=fake` demos |
| `OsApiStore` | `charm_notes.osapi` | the real vault inbox, through the OS knowledge service |

```python
from charm_notes.osapi import OsApiStore

store = OsApiStore()            # resolves config (below); a missing config is not an error here
receipt = await store.save(note)  # SaveReceipt(ok=True, where="inbox/…") or ok=False + error
```

`OsApiStore` behaviour:

- **One request per save, no automatic retries.** The service creates a new file on every submit,
  so a retry after a lost reply could duplicate the note. The caller decides whether to ask again.
- `POST {OS_API_BASE}/submit` with JSON `{filename, content, agent: "charm"}` and
  `Authorization: Bearer <token>`. Transport is stdlib `urllib` (no extra dependency), 10 s timeout,
  run off the event loop. Redirects are **not** followed (they would resend the token elsewhere).
- **`ok=True` only on 2xx with a non-empty `path`** in the reply (the service answers
  `{"ok": true, "path": "inbox/…"}`); `where` is that vault path. Anything else is
  `ok=False` with a human reason:

  | Situation | `error` |
  |---|---|
  | no config | `vault service config not found` |
  | connection refused / DNS / network | `vault service unreachable` |
  | no reply within the timeout | `vault service timed out` |
  | 401 | `vault service rejected the token (401)` |
  | 403 | `vault service refused the write (403)` |
  | 5xx | `vault service error (<status>)` |
  | other non-2xx (incl. 3xx) | `vault service returned HTTP <status>` |
  | 2xx without a usable `path`, or not JSON | `vault service gave a malformed reply` |

  A timeout is still "not saved" as far as the charm is concerned, even though the service *may*
  have written the file. The charm never shows Saved without the receipt.
- **The token is never logged, printed, or put in a receipt or repr.** Tests assert this, including
  against a service that echoes the token back.

### Config

This follows the same resolution order as the service's `os` command-line client:

1. Env `OS_API_BASE` and `OS_API_TOKEN` (env wins, per variable).
2. Otherwise the first file that exists: `$OS_API_CONFIG`, then `~/.os-api.env`, then
   `/etc/os-api.env`. It's a shell env file: `KEY=value` lines, where `export` and quotes are OK.

These files hold a secret and live outside git. This package never creates or copies them.

## Note file format

This is what `/ingest` in the vault can route on. The service stores it as
`inbox/<YYYY-MM-DD>-charm-<slug>.md`. The charm sends `filename` = a slug of the
thought's first 6 words (`foxes-win-because-they-change-their.md`). The service adds the date and
agent prefix, and a `-2`, `-3`… suffix instead of ever overwriting.

```markdown
---
title: "Foxes win because they change their minds."
type: reading-note
created: 2026-09-27T18:40:00-05:00
source: dex-charm
book: "Superforecasting"
author: "Philip Tetlock"
chapter: "3"
language: "en"
tags: [reading, charm]
---

> Foxes win because they change their minds.
```

- **Frontmatter:**
  - Every key is always present.
  - `book`, `author` and `chapter` are `null` when unknown (a thought outside reading mode has all
    three `null`).
  - Strings are double-quoted YAML (JSON-escaped), so quotes, colons and accents are safe.
  - `title` is the thought's first 8 words, with `…` if it was longer.
  - `created` is the capture time as ISO 8601 with its UTC offset.
  - `type: reading-note`, `source: dex-charm` and `tags: [reading, charm]` are constant, so these
    are the routing keys.
- **Body:**
  - The body is the thought, **verbatim**, as a markdown blockquote: each line is prefixed `> `, and
    empty lines become `>`.
  - Nothing is generated, summarized or added. Strip the quote prefix and you get the speaker's exact
    words back.

## CLI

```sh
uv run charm-notes save "text" [--book T] [--author A] [--chapter C] [--language en] [--dry-run]
uv run charm-notes check [--base http://<service-host>:8088]
```

- **`save --dry-run`** prints the exact file it would submit (plus a `# dry run:` header line with
  the filename) and sends nothing.
- **`save`** does one real submit. It prints `saved: <vault path>` only on a confirmed receipt;
  otherwise it prints `not saved: <reason>` and exits 1.
- **`check`** writes nothing. It reports whether config was found (and where from, **never the
  token**), then calls the unauthenticated `GET /health`. It exits 0 only when config is found
  **and** the service is healthy. `--base` lets you check health without config.

## Checks

```sh
uv run ruff check . && uv run mypy src && uv run pytest -q
```

The tests run against a local fake HTTP server (`tests/fake_service.py`). They never touch the real
service or vault.
