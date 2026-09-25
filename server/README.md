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
                        │  ├─ agent.py   Agent protocol · HermesAgent (the Margin pattern, below)
                        │  ├─ tts.py     TTS protocol · EdgeTTS (MP3 → ffmpeg → 16 kHz s16le, streamed)
                        │  └─ cards.py   schema validation, edition/pending loading, reply → say + card
                        ▼
                      protocol.py    wire constants, state/error builders, 8192/4096-byte limits
```

**The talk flow.** The server receives `audio_start` → PCM → `audio_end{released|limit}` and then
sends, in order: `state{transcribing}` → `transcript{final}` → `state{working, agent:"dex"}` →
`card{answer}` → `state{speaking}` → `speech_start{card_id}` → PCM → `speech_end` → `state{idle}`.

- The reply is stripped of markdown. The first two sentences are spoken. The card body holds up
  to 60 words (and 420 characters); when it's cut, a `footer` says so ("Shortened. Ask Dex for the
  rest."). It doesn't claim the rest went to Telegram, because nothing is sent there. The card's
  title is the question.
- Speech starts as soon as Edge's first MP3 chunk is decoded. It's paced at real time plus a 1 s
  lead, so the device's ring buffer never overflows, in frames of 4096 bytes or less.
- Each connection keeps its own conversation context (the last 8 question/answer pairs). A
  cancelled question isn't added.

**Errors.** `too_short` (<0.5 s or silent), `no_speech` (empty transcript), `agent_timeout` (120 s),
`agent_error`, `busy` (`audio_start` while a job runs) and `audio_format` (bad `audio_start` fields
or an oversized/odd binary frame). Each is followed by `state{idle}`. If TTS fails before any
audio, the card stays up without speech. If it fails midway, the server sends `speech_end` early.

**Cancel.** A `cancel` kills the running job (the SSH process to Hermes included), sends
`speech_end` if it was speaking, then `state{idle}`. The late answer is never sent.
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

`HermesAgent` follows Margin's `bridge.py` (provenance in `agent.py`): `ssh hermes docker exec -i
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
| agent | working → card |
| tts | card → `speech_start` |
| first audio | until `speech_start` |
| total | until `speech_end` |

The server logs its own `talk timings` line. Exit codes: 0 ok, 1 the server sent an error, 2 bad
token, 3 unreachable.

## Live smoke run (2026-09-25, Mac → VPS)

`charm-client --say "What is the difference between a metaphor and a simile?"`:

| Stage | Time |
|---|---|
| stt | 0.74 s |
| agent | 11.16 s |
| tts (to first audio) | 5.11 s |
| total (to `speech_end`, 9.8 s of speech) | 25.74 s |

Edge's own first chunk takes 3–7 s from here. Streaming the decode cut TTS-to-first-audio from
12.45 s to 5.11 s.
