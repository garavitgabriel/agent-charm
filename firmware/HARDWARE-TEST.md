# Hardware test: first plug-in of Dex Charm

For whoever has the device on the desk. The firmware was only compiled and unit-tested when it
was written. Nothing had run on the board yet, so **this checklist is where it's proven**. Work
top to bottom. Each check says what to do and what proves it passed. Note anything that fails,
with the serial log.

**Setup:**
- The server is running (`server/README.md`) on the Mac, with `CHARM_TOKEN` set.
- `firmware/src/secrets.h` is filled in: Wi-Fi, the Mac's LAN IP as `CHARM_SERVER_HOST`, the same
  token.
- You backed up the flash and flashed as in `README.md` → Flash.
- A serial monitor is open: `pio device monitor -b 115200`.

| # | Check | Do | Passes when |
|---|---|---|---|
| 1 | **Boot + chips** | Reset the board and watch the log | It prints `[charm] dex-charm-fw/0.1 proto/0`, then `touch=1 audio=1 imu=1 pmu=1 psram=8388608`. Any `0` names the chip that failed. |
| 2 | **Display** | Look at the screen | The UI's first screen renders: centred, not mirrored, no stripes or offset (column offset 16). With the stub UI it's the white label on black. |
| 3 | **Touch** | Tap and drag across the screen, including the corners | The UI reacts where you touch. With the stub UI, nothing crashes and the log stays clean. Once the real UI lands, a tapped control responds. |
| 4 | **Offline honesty** | Boot with the server **stopped** | The UI shows offline. The log shows `[net] socket down, retry in 1000 ms`, then 2000, 4000, 8000, 16000 and 30000 ms (the backoff). |
| 5 | **Wi-Fi join** | Watch the log after boot | `[net] wifi 192.168.x.x` appears within ~10 s. |
| 6 | **hello / welcome** | Start the server | The server log shows the `hello` with `device_id`, `fw` and the caps. The device goes online (the UI leaves offline) with no reconnect loop. With a **wrong token**, the server replies `error{auth}` and closes 4401, and the UI shows the error, not "online". |
| 7 | **Keepalive** | Leave it idle 1 min | The server log shows a `ping` about every 10 s, answered with `pong`, and the device stays online. Stop the server: the UI goes offline within ~30 s at most (right away if the socket closes cleanly). |
| 8 | **Button** | Press BOOT briefly, then hold it 3 s | Holding calls `charm_ui_talk_pressed`, releasing calls `…_released`. The server sees exactly one `audio_start` and one `audio_end{reason:"released"}` per hold, and no double-fires. A BOOT held **during reset** is ignored until released. |
| 9 | **Mic level** | Hold BOOT and talk, then stay silent | The level indicator moves with your voice and falls when you're quiet. The server receives binary frames of ≤ 4096 bytes (about 8 per second). |
| 10 | **Listening honesty** | Hold BOOT with the server **stopped** | The UI does **not** show listening (`charm_host_mic_start()` returned false). |
| 11 | **25 s limit** | Hold BOOT for 30 s | At 25 s the server receives `audio_end{reason:"limit"}`, and releasing later sends nothing more. |
| 12 | **Spoken round trip** | Hold BOOT, ask "What time is it in Tokyo?", release | Transcript, then working, then an answer card, then Dex's voice from the speaker. The server logs `displayed{id}` for the card. Note the total time. |
| 13 | **Speaker playback quality** | Listen to check 12's reply | Clear speech at the right pitch and speed: not chipmunk (a rate mismatch), not crackly (underrun), and audible at volume 80. |
| 14 | **Interrupt** | While Dex is speaking, trigger the UI's stop (tap to interrupt) or press BOOT to talk again | The audio stops within ~0.1 s. No old audio resumes afterwards. |
| 15 | **PA off when idle** | After speech ends, put your ear to the speaker. With a multimeter, probe GPIO46 (PA enable) against GND | No hiss when idle. GPIO46 is ~0 V when idle, ~3.3 V only during speech, and back to 0 V after `speech_end` has drained or after an interrupt. |
| 16 | **Face-up sign** | Lay the device **screen up**, then flip it **screen down** and hold 1 s | The server gets `event{name:"face_down"}` when it goes screen-down, and `face_up` when you turn it back. **If they're swapped**, set `face_up_z_sign = -1.0f` in `lib/charm_core/src/motion.h`, rebuild, and repeat. |
| 17 | **Pickup** | Leave it flat and untouched 3 s, then pick it up | One `event{name:"pickup"}`. |
| 18 | **Shake** | Shake it firmly 3–4 times | One `event{name:"shake"}`, not a burst. If it's too sensitive or too hard to trigger, tune `shake_g` / `shake_peaks` in `motion.h`. |
| 19 | **Battery** | Run on battery, then plug in USB | Shortly after the device goes online, the server gets `event{name:"battery","value":N}` with a believable percent. **With no battery attached, no battery event is sent at all**, since the device never invents a level. |
| 20 | **Brightness** | Trigger the UI's dim or night mode | The panel dims and comes back. |

**If a chip is missing** (`imu=0` or `pmu=0` in check 1), the rest still works and that chip's
events simply never appear. Report the log line.

**After testing:** to go back to the previous firmware, see `README.md` → Restore.
