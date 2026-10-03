# A status
branch: track/a · last commit: see `git log -1 track/a` (status commit follows 8413d6c) · rung reached: unit (device: deferred to chief)

## Done
- `server/src/charm_server/http_api.py`: the HTTP API v1 per `docs/HTTP.md`. aiohttp app in the
  same process, sharing `Deps`. One `Session` per device id, `send_raw` → per-device event log
  (`seq`, last 200), binary speech between `speech_start`/`speech_end` cut into WAV clips
  (published at ≥ 1.5 s or at `speech_end`, `speech_clip` events with `seq_in_speech`, `ms`,
  `card_id`). Clips: 20 most recent or 10 min per device, served only to their own device.
- Endpoints: health (no auth), hello, turns, actions, requests, cancel, events (long poll, one
  waiter per device, reset on stale cursor, cursor past the end = the end), speech. Errors are
  the contract's JSON `{code, text}` (401/400/404 no_session|not_found/409/413/415).
- Turns go through `Session.handle_text(audio_start)` → `handle_binary` (4096-byte frames) →
  `handle_text(audio_end{released})`; actions/requests/cancel through `handle_text`. No turn,
  money, Coach, reading or notes logic duplicated. Sessions use
  `replace(deps, speech_lead_s=None)`.
- Config `CHARM_HTTP_PORT` (8766, 0 disables) + `CHARM_HTTP_SESSION_TTL` (3600) in `config.py`
  and `.env.example`; started/stopped in `server.run` next to the WS server.
- `aiohttp==3.14.3` pinned (already in the lock transitively; `uv lock` adds the direct edge).
- `tests/test_http_api.py`: 59 tests against a real aiohttp server + real `Session` with the
  conftest fakes. Covers every item in A.md's test list plus TTL expiry, per-device isolation,
  re-hello mid-turn, multi-clip cutting, chunk-walking WAV parser.
- Verification: `cd server && uv run pytest -q && uv run ruff check . && uv run mypy src` → exit 0,
  484 passed (425 before + 59 new).

## Session seam
- `Session.open()`: the hello greeting (`welcome`, state, `greet()`), lifted out of
  `server.handle` so WS and HTTP share it. On a live session that's busy it reports
  `last_state`, never `idle`. `greet()` now detaches its Coach listener before attaching, so a
  repeated hello doesn't register twice. WS behaviour unchanged (all 425 tests pass).

## Not done
- Nothing from A.md's list.

## Could not verify
- Live run of `charm-server` with the HTTP port open (needs Whisper + an agent); covered only by
  `http_api.start()` in tests. Funnel path `/charm-api` and VPS deploy: chief.
- Real Watch `AVAudioRecorder` WAVs (header layout): the parser walks RIFF chunks and tolerates an
  overstated data size, but no real file was tested. Device verification deferred to chief.

## Interpretations
- "Pending cards" in the hello greeting = what the WS greeting already sends (`greet()`: Coach
  jobs/results, reading mode). It does not run `request pending`; the client asks for that.
- Unauthenticated requests to any path but `/v1/health` get 401 before any 404 (no path probing).
- `wait` is clamped to 0–25 s; non-numeric/NaN `wait` or negative/non-int `after` → 400.
  `after` defaults to 0 when missing.
- Empty poll responses (timeout or superseded) return `cursor = min(after, end)`, so a client can
  never skip an event.
- Content types `audio/wav`, `audio/x-wav`, `audio/wave` are all accepted; anything else → 415.
- Over the body limit (27 s of PCM + 64 KB of RIFF slack) → 413 without reading; between 27 s of
  PCM and that → read, then 413. Over-limit audio is never silently cropped.
- Expired sessions answer 404 `no_session` immediately, even before the sweeper removes them; a
  device with a waiting poll is never swept.
- 405 for wrong methods uses `{code: "bad_request"}` (not in the contract's table).
- `turn_id` is an opaque id for the client; events don't carry it (the contract doesn't add it).

## Asks for the chief
- HTTP.md could state that `speech_clip.url` is relative to the base URL (behind the Funnel the
  client must prefix `/charm-api`). The implementation emits `/v1/speech/<id>.wav` as written.
- Consider whether hello should also replay pending cards (`request pending`) — ARCHITECTURE § 4
  says "replays current pending cards"; I followed HTTP.md's "same greeting as the WebSocket".

## Friction / gotchas
- `hello`'s cursor is before the greeting, so the greeting's `state:idle` is the first idle a
  client sees; tests drain it before waiting for a turn's idle.
