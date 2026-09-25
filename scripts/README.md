# scripts: run and check the whole charm on the Mac

| Script | What |
|---|---|
| `demo.sh` | One command: the charm server + the simulator as a real device. Talk to Dex |
| `integration_test.py` | The sim ↔ server round trip with fake STT/Dex/TTS (ctest `sim_live_integration`) |

## Talk to Dex: `scripts/demo.sh`

From the repo root:

```sh
scripts/demo.sh
```

Needs `uv`, `cmake`, `ffmpeg`, SDL2 (`sdl2-compat`, see [`sim/README.md`](../sim/README.md)) and the
`hermes` SSH alias (the one Margin uses). What it does:

1. **Token.** Makes sure `server/.env` exists (copied from `.env.example`) and has a `CHARM_TOKEN`. If
   it's empty, it writes a random one. The file is gitignored and `chmod 600`; the script prints only
   the first 4 characters.
2. **Cards.** `charm-feeds pull && charm-feeds build` into `out/cards` (gitignored): read-only copies of
   Dex's desk feeds, turned into the pocket edition. If that fails (no network, SSH down), it says
   so and uses `feeds/fixtures/cards`. Log: `out/demo/feeds.log`.
3. **Server.** `charm-server` on `127.0.0.1:8765` (or `CHARM_PORT`) with `CHARM_CARDS_DIR` pointed at
   those cards. It loads Whisper first (a few seconds). Log: `out/demo/server.log`, which also has
   each talk's `talk timings stt=… agent=… tts=… total=…`.
4. **Sim.** Builds `charm-sim` and launches it connected at `--scale 2`, with the token passed through
   the environment (never on the command line).

**Ctrl-C** in the terminal, or closing the sim window (Esc / q), stops the sim and the server.

Flags: `--no-pull` skips the feeds pull and uses the fixture cards. Anything else goes to `charm-sim`,
for example a scripted question with its timings:

```sh
say -o /tmp/q.aiff "What's the difference between a metaphor and a simile?"
afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/q.aiff out/demo/q.wav
scripts/demo.sh --mic-wav out/demo/q.wav --auto-talk --trace --quit-after-reply
```

### Controls (sim window)

| Input | Does |
|---|---|
| **space** (hold) | Talk. Dex listens while it's held (25 s at most); release to send. Pressing it while Dex speaks cuts the speech off |
| mouse | Touch: tap, press-and-hold (money confirm needs a 2 s hold), drag to swipe |
| ← | Swipe left: the pocket edition (the server sends the cards) |
| arrows | Swipe in that direction |
| `c` | Drop the connection (the UI goes offline); `c` again reconnects |
| `1`–`8` | Inject a `contract/examples` card locally (not from the server) |
| `h` | Key help · Esc / q quits |

### macOS microphone permission

macOS asks the first time you hold space, on behalf of the terminal app that ran `demo.sh`. If it
was denied, the mic gives silence (the sim prints `[audio] the mic delivers pure silence…`, and Dex
says the talk was too short). Enable your terminal in **System Settings → Privacy & Security →
Microphone** and restart the terminal. Speech plays on the default output device.

## `integration_test.py`

```sh
uv run --project server python scripts/integration_test.py --sim build/sim/charm-sim
```

It needs no network and no Hermes. It starts the real server in-process, with the server's own
`FakeSTT`/`FakeAgent`/`FakeTTS` *imported* from `server/tests/conftest.py` (nothing in `server/` is
edited). Then it runs `charm-sim --connect … --headless --mic-wav sim/tests/fixtures/question.wav
--auto-talk` and checks:

- `welcome`, one transcription, one question to the fake Dex;
- the answer card is on the sim's screen, and its `displayed` receipt came back;
- every byte of the fake speech reached the sim's speaker;
- a wrong token gets the server's `auth` error, and the sim never goes online;
- after a server restart on the same port, the sim reconnects and is welcomed again.

ctest runs it as `sim_live_integration` when `uv` is on the PATH.
