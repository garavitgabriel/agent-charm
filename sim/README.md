# sim: the Dex Charm UI on the Mac

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

The first configure downloads LVGL and ArduinoJson as release tarballs pinned by SHA256
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
Host notes (mic start/stop, brightness) go to stderr. At startup the sim plays a minimal backend:
it's connected and sends itself a `welcome` with the Mac's clock. Connecting to the real server is
the chief's integration step.

The fake mic always starts (`charm_host_mic_start()` returns true) and feeds a wobbling level.
Brightness (`charm_host_set_brightness`) dims the window and the screenshots.

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
| `src/png_write.cpp` | Minimal PNG encoder (zlib) |
| `tests/test_ui.cpp` | ctest `ui_contract`: every example card, receipts, replace/dismiss, stale, hold-to-confirm, honesty rules |
| `tests/test_host.cpp` | A recording `charm_host.h` with a virtual clock |
| `replays/talk.jsonl` | A talk → answer → decision → notice → error session |

ctest runs three tests: `ui_contract`, `sim_shots` (the screenshot script must reach every surface)
and `sim_replay` (the sample replay must parse and play).

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
