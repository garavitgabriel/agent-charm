# server — the Dex Charm server and `charm-client`

The server side of [`docs/PROTOCOL.md`](../docs/PROTOCOL.md). A device (the ESP32 charm, the Mac
simulator, or `charm-client`) holds a WebSocket at `ws://<host>:8765/charm`. The server hears it
(Whisper), asks Dex (Hermes, read-and-converse only), and answers with a card plus a spoken reply
(Edge TTS). It also serves the pocket edition and pending cards, and handles card buttons.

## Run it

Needs `uv`, `ffmpeg` and SSH access to the `hermes` alias (the same one Margin uses).

```sh
cd server
cp .env.example .env          # then set CHARM_TOKEN (the file is gitignored)
uv sync
uv run charm-server           # loads Whisper, then listens on ws://127.0.0.1:8765/charm
```

In another terminal, be the device:

```sh
uv run charm-client --say "What's the difference between a metaphor and a simile?"
uv run charm-client --voice Mónica --say "¿Qué diferencia hay entre una metáfora y un símil?"
uv run charm-client --wav question.m4a        # any file ffmpeg can read
uv run charm-client --mic                     # Enter to start, Enter to stop (Mac mic)
uv run charm-client --edition                 # the pocket edition, in section order
uv run charm-client --pending                 # decision / money / tracker / job / notice cards
uv run charm-client --action order-001:confirm --held-ms 2100   # hold-to-confirm (sample)
uv run charm-client --action dec-001:approve
```

`charm-server --host 0.0.0.0` exposes it on the LAN for the real device. `-v` turns on debug logs.

Checks: `uv run ruff check . && uv run mypy src && uv run pytest -q`. The tests use fake
STT/Agent/TTS engines and a localhost server. They never touch the network, Hermes or Edge.

## Environment

The real environment wins over `server/.env`. See [`.env.example`](.env.example).

| Variable | Default | What |
|---|---|---|
| `CHARM_TOKEN` | — (required) | Shared secret the device sends in `hello`. A wrong or missing token gets `error{auth}` and a 4401 close |
| `CHARM_HOST` / `CHARM_PORT` | `127.0.0.1` / `8765` | Where the server listens and where the client connects |
| `HERMES_SSH_ALIAS` | `hermes` | SSH host alias for the VPS |
| `HERMES_CONTAINER` | `hermes-agent` | The Hermes container `docker exec` targets |
| `HERMES_CHANNEL` | `1` | `1`: one persistent channel to Dex, answers streamed. `0`: the old `ssh` per question |
| `CHARM_CARDS_DIR` | `../contract/examples` | `*.json` cards for `request{edition\|pending}`. Point it at the feeds output later |
| `CHARM_SCHEMA` | `../contract/card.schema.json` | Every card is validated against it before sending |
| `CHARM_ACTION_LOG` | `.local/actions.jsonl` | Local log of card actions (gitignored) |
| `CHARM_TZ` | `America/Chicago` | `welcome.tz` and card timestamps |
| `CHARM_VOICE_EN` / `CHARM_VOICE_ES` | `en-US-AndrewNeural` / `es-CO-GonzaloNeural` | Edge voices by detected language (anything else falls back to English) |
| `CHARM_WHISPER_MODEL` | `base` | faster-whisper model |

Relative paths are resolved from `server/`.

## Architecture

```
device ──ws /charm──▶ server.py      auth (hello + token → welcome, else 4401), frame loop
                        │
                        ▼
                      session.py     one per connection: talk job, cancel, busy, requests, actions
                        │  ├─ stt.py     STT protocol · WhisperSTT (base, int8, CPU, VAD, detects language)
                        │  ├─ hermes.py  HermesChannel: one long-lived worker in the container, streamed answers
                        │  ├─ agent.py   Agent / StreamingAgent protocols · HermesAgent (ssh per question)
                        │  ├─ tts.py     TTS protocol · EdgeTTS (MP3 → ffmpeg → 16 kHz s16le, streamed)
                        │  └─ cards.py   schema validation, edition/pending loading, reply → say + card
                        ▼
                      protocol.py    wire constants, state/error builders, 8192/4096-byte limits
```

**The talk flow.** The server receives `audio_start` → PCM → `audio_end{released|limit}` and then
sends `state{transcribing}` → `transcript{final}` → `state{working, agent:"dex"}`, then the answer:
`card{answer}`, `state{speaking}` → `speech_start{card_id}` → PCM → `speech_end`, then
`state{idle}`. The message types are the same as ever, and `state{speaking}` always precedes
`speech_start`.

Dex's answer streams in, and the speech doesn't wait for it to finish:
- **Sentence 1** goes to Edge TTS the moment it's complete. Its audio streams to the device as
  soon as the first MP3 chunk is decoded.
- **Sentence 2** gets its own TTS stream, started as soon as it's complete, so it's ready by the
  time sentence 1 has played. Sentences that are already waiting when TTS starts are synthesized
  in one call.
- **The card** is sent once the whole answer is in. If that happens before the first audio is
  ready (Edge is often the slower one), the card goes first, exactly as in PROTOCOL.md's flow.
  Otherwise it arrives mid-speech. The device ignores `speech_start.card_id` and takes a card at
  any time. The card id is fixed before the speech starts, so the two always match.

Sentence splitting (`cards.sentences`) is EN/ES aware. It ignores decimals (`3.5`, `1.200`),
abbreviations (`Dr.`, `Mrs.`, `e.g.`, `U.S.`, `p.m.`, `Sr.`, `Sra.`, `EE. UU.` …) and initials
(`J. R. R.`), and never breaks before a lowercase word. While the answer is still streaming, a
sentence counts as complete only once the next word has started.

- The reply is stripped of markdown. The first two sentences are spoken, and the streamed speech
  always equals `say_text(full answer)`. The card body holds up to 60 words (and 420 characters);
  when it's cut, a `footer` says so ("Shortened. Ask Dex for the rest."). It doesn't claim the rest
  went to Telegram, because nothing is sent there. The card's title is the question.
- Speech is paced at real time plus a 1 s lead, so the device's ring buffer never overflows, in
  frames of 4096 bytes or less.
- **If Dex fails mid-answer** after the speech started, the speech ends at once (`speech_end`),
  then `error{agent_error|agent_timeout}` → `state{idle}`. No card is sent for a half answer.
- Each connection keeps its own conversation context (the last 8 question/answer pairs). A
  cancelled question isn't added.

**Errors.** `too_short` (<0.5 s or silent), `no_speech` (empty transcript), `agent_timeout` (120 s),
`agent_error`, `busy` (`audio_start` while a job runs) and `audio_format` (bad `audio_start` fields
or an oversized/odd binary frame). Each is followed by `state{idle}`. If TTS fails before any
audio, the card stays up without speech. If it fails midway, the server sends `speech_end` early.

**Cancel.** A `cancel` stops the running job: the answer stream (the worker is told to stop
reading Dex's reply, and any late lines are dropped) and every TTS stream. It sends `speech_end` if
it was speaking, then `state{idle}`. The late answer, card or audio is never sent.
`audio_end{cancel}` discards the recording.

**Requests.**
- `edition` sends the valid `kind:"edition"` cards in section order (masthead, one_thing, sports,
  almanac, waiting, wire). If there are none, it sends a notice card saying nothing was filed.
- `pending` sends the decision/money/tracker/job/notice cards, then `state{attention}`.
- `status` replies with the current state.

Invalid cards are logged and never sent.

**Actions** (only on cards sent on this connection; an unknown card id gets a `dismiss`):
- **Decision** approve/reject/snooze: logged to `CHARM_ACTION_LOG`, then `state{done}` and
  `dismiss`. There's no Hermes write in v0.
- **Money confirm:** needs `held_ms ≥ hold_ms` (and never less than 2000). A short hold gets
  `error{too_short}`, and the card stays. A full hold on a `fixture` card replaces it with a notice:
  "Sample order: nothing was charged." A non-fixture card gets "Ordering isn't wired up yet". **No
  DeliveryCo call exists in this server.**
- **Other kinds** (job, tracker, …): logged, and the card is replaced by a "Noted, v0 doesn't
  forward this yet" notice.

### Dex (Hermes): read and converse only

**The persistent channel (`hermes.py`, the default).**
- **One worker.** At server start, `HermesChannel` runs one worker in the container over the usual
  path: `ssh hermes docker exec -i <container> /opt/hermes/.venv/bin/python -u -c <worker>`. It
  warms up in parallel with Whisper, and every question reuses it.
- **Wire.** JSON lines over stdin/stdout. `{"type":"chat","id":N,"messages":[…]}` goes in;
  `delta` lines stream back while Dex writes, then `done` or `error`.
- **The key.** The worker reads `API_SERVER_KEY` from `/opt/data/.env` inside the container, as
  before, and calls the container-local `/v1/chat/completions` with `stream: true`. If the API
  answers without streaming, the whole reply comes back as one piece.
- **Not a service.** The worker is an ordinary process. It exits when its stdin closes: the server
  stopped, or the SSH link died. Nothing is installed, and there are no Hermes config, service,
  cron, skill or charter changes.

Its failure handling:
- **Drops.** SSH keepalives (`ServerAliveInterval=15`) notice a dead link. The channel then
  reconnects in the background with backoff (1, 2, 4, 8, 15, 30 s), so the next question finds it
  warm. Every request also connects on demand.
- **Retries.** A drop *before* any text arrives is retried once on a fresh worker. That's harmless,
  because Dex is converse-only. A drop *mid-answer* is an `agent_error`.
- **Timeouts.** Each request has its own 120 s deadline (`agent_timeout`), and the session enforces
  the same one around the whole answer.
- **Cancel.** A cancelled request tells the worker to stop reading that answer. Late lines for it
  are dropped.

**Per question (`HERMES_CHANNEL=0`).** `HermesAgent` follows Margin's `bridge.py` (provenance in `agent.py`): `ssh hermes docker exec -i
<container> /opt/hermes/.venv/bin/python -` runs a small script inside the container. That script
reads `API_SERVER_KEY` from the container's `/opt/data/.env` and POSTs to the container-local
`http://127.0.0.1:8642/v1/chat/completions`. The key never leaves the VPS. The charm persona asks for
conversation only (no tools, actions, messages, orders or memories), plain text, at most 60 words,
and a reply in the question's language. A system note also names the detected language. Nothing
here changes Hermes config, crons, skills or the charter.

## How `charm-client` works

It's a fake device speaking the device side of the protocol:
1. It sends `hello` (with `CHARM_TOKEN`) and waits for `welcome`.
2. It turns the input into 16 kHz s16le mono PCM:
   - `--say`: macOS `say` → AIFF → ffmpeg
   - `--wav`: any file → ffmpeg
   - `--mic`: live `sounddevice` capture
3. It streams that in frames of 4096 bytes or less between `audio_start` and `audio_end`
   (`reason:"limit"` past 25 s).
4. It prints every state, the transcript and each card (as a text box), and sends `displayed{id}`
   receipts like the device does.
5. It plays Dex's speech live through the Mac speakers (`--no-play` skips it; `afplay` is the
   fallback).

At the end it prints client-observed timings. They're measured from `audio_end`:

| Timing | Measured as |
|---|---|
| stt | until the transcript |
| agent | working → card (the whole answer) |
| tts | card → `speech_start` (negative when speech began before the answer was complete) |
| first audio | until `speech_start` |
| total | until `speech_end` |

The server logs its own `talk timings` line. It adds `agent_first` (question → the first piece of
the answer), `tts` (the first sentence ready → its first audio) and `first_audio`. Exit codes: 0 ok, 1 the server sent an error, 2 bad
token, 3 unreachable.

## Live smoke run (round 1, before streaming — 2026-09-25, Mac → VPS)

`charm-client --say "What is the difference between a metaphor and a simile?"`:

| Stage | Time |
|---|---|
| stt | 0.74 s |
| agent | 11.16 s |
| tts (to first audio) | 5.11 s |
| total (to `speech_end`, 9.8 s of speech) | 25.74 s |

Edge's own first chunk takes 3–7 s from here. Streaming the decode cut TTS-to-first-audio from
12.45 s to 5.11 s.

## Latency (2026-09-25, Mac → VPS, real Dex)

`uv run python bench/latency.py --label NAME --server-log LOG` runs 5 English and 5 Spanish
questions (`charm-client --say --no-play`, a fresh connection each) against a running server and
writes the rows plus median/p90 to `bench/results/` (gitignored). The runs below are committed in
`bench/runs-2026-09-25/`. Times are in seconds, from `audio_end`:

| | stt | agent first piece | agent (whole answer) | first audio | total |
|---|---|---|---|---|---|
| before (ssh per question, no streaming): median | 0.68 | n/a | 8.43 | **13.32** | 24.67 |
| before: p90 | 0.80 | n/a | 10.46 | **16.80** | 36.18 |
| after (channel + streaming): median | 0.65 | 3.25 | 4.37 | **7.58** | 23.08 |
| after: p90 | 0.72 | 3.73 | 5.20 | **11.06** | 27.47 |

By language, after: Spanish first audio has a median of 6.24 s (p90 7.33); English, 10.18 s
(p90 12.98).

Where the time went:
- **The channel** removes the SSH handshake, `docker exec` and Python start from every question.
  Those alone measured 3.2–4.1 s. The channel pays them once at start, taking 3.8–6.7 s.
- **Streaming** starts the speech on the first sentence, about 1 s before the whole answer is in.
  Dex's first words now arrive in about 3.3 s. Hermes does stream `delta`s.
- **Edge TTS is now the largest part.** Its first MP3 chunk takes about 1.4–2.5 s for
  `es-CO-GonzaloNeural`, but 3.2–8.9 s for `en-US-AndrewNeural`. That's why English lags.
  - A supplementary run with `CHARM_VOICE_EN=en-US-GuyNeural` gave an English first-audio median of
    **6.69 s** (p90 7.13).
  - The voice is a product choice, so the default stays Andrew. Switching is one env var.
- **What doesn't help much.** ffmpeg's decode adds about 0.1 s. Edge's TCP+TLS setup is about
  0.5 s, so pre-connecting would save at most that.
