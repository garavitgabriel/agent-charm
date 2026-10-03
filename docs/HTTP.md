# Agent Charm HTTP API — v1

The turn-based HTTP face of the bridge, for clients that can't hold a WebSocket (the Apple Watch
app first). The ESP32 keeps the WebSocket in [`PROTOCOL.md`](PROTOCOL.md). Both run in the same
process, share the same `Deps`, and apply the same rules: cards, the 2-second money hold, the
honesty rules, Coach routing, reading mode, notes.

Owned by the chief session. Builders implement against it and never edit it. If it's wrong or
missing something, write a blocker note.

## Shape

- Base URL: `http://<host>:<CHARM_HTTP_PORT>` (default **8766**). Behind the VPS Funnel it's
  `https://<funnel-host>/charm-api`; all paths below are relative to the base.
- JSON in and out (`application/json; charset=utf-8`), except audio.
- Every request but `GET /v1/health` carries:
  - `Authorization: Bearer <token>`: v1 accepts `CHARM_TOKEN`; per-device tokens are v2.
  - `X-Charm-Device: <device_id>`: 1–64 chars `[A-Za-z0-9._-]`. One server-side `Session`
    exists per device id (created on `hello`, kept for `CHARM_HTTP_SESSION_TTL` s idle,
    default 3600).
- Implementation (not visible to clients but required): each device's `Session` gets a
  `send_raw` that appends to that device's **event log**. Its `Deps` is
  `dataclasses.replace(deps, speech_lead_s=None)`, so speech isn't paced at real time.

## Errors

`{ "code": "<code>", "text": "<human sentence>" }` with:

| HTTP | code | when |
|---|---|---|
| 401 | `auth` | missing or wrong token |
| 400 | `bad_request` | malformed JSON, missing/invalid field or device header |
| 404 | `no_session` | no `hello` for this device (or it expired): the client re-hellos |
| 404 | `not_found` | unknown clip id or path |
| 409 | `busy` | a turn is already running for this device |
| 413 | `too_long` | audio over 27 s |
| 415 | `audio_format` | not `audio/wav`, or not 16 kHz / mono / 16-bit PCM |

Turn-level failures (no speech, agent timeout, too short…) aren't HTTP errors. They arrive as
`error` + `state` events, exactly as on the WebSocket.

## Endpoints

### `GET /v1/health`
No auth. `200 {"ok": true, "server": "<SERVER_ID>"}`.

### `POST /v1/hello`
Body: `{"device_id": "...", "app": "agent-charm-watch", "version": "0.1.0", "caps": ["mic","speaker"]}`
(`device_id` must equal the header).
→ `200 {"server", "time", "tz", "agent", "cursor"}`. `cursor` is the current end of the log. The
server then runs the same greeting the WebSocket `hello` triggers (`welcome`, `mode`, `state`,
Coach jobs/results, reading mode) **into the log after `cursor`**. Pending decision/money/
edition cards are **not** included: the client asks with `POST /v1/requests {"what":"pending"}`
right after hello, so the client's first `events?after=cursor`
receives them. Re-hello on an existing device keeps its session and history (an app relaunch
isn't a new conversation).

### `POST /v1/turns`
Body: the recording, `Content-Type: audio/wav`, RIFF/WAVE PCM s16le, 16 000 Hz, mono,
≤ 27 s of audio (`p.MAX_AUDIO_BYTES` + the 44-byte header). The server strips the header and
runs the same job as WebSocket `audio_start … audio_end{released}`.
→ `202 {"turn_id": "<id>"}`. Output arrives as events.

### `POST /v1/actions`
Body: `{"card_id": "...", "action": "<action id>", "held_ms": 2140}` (`held_ms` optional; required
for hold actions). Same handling as WebSocket `action`. A short money hold yields
`error{too_short}` as an event, never an order. → `202 {}`.

### `POST /v1/requests`
Body: `{"what": "edition" | "pending" | "status"}`. → `202 {}`; cards arrive as events.

### `POST /v1/cancel`
Aborts the current job, like WebSocket `cancel`. → `202 {}`.

### `GET /v1/events?after=<cursor>&wait=<s>`
Long poll. `wait` 0–25 s (default 25). Returns as soon as at least one event with
`seq > after` exists, else after `wait` seconds with an empty list.
→ `200 {"cursor": <last seq returned or the current end>, "events": [ … ]}`.
- The log keeps the last **200** events per device. If `after` is older than the oldest kept
  event, the response is `200 {"cursor": <end>, "events": [], "reset": true}` and the client
  must re-hello.
- `after` greater than the end → treated as the end.
- At most one waiting poll per device: a new poll supersedes (completes) the previous one with
  an empty list.

### `GET /v1/speech/<clip_id>.wav`
→ `200 audio/wav` (16 kHz mono s16le, with header). Clips are kept for the 20 most recent per
device or 10 minutes, whichever is shorter. Unknown/expired clip → 404.

## Events

Each event is exactly one WebSocket server→device JSON frame from `PROTOCOL.md` (`welcome`,
`state`, `mode`, `transcript`, `card`, `dismiss`, `error`, `speech_start`, `speech_end`, and
any added later), with one extra field and one extra type:

- Every event carries `"seq": <int>`, the device log's monotonically increasing sequence number
  (the cursor). Clients ignore unknown fields and unknown types.
- **`speech_clip`**: `{"type": "speech_clip", "seq", "clip_id", "card_id"?, "seq_in_speech": n,
  "url": "/v1/speech/<clip_id>.wav", "ms": <duration>}`. `url` is relative to the **base URL**
  (behind the Funnel the client requests `<base>/v1/speech/…`, i.e. with `/charm-api` in front). The binary PCM the session sends
  between `speech_start` and `speech_end` is cut into clips. A clip is closed and published
  when it reaches **≥ 1.5 s** of audio **or** at `speech_end`, so a long answer starts playing
  before it's fully synthesized. Clients play clips in `seq_in_speech` order within one
  `speech_start … speech_end` span. `speech_start` / `speech_end` events are still emitted
  around them.

## Not in v1
Per-device tokens and pairing (QR), the relay, push notifications, partial transcripts, the
`charm` MCP tool for agents. See `agent-charm-apple/docs/ARCHITECTURE.md` § 9.
