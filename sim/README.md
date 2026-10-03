# sim: the Agent Charm UI on the Mac

**To talk to Dex:** `scripts/demo.sh` from the repo root (see [`scripts/README.md`](../scripts/README.md)).
It starts the server and runs this sim as a real device: hold **space** to talk.

The shared `ui/` (LVGL 8.3.11 + ArduinoJson 7.4.2, the same code the ESP32 firmware compiles) in a
368×448 SDL2 window, plus headless screenshots and the contract tests. Visuals are **gray
placeholders**. The design sprint replaces `ui/dex_sprite.cpp` and the surface builders in
`ui/charm_ui.cpp`.

## Build, test, shoot

```sh
brew install cmake            # SDL2 comes from sdl2-compat, already installed
cmake -S sim -B build/sim && cmake --build build/sim
ctest --test-dir build/sim --output-on-failure
./build/sim/charm-sim --shots out/shots     # 01-home.png … 11-offline.png (+ 12-error.png)
```

The first configure downloads LVGL, ArduinoJson and IXWebSocket 11.4.6 (BSD-3-Clause; the live
mode's WebSocket client, built without TLS or zlib) as release tarballs pinned by SHA256
(`FetchContent`). LVGL is compiled from its sources against `ui/lv_conf.h` (`LV_CONF_INCLUDE_SIMPLE`),
the same way the firmware compiles it.

## Run it

```sh
./build/sim/charm-sim                        # window at --scale 2
./build/sim/charm-sim --replay sim/replays/talk.jsonl
./build/sim/charm-sim --headless --replay sim/replays/talk.jsonl   # no window, virtual clock
```

| Input | Does |
|---|---|
| mouse | touch (tap, press-and-hold, drag to swipe) |
| **space** (hold) | the talk button: `charm_ui_talk_pressed` / `released` |
| `1`–`8` | inject `contract/examples/*.json`, sorted by name (edition cards open the edition first) |
| arrows | swipe left/right/up/down |
| `c` | toggle the connection (`charm_ui_set_connected`) |
| `d` / `i` | server `state{done}` / `state{idle}` |
| `x` | server `dismiss` for the card on screen |
| `h` | print the key help |

Device→server frames (`displayed`, `action`, `request`, `cancel`) print to **stdout as JSON lines**.
Host notes (mic start/stop, brightness) go to stderr. Without `--connect` the sim plays a minimal
backend: it's connected and sends itself a `welcome` with the Mac's clock. The fake mic always
starts (`charm_host_mic_start()` returns true) and feeds a wobbling level. Brightness
(`charm_host_set_brightness`) dims the window and the screenshots.

## Live: a real device (`--connect`)

```sh
CHARM_TOKEN=… ./build/sim/charm-sim --connect ws://127.0.0.1:8765/charm        # window, mic, speakers
./build/sim/charm-sim --connect URL --mic-wav q.wav --auto-talk --trace          # scripted question
./build/sim/charm-sim --connect URL --headless --mic-wav q.wav --auto-talk       # no window/speakers
```

| Flag | Does |
|---|---|
| `--connect URL` | Be a client of `docs/PROTOCOL.md` at `ws://HOST:PORT/charm` |
| `--token T` | The server's `CHARM_TOKEN`. Default: the `CHARM_TOKEN` environment variable (prefer it: argv shows in `ps`) |
| `--mic-wav FILE` | A 16 kHz mono s16 WAV instead of the mic, streamed in real time while the talk button is held; the talk releases itself when the file ends. Make one with `say -o q.aiff "…" && afconvert -f WAVE -d LEI16@16000 -c 1 q.aiff q.wav` |
| `--auto-talk` | Hold the talk button once, 0.8 s after the welcome (pairs with `--mic-wav`) |
| `--trace` | Print server text frames (`[rx]`) and `audio_start`/`audio_end` to stderr |
| `--quit-after-reply` | Close the window once the reply finished playing |
| `--headless` | No window and no speakers (speech bytes are counted); exits after the reply with `--auto-talk`, else at `--timeout MS` (60000) |

It behaves like the firmware, and shares its code: `firmware/lib/charm_core` (frame builders,
reconnect backoff, keepalive, the 25 s talk limit, the level meter) is compiled unchanged into the sim.

- **Socket:** `hello` (`device_id` `charm-sim`, caps `mic`, `speaker`) → `welcome` within 10 s, else
  reconnect. `ping` every 10 s; no `pong` for 30 s means the link is dead. Reconnects back off 1, 2, 4,
  8, 16, then 30 s. The UI is offline until the real `welcome` (the sim sends itself nothing), and
  goes offline the moment the socket drops. Every server text frame goes to `charm_ui_on_message`,
  which sends its own receipts (`displayed`) back. `c` drops the socket and keeps it down; `c` again
  reconnects.
- **Mic:** holding space opens the Mac's default input through SDL2 at exactly 16 kHz s16le mono
  (SDL converts), sends `audio_start`, streams binary frames of 2048 bytes (≤ 4096), reports the level
  through `charm_ui_mic_level`, and on release flushes the rest and sends `audio_end{released}`. At
  25 s the sim ends the talk itself with `audio_end{limit}`. The device is closed between talks, so
  macOS's mic indicator is on only while it's really capturing. Listening shows only after the mic
  opened and the socket is online.
- **Speaker:** `speech_start` frames play through the default output (SDL2 queue, 16 kHz s16le mono);
  `charm_host_speech_stop()` (tap to interrupt) clears the queue at once and drops the rest of that
  speech. **Half-duplex:** pressing talk stops any speech first, like the firmware, so Dex's voice is
  never recorded.
- **Timings:** after each talk the sim prints `[timing]` lines (transcript, working, answer card,
  speech_start, first audio, speech_end, idle) in ms after the release.

### macOS microphone permission

The mic belongs to the app that launched the sim (Terminal, iTerm, VS Code…). The first talk makes
macOS ask; if it was denied, the Mac hands SDL pure silence rather than an error. The sim notices
(`[audio] the mic delivers pure silence…`) and the server answers `too_short`. Fix: **System Settings
→ Privacy & Security → Microphone**, enable your terminal, restart it. `--mic-wav` needs no permission.

### Replay files (`.jsonl`)

One server→device frame per line, fed every `--interval` ms (default 700). `#` lines are comments.
There are three sim directives:

```json
{"_sim":"wait","ms":2500}
{"_sim":"connected","value":false}
{"_sim":"talk","value":"press"}
```

## Layout

| Path | What |
|---|---|
| `src/main.cpp` | Args, SDL window, keys, replay pacing |
| `src/sim_host.cpp` | `charm_host.h` for the Mac: stdout frames, fake mic, real or virtual clock |
| `src/sim_display.cpp` | LVGL display into a framebuffer and a pointer indev (shared by the window, shots and tests) |
| `src/sim_script.cpp` | Example injection, replay lines, the scripted screenshot run |
| `src/sim_live.cpp` | `--connect`: the WebSocket client (IXWebSocket), hello/ping/backoff, talk streaming, speech |
| `src/sim_audio.cpp` | SDL2 mic capture and speaker queue, the WAV mic, the headless null speaker |
| `tests/fixtures/question.wav` | "What is a metaphor?" (`say`, 16 kHz mono) for the integration test |
| `src/png_write.cpp` | Minimal PNG encoder (zlib) |
| `tests/test_ui.cpp` | ctest `ui_contract`: every example card, receipts, replace/dismiss, stale, hold-to-confirm, honesty rules |
| `tests/test_host.cpp` | A recording `charm_host.h` with a virtual clock |
| `replays/talk.jsonl` | A talk → answer → decision → notice → error session |

ctest runs four tests: `ui_contract`, `sim_shots` (the screenshot script must reach every surface),
`sim_replay` (the sample replay must parse and play) and `sim_live_integration`
([`scripts/integration_test.py`](../scripts/integration_test.py)): the real charm server in-process
with its own test fakes for STT, Dex and TTS (imported from `server/tests/conftest.py`), the sim
connected headlessly, one talk from `tests/fixtures/question.wav`, then checks that the answer card is
on screen, its `displayed` receipt went back and all the speech arrived. It also checks a wrong token
and a server restart (the sim reconnects). No network, no Hermes; it needs `uv` (the test runs in the
server's environment).

## The UI (`ui/`)

| File | What |
|---|---|
| `charm_ui.cpp` | The `charm_ui.h` entry points, the surface state machine, and the placeholder surface builders |
| `dex_sprite.h/.cpp` | **The Dex seam**: `dex_set_pose/outfit/size`. Today it's a labeled gray box |
| `ui_card.h/.cpp` | Card model + ArduinoJson parsing, staleness, money formatting |
| `ui_hold.h` | Hold-to-confirm timing |
| `ui_time.h/.cpp` | ISO-8601 parsing; wall clock from `welcome.time` |
| `charm_ui_debug.h` | Introspection for the tests and the sim (firmware doesn't need it) |

Surface priority: offline (only from `charm_ui_set_connected(false)`) › listening (only after
`charm_host_mic_start()` returned true) › error › night › edition › focused card › working › home.
