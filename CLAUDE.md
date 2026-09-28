# Dex Charm — repo guide

Dex with a body: a pocket ESP32-S3 AMOLED device, the always-animated **smooth illustrated** Dex, and a
voice/cards server for your agent (any OpenAI-compatible model, or a Hermes agent).

## Read first (every builder, every time)

1. **[`docs/BRIEF.md` § 11 Design](docs/BRIEF.md)**: the final design.
   - Its sources of truth are [`docs/design/final/tokens.md`](docs/design/final/tokens.md),
     [`motion.md`](docs/design/final/motion.md), the 368×448 reference screens
     `docs/design/final/*.png`, and the sprite source `docs/design/final/src/`.
   - **Implement from the final render,** not from critic reports or chat screenshots.
   - Every UI change must pass the **§ 11.6 pre-merge checklist** on the simulator.
2. [`docs/PROTOCOL.md`](docs/PROTOCOL.md) + [`contract/`](contract/): the wire contract, including
   § Clarifications and § Reading mode.
3. The rest of `docs/BRIEF.md`: the product context.

**Where the design and the contract disagree, the contract wins.** Tell the chief, who resolves it
with the design owner. Rulings so far:
- The answer-card footer comes from the server and follows PROTOCOL clarification #5 ("Shortened. Ask
  Dex for the rest."). It never says "Full version in <chat app>" unless something was actually sent
  there.
- The Listening "fuse" runs for the listen limit, **25 s** (the firmware and UI limit), not 30 s.
- **Sprite cell is 192×224** (not the 192×192 in BRIEF § 11.7). At scale 0.62 Dex spans the hip
  −161 px (bag overhead) to +62 px (ground shadow). The cell covers screen x 160..351, y 218..441.
- **Honest mouth.** `DEX_POSE_SPEAKING` (talking mouth) only while speech audio plays. The quiet
  reading lead is `DEX_POSE_ATTENTION`, and the reading detail is `DEX_POSE_PAPER`.
- **Money Done** frames bake a full gold bag. The LVGL bag-fill overlay is for `LIFT_BAG` (mid-hold)
  only.

## Layout and ownership

| Path | What | Owner |
|---|---|---|
| `docs/PROTOCOL.md`, `contract/**`, `ui/charm_ui.h`, `ui/charm_host.h`, `notes/src/charm_notes/__init__.py`, this file | The contract | Chief session only |
| `docs/BRIEF.md` § 4 and § 11, `docs/design/**` | The design | Design session only; builders read, never edit |
| `firmware/**` | PlatformIO ESP32-S3 firmware (Waveshare AMOLED 1.8 V2) | Hardware layer |
| `ui/**` (except the two headers) | LVGL UI shared by the firmware and the simulator | UI / simulator |
| `sim/**` | macOS SDL2 simulator (CMake) | UI / simulator |
| `tools/**` | `charm-assets`: sprites and fonts → generated `ui/charm_assets_*` | Asset pipeline |
| `server/**` | Python charm server: WebSocket, STT → Dex → TTS, reading mode | Server |
| `notes/**` | Python note store ("save this thought" → vault inbox via the OS knowledge service) | Notes |
| `feeds/**` | Python: Dex's desk feeds → edition/decision cards | Feeds |

## Rules

- **The contract changes only through the chief session,** and the design only through the design
  session. If either blocks you, write a blocker note. Don't edit it.
- **Work in your own worktree** (`../dex-charm-batch-N`), never in the primary checkout.
- **Never commit secrets:** the Wi-Fi password, `CHARM_TOKEN`, the Hermes API key, `OS_API_TOKEN`.
  Use `secrets.h` / `.env` / `~/.os-api.env`, all outside git.
- **Honesty invariants** (from Margin, Dex's charter and design § 11.5):
  - Never show listening unless the mic is capturing.
  - Never show ✓ / Done / Saved before the backend confirms.
  - Stale data says it's stale.
  - Money needs a ≥2000 ms hold of Dex's bag on a preview (never a tap).
  - v0 never places a real order.
  - Dex never promises to nudge.
- **The agent is read-and-converse only from this project.** With the Hermes backend, reach it over
  an SSH `hermes` alias into the container's local API. Make no agent config, cron or charter changes.
- **Vault writes go only through the OS knowledge service's `POST /submit`** (inbox-only, new files
  only). Never write to the synced vault folder directly.
- **Margin is the hardware reference** (the author's earlier firmware for this board, not
  published). Code ported from it carries a provenance comment.
- Commits: `area: brief description` (e.g. `server: add edge-tts synthesis`).
