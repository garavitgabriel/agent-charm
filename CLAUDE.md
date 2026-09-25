# Dex Charm — repo guide

Dex with a body: a pocket ESP32-S3 AMOLED device, the always-animated pixel Dex, and a voice/cards
server for the owner's agent fleet. Product and design context: [`docs/BRIEF.md`](docs/BRIEF.md). Wire
contract: [`docs/PROTOCOL.md`](docs/PROTOCOL.md) + [`contract/`](contract/).

## Layout and ownership

| Path | What | Owner |
|---|---|---|
| `docs/BRIEF.md`, `docs/PROTOCOL.md`, `contract/**`, `ui/charm_ui.h`, `ui/charm_host.h` | The contract | Chief session only |
| `firmware/**` | PlatformIO ESP32-S3 firmware (Waveshare AMOLED 1.8 V2) | Hardware layer |
| `ui/**` (except the two headers) | LVGL UI shared by the firmware and the simulator | UI / simulator |
| `sim/**` | macOS SDL2 simulator (CMake) | UI / simulator |
| `server/**` | Python charm server: WebSocket, STT → Dex → TTS | Server |
| `feeds/**` | Python: Dex's desk feeds → edition/decision cards | Feeds |

## Rules

- **The contract changes only through the chief session.** If it blocks you, write a blocker note.
  Don't edit it.
- **Never commit secrets:** the Wi-Fi password, `CHARM_TOKEN`, the Hermes API key. Use `secrets.h`
  and `.env`, both gitignored.
- **Honesty invariants** (from Margin and Dex's charter):
  - Never show listening unless the mic is capturing.
  - Never show ✓ before the backend confirms.
  - Stale data says it's stale.
  - Money needs a ≥2000 ms hold on a preview.
  - v0 never places a real order.
- **Hermes is read-and-converse only from this project.** Reach it the way Margin does (an SSH
  `hermes` alias into the container's local API). Make no Hermes config, cron or charter changes.
- **Margin is the hardware reference** (`margin`, local only). Copy code from it with its
  license and provenance; never modify that repo.
- Commits: `area: brief description` (e.g. `server: add edge-tts synthesis`).
