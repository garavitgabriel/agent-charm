# Coach Beard on the charm — plan

> **Coach is optional.** He's the worked example of giving the charm a second agent with its own
> body, voice and history. The server keeps him off unless `COACH_ENABLED=1`:
> - with `CHARM_AGENT=openai`, he's the same endpoint with his own persona (and `COACH_MODEL`, if
>   you want a different model);
> - with `CHARM_AGENT=hermes`, he's a second Hermes profile (`COACH_ENV_PATH`, `COACH_PORT`), with
>   an optional read-only decision ledger for the fast path (`COACH_LEDGER_PATH`).
>
> The rest of this page is the original plan, kept for the design reasoning.

Status: **planned 2026-09-28**, approved by the owner. It starts after the VPS move.
Reference: [`coach/coach-reference.jpg`](coach/coach-reference.jpg). An AI-generated pixel image on a
fake checkerboard background (it's a JPEG with no transparency). **It's a reference only:** Coach is
redrawn smooth, in Dex's style.

## What it is

The charm gets a second character. **Coach Beard** is the `coach` Hermes profile: fantasy football
research, a second opinion from a fantasy-analysis tool, and start/sit calls. Ask "Coach, …", or ask something clearly
about fantasy or the NFL, and Coach answers, in his own body, voice and conversation history.
Everything else still goes to Dex.

## Design: the same system, a different character

The design system stays exactly as it is: § 11 tokens, layout, motion, the separator and the anchor,
one gold accent meaning "you can act", no boxes and no clock. **The character is the identity
cue,** so there's no name label; the kill list already bans eyebrow labels. Coach follows the
**character-swap contract (BRIEF § 11.7)**:
- the same pose list for the surfaces he uses;
- the same footprint (a 192×224 cell, hip at 236,379, scale 0.62);
- hands that hold props;
- a night palette.

The only fantasy-specific changes:

1. **His props replace Dex's on active screens.**
   - Listening: a hand to his headset.
   - Working: studies the calendar or tablet ("watching film").
   - His call: points at the circled date on the calendar, or blows the whistle.
   - Done: a thumbs-up with the whistle.
   - Asleep: seated, beanie pulled down.
   - Offline: taps a dead headset.
2. **Two Coach-only surfaces:**
   - **"Coach is on it."** A walk-away working state. His answers take about 3 minutes (measured:
     167 s), so the charm lets you put it down; Dex's Working screen assumes a few seconds.
   - **"Coach's call."** The start/sit verdict (one line, 32 px), the deadline in local time, and
     the flip condition ("Flip only if Purdy is out before Sun 12:00"). The actions are *Got it* /
     *Why?*. It reuses the Decision layout.
3. **Watch the accent.** His orange jacket and beanie sit close to the gold `#F2C14E`. § 11.7 rule 5
   says the character's colours must not collide with the accent. The design session tests it and
   adjusts his orange toward burnt or rust, or leans on the navy, if the gold stops reading as "you
   can act".

Coach never uses the money screens: he never orders, and his Hermes config can't. There's no
reading mode for him either.

## Backend: how the charm reaches Coach

Facts, checked 2026-09-28:
- `coach` runs its own s6 gateway (its own chat channels).
- **His API server isn't enabled.** Only Dex's `/opt/data/.env` carries `API_SERVER_KEY`.
- His config **enforces** a read-only toolset on every platform, including `api_server`: `web`,
  `skills`, a fantasy-data tool and `coach_local`, with `file`/`terminal`/`code_execution`/… disabled.
  That's stronger than Dex's behavioral "read, don't act".
- `hermes -p coach -z "<question>"` (docker exec) works today with no Hermes change. One live
  lineup question took **167 s** and gave a correct, in-character answer.

Two options:
- **A: CLI transport,** with no Hermes change. A cold start per question, and no streaming.
- **B (recommended): turn on Coach's API server** (`API_SERVER_KEY` + its own port in the `coach`
  profile `.env`, then a gateway restart). That gives the same persistent, streaming channel as Dex.
  **This is a Hermes config change, so it needs the owner's explicit OK.**

## Build round (one round, three builders, after the Coach design lands)

| Builder | Scope |
|---|---|
| Server | Routing: the "Coach, …" wake word plus clear fantasy/NFL intents (EN/ES) go to coach, everything else to Dex. Per-agent persona, history, TTS voice and `state.agent`. A **walk-away job**: immediate `state{working, agent:"coach", label:"Coach is on it"}`, then a `card` + `attention` when he's done, and speech only when the owner looks (no pings). A **fast path**: "What's Coach's latest call?" answers in seconds from his decision ledger / `coach-today` output instead of a fresh 3-minute run. Transport A or B behind one interface. |
| Sprites | A character dimension, (dex \| coach) × pose × outfit, in `dex_sprite.h` (a chief contract change before the round). Export Coach's frames from the design source. A budget report (~30–40 frames, ~400 KB LZ4; firmware flash is 31 % today). |
| UI | Character switching (the separator stays; the character crossfades at the anchor). The "Coach is on it" and "Coach's call" surfaces. Start/sit cards. |

Protocol additions (chief, before the round): `mode{..., agent}` / a `character` field; a `call`
card (a decision variant with `data.flip_if`); `job` cards reused for "on it".

## Order

1. Move the charm server to the VPS (next to Hermes, Coach and the notes service).
2. The owner decides A vs B.
3. A Coach design mini-sprint, using this brief + the reference, in the design session.
4. The build round above, then a live test on game day.
