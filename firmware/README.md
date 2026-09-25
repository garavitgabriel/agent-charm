# firmware: Dex Charm on the Waveshare ESP32-S3-Touch-AMOLED-1.8 V2

The hardware layer. It hosts the shared LVGL UI (`../ui`) on the device, so it implements
`ui/charm_host.h` and drives `ui/charm_ui.h`, and it speaks `docs/PROTOCOL.md` to the charm server
over Wi-Fi.

**Board: V2 only** (CO5300 display + CST820 touch). V1 (SH8601/FT3168) won't work. Pin map:
`src/board.h`. Hardware reference and provenance: Margin's `docs/hardware.md`, which lives in
`margin` and is read-only for this project.

Plugging the device in for the first time? Work through [`HARDWARE-TEST.md`](HARDWARE-TEST.md).

## Build and test

```sh
cd firmware
pio run -e charm      # ESP32-S3 firmware (first run downloads the pioarduino platform, ~1 GB)
pio test -e native    # unit tests for the pure logic in lib/charm_core, on the Mac
```

- `env:charm` uses Margin's exact platform (pioarduino `55.03.311`, i.e. Arduino-ESP32 3.3.11) and
  its memory settings: 16 MB QIO flash, OPI PSRAM, `default_16MB.csv`, USB CDC on boot.
- The shared UI is compiled from `../ui/*.cpp` by `scripts/shared_ui.py`, with `-I ../ui` so LVGL
  picks up `../ui/lv_conf.h` (`LV_CONF_INCLUDE_SIMPLE`). Whatever `ui/` holds builds unchanged:
  today that's the skeleton stub, later it's the real UI.
- Pinned libraries: LVGL `8.3.11` and ArduinoJson `7.4.2` (same as Margin), and
  `links2004/WebSockets` `2.7.3` (see below).

## Secrets

```sh
cp src/secrets.example.h src/secrets.h   # gitignored, never commit it
```

Fill in the Wi-Fi SSID/password, the server host/port/path, `CHARM_TOKEN` (must equal the server's
`CHARM_TOKEN` env var) and a device id. Without `secrets.h` the build still succeeds (with a
warning) using the placeholders, and the device stays offline.

## Flash

No device is attached during this build, so nothing here has been flashed yet. When the device
is plugged in:

1. **Back up the current flash first.** It's running Margin now. Margin's docs say its original
   factory image is on the **Mac mini** at `margin/.local/backups/original-2026-09-08.bin`
   (it's private and not copied to other machines; there's a `.sha256` next to it). Still take a fresh
   full backup of the Margin image before flashing, and keep it **outside any git repo**:

   ```sh
   ls /dev/cu.usbmodem*        # find the port (it was /dev/cu.usbmodem11301 for Margin)
   mkdir -p ~/charm-backups
   uv tool run --from esptool esptool --port /dev/cu.usbmodemXXXX --baud 921600 \
     read-flash 0 0x1000000 ~/charm-backups/pre-charm-$(date +%F).bin
   uv tool run --from esptool esptool --port /dev/cu.usbmodemXXXX --baud 921600 \
     verify-flash 0 ~/charm-backups/pre-charm-$(date +%F).bin
   ```

2. Flash:

   ```sh
   pio run -e charm -t upload --upload-port /dev/cu.usbmodemXXXX
   pio device monitor -b 115200
   ```

   The boot log prints `[charm] touch=1 audio=1 imu=1 pmu=1 psram=8388608` when everything came up.

## Restore Margin or the original image

- **Margin firmware:** `cd margin/firmware && pio run -e margin-v2 -t upload --upload-port /dev/cu.usbmodemXXXX`
  (this builds from Margin's repo without changing it).
- **A full image** (the factory backup if it turns up, or the pre-charm backup from step 1):

  ```sh
  uv tool run --from esptool esptool --port /dev/cu.usbmodemXXXX --baud 921600 \
    write-flash 0 path/to/backup.bin
  ```

  A full image restores the partition layout and settings too. No efuses or security settings
  are touched by any of this.

## How it's put together

| File | Role |
|---|---|
| `src/main.cpp` | Arduino setup/loop: LVGL tick, touch → LVGL, BOOT button → `charm_ui_talk_*`, inbound frames → `charm_ui_on_message`, online/offline → `charm_ui_set_connected`, the 25 s talk limit, IMU/battery events. Implements `charm_host.h`. |
| `src/display.*` | XCA9554 reset, CO5300 panel, LVGL display driver, CST820 touch. Ported from Margin. |
| `src/audio.*` | I2S + ES8311. The mic task keeps the left channel as 16 kHz mono in a PSRAM ring; the speaker task plays the `SpeechPlayer` ring, mono duplicated to stereo. The PA (GPIO46) is HIGH only while playing. |
| `src/net.*` | Wi-Fi + WebSocket on its own task (the TCP connect can block for 5 s). It sends hello, pings every 10 s, reconnects with backoff (1, 2, 4, 8, 16, then 30 s), and streams mic frames (≤ 4096 bytes). |
| `src/sensors.*` | QMI8658 accelerometer → face_down/face_up/pickup/shake; AXP2101 battery percent. |
| `src/es8311*` | Espressif's ES8311 driver, Apache-2.0 headers kept, from Waveshare's V2 `15_ES8311` example (identical to Margin's copy). |
| `lib/charm_core/` | Pure logic with no Arduino: frame building, message peek, ring buffer, speech player, button debounce, backoff, keepalive, talk limit, mic level, motion, battery reporting. Covered by `test/`. |
| `lib/waveshare-gfx/` | Waveshare's Arduino_GFX copy with the CO5300 driver. See its `PROVENANCE.md`. |
| `lib/SensorLib/`, `lib/XPowersLib/` | QMI8658 and AXP2101 drivers from Waveshare's repo at the pinned commit. See each `PROVENANCE.md`. |

### Talk and speech flow on the device

- The BOOT button (debounced, 30 ms) calls `charm_ui_talk_pressed/released`. The UI calls
  `charm_host_mic_start()`, which returns true only when the codec is up and the server has
  welcomed us. Then the host sends `audio_start`, streams binary PCM, and on stop sends
  `audio_end{reason}`. At 25 s the host ends the talk itself with `reason:"limit"`.
- Starting to talk stops any playback first (half-duplex), so Dex doesn't hear itself.
- `speech_start` (16 kHz, s16le, mono only) arms the player. Binary frames fill a 1 MB PSRAM ring,
  and playback starts after 100 ms of buffered audio or at `speech_end`. `speech_end` drains the
  ring, then the PA goes low. `charm_host_speech_stop()` clears the ring and drops the PA
  immediately. Late frames after a stop are discarded.
- The link counts as online from `welcome` until the socket drops, 30 s pass without a `pong`, or
  10 s pass after `hello` without a `welcome`. The UI is told offline by the host only.

### Why `links2004/WebSockets` 2.7.3

It's the most widely used Arduino WebSocket client. It supports binary frames and ESP32 Arduino
3.x (`NetworkClient`), with no async-TCP dependency, and it builds on Margin's pinned platform.
Two of its behaviours shape `net.cpp`:

- The TCP connect is blocking (up to 5 s), so the client runs on its own FreeRTOS task, never on
  the UI loop.
- A failed TCP connect raises no event. A thin subclass reads the library's protected
  last-failure timestamp so each failure advances our own tested `Backoff` schedule through
  `setReconnectInterval()`.

The alternative was ESP-IDF's `esp_websocket_client`. It isn't part of the Arduino core's
prebuilt components, so using it would mean a hybrid IDF build.

### Motion thresholds

`lib/charm_core/src/motion.h` holds first guesses: flat is |z| > 0.8 g held 600 ms, pickup is a
0.2 g jolt after 2 s at rest, and shake is 3 peaks over 0.9 g within 900 ms. The sign of Z with
the screen facing up depends on how the IMU is mounted, so it's `face_up_z_sign`, checked in
`HARDWARE-TEST.md`. Tune these on the device.

### Known limits (v0)

- When the host's 25 s limit ends a talk, it sends `audio_end{limit}`, stops the mic, and calls
  `charm_ui_talk_released()` so the UI leaves "listening" (chief ruling, 2026-09-25). The UI replies
  with `charm_host_mic_stop("released")`, which is a no-op by then. The real UI also enforces 25 s
  itself by calling `charm_host_mic_stop("limit")`; `end_talk()` is idempotent, so whichever fires
  first wins and only one `audio_end` is sent.
- Wi-Fi modem sleep is off (`WiFi.setSleep(false)`) for steady audio streaming. That costs
  battery; revisit once power matters.
- `ws://` only. `wss://` for the VPS needs certificates configured; not done in v0.
