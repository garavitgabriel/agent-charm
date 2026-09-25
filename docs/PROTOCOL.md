# Dex Charm protocol — v0

The one contract between the **device** (firmware, or the Mac simulator standing in for it), the
**charm server** and the **feeds → cards** builder. Owned by the chief session. Builders code against
it and never edit it: if it's wrong or missing something, write a blocker note.

Machine-readable pieces:
- [`contract/card.schema.json`](../contract/card.schema.json): JSON Schema for a card.
- [`contract/examples/`](../contract/examples/): one valid example per card kind.

## Transport

- A **WebSocket** at `ws://<host>:8765/charm`. Later, `wss://` on the VPS.
- **Text frames** carry one JSON object each, with a required `"type"` string.
- **Binary frames** carry raw audio only: PCM **s16le, mono, 16 000 Hz**. Their meaning comes from the
  most recent `audio_start` (device → server) or `speech_start` (server → device).
- Binary frames are at most **4096 bytes** each, which is 128 ms of audio.
- Text frames are at most **8192 bytes** UTF-8.
- One device per connection. The server may hold several connections, but v0 assumes one.

## Auth

The first frame from the device must be `hello` with a `token`. The server compares it against the
`CHARM_TOKEN` environment variable. If it's wrong or missing, the server sends
`error {code:"auth"}` and closes with code 4401. The token lives in the device's gitignored
`secrets.h` and in the server's environment, **never in the repo**.

## Device → server

| type | fields | meaning |
|---|---|---|
| `hello` | `device_id`, `fw`, `token`, `caps: string[]` (e.g. `["mic","speaker","imu"]`) | First frame |
| `audio_start` | `rate:16000`, `format:"s16le"`, `channels:1` | Hold-to-talk began. Binary frames follow |
| `audio_end` | `reason: "released" \| "limit" \| "cancel"` | Talk ended. `cancel` means discard the audio |
| `cancel` | — | Abort the current job (transcribe, think or speak) |
| `action` | `card_id`, `action` (an `id` from the card's `actions`), `held_ms?` | The user pressed a card button. `held_ms` is reported for hold actions |
| `request` | `what: "edition" \| "pending" \| "status"` | Pull cards (e.g. on pick-up, or a swipe to the edition) |
| `displayed` | `id` (a card id) | Render acknowledgment. Only the device's receipt counts as "shown" |
| `event` | `name: "face_down" \| "face_up" \| "pickup" \| "shake" \| "battery"`, `value?` | Motion or power events |
| `ping` | — | Keepalive every 10 s |

## Server → device

| type | fields | meaning |
|---|---|---|
| `welcome` | `server`, `time` (ISO-8601), `tz` | Auth accepted |
| `state` | `value`, `label?`, `agent?` | Drives Dex's pose. `value` is one of the states below |
| `mode` | `value: "default" \| "gameday" \| "reading" \| "food" \| "code" \| "cat"` | Outfit/prop for Dex |
| `transcript` | `text`, `final: bool` | What the server heard |
| `card` | `card` (see schema) | Show or replace a card (same `id` = replace) |
| `dismiss` | `card_id` | Remove a card |
| `speech_start` | `rate:16000`, `format:"s16le"`, `channels:1`, `card_id?` | Binary speech frames follow |
| `speech_end` | — | Speech finished (also sent after a `cancel`) |
| `error` | `code`, `text` | Human-readable; the device shows it honestly |
| `pong` | — | Reply to `ping` |

**`state.value`:** `idle`, `listening`, `transcribing`, `working`, `speaking`, `attention` (a card is
waiting), `done` (the backend **confirmed** something), `error`, `offline`.

`offline` is **never sent by the server**. The device enters it on its own when the socket is down.
The same goes for `listening`: the device shows it only while its mic is actually capturing. The
server's `listening` state is an echo, not a command.

## Flows

**Talk:**
```
device: audio_start → [binary PCM…] → audio_end{reason:"released"}
server: state{transcribing} → transcript{final:true} → state{working, agent:"dex"}
        → card{kind:"answer"} → speech_start → [binary PCM…] → speech_end → state{idle}
device: displayed{id}
```
The spoken reply is **at most 2 sentences**; the card is at most ~60 words. When the full answer is
longer, the card's `footer` says where the rest went ("Full version in Telegram").

**Decision:** the server pushes `card{kind:"decision"}`. The device sends
`action{card_id, action:"approve"|"reject"|"snooze"}`. The server confirms with `state{done}`, then
`dismiss`. There is no ✓ before the confirmation.

**Money (hold to confirm):** the server pushes `card{kind:"money"}` whose confirm action carries
`hold_ms: 2000`. The device sends that action **only after a continuous 2000 ms hold**, and reports
`held_ms`. The server rejects any confirm with `held_ms < hold_ms`. In v0, money cards come only from
fixtures; nothing real is ordered (see BRIEF § 10).

**Edition:** the device sends `request{what:"edition"}`. The server sends a `card{kind:"edition"}` for
each section, in order: `masthead`, `one_thing`, `sports`, `almanac`, `waiting`, `wire`.

**Cancel:** a `cancel` at any point stops transcription, thinking and speech. The server sends
`speech_end` if it was speaking, then `state{idle}`. A late answer to a cancelled job is dropped,
never shown.

## Errors (codes)

| code | when |
|---|---|
| `auth` | Bad or missing token |
| `audio_format` | Unsupported `audio_start` fields |
| `too_short` | Less than 0.5 s of audio, or silence |
| `no_speech` | Transcription was empty |
| `agent_timeout` | Dex didn't answer within 120 s |
| `agent_error` | Dex returned an error |
| `busy` | A job is already running |
| `stale` | Requested data exists but is past its `fresh_until` date (for cards, stale is shown inside the card instead) |

## Clarifications — 2026-09-25 (chief rulings after batches 3 and 4)

These are additive; nothing breaks. The device and UI must treat them as the contract.

1. **A short money hold** is answered with `error{code:"too_short"}`, and the card stays in place.
2. **After any error**, the server sends `state{idle}` (not `state{error}`). The device shows the error
   text; `state{error}` is reserved for a device-side failure.
3. **Speech order:** `state{speaking}` comes before `speech_start`.
4. **A confirmed sample (fixture) money order** is replaced by a `notice` card ("Sample order: nothing
   was charged"). No ✓ is shown, because nothing real happened.
5. **Truncated-answer footer:** "Shortened. Ask Dex for the rest." Never "Full version in Telegram"
   unless something was actually sent to Telegram.
6. **An `action` on a card id this connection never received** is answered with `dismiss{card_id}`.
7. **Edition cards may carry `stale: true` plus a footer** like "<Desk> desk missed deadline — last
   filed <when>", and a failed desk yields a card with only that wording. `edition_no` is optional and
   omitted when no feed provides it.
8. **Decision cards need structured pending items.** No Dex feed publishes those yet (id, default,
   deadline). Until one does, pending items appear as rows on the `waiting` edition card, with no
   action buttons. A structured `pending[]` feed on the Hermes side is a follow-up.

## Versioning

This is v0. The protocol version travels in `hello.fw` and `welcome.server` (e.g. `"charm-server/0.1 proto/0"`).
A breaking change bumps the `proto/N` number and gets a note here.
