---
title: Dex Charm — product and design brief
type: brief
created: 2026-09-25
updated: 2026-09-25
status: pre-design (input to /design-sprint)
vault_home: ~/notes-vault/agents/active/hermes/charm/README.md
---

# Dex Charm — product and design brief

This brief is the context pack for `/design-sprint ~/Projects/dex-charm`. The canvas has no memory of the
brainstorm that produced it, so everything the sprint needs is here.

## 1. What it is

A pocket-sized device with a small, always-animated **Dex** on its screen. Dex is the owner's personal
chief-of-staff agent (Nous Hermes, running on his VPS). The charm is **Dex with a body**. The owner can
hold to talk, glance at what's pending, and approve things with one tap, without opening his phone.

It is **not a new agent**. Dex, Coach Beard (fantasy football), the DeliveryCo ordering tools, the daily
newspaper and the cat camera already exist. The charm is a **remote control and a face** for them.
Humane and Rabbit failed by squeezing a new agent into a gadget. This goes the other way: the agents
already work, and the device only has to do three things well:

1. **Start it and walk away**: an order, a repo review, research, a long agent task.
2. **Show what's happening**: Dex's mood and pose, plus a progress glance.
3. **Decide in one second**: tap to approve, hold to spend money.

**Competitive reference, not a target:** Meta's Muse Charm (shown at Meta Connect, 2026-09-23). It is a
keychain device with a ~2" OLED touch screen and an animated, customizable avatar that is always on
screen. You tap a fingerprint sensor, then talk, and the avatar replies by voice. Long results go to
the Muse app, not the tiny screen. We share the core idea: a character that lives on screen, voice
first, cards second, and the full version sent somewhere bigger. Ours is different because a single
person's existing agent fleet sits behind it.

## 2. The hardware (the canvas)

Waveshare **ESP32-S3-Touch-AMOLED-1.8 V2**. The owner already owns this board; it currently runs the
Margin reading-companion prototype.

| Constraint | Value | Design consequence |
|---|---|---|
| Screen | **368 × 448 px** AMOLED, ~1.8", portrait | Every screen is drawn at exactly this size |
| Black | True black = pixels off | Default background is `#000`. It saves power, and Dex floats in darkness |
| Input | Capacitive touch + **one physical button** (BOOT) | Big touch targets (≥ 56 px); the button is hold-to-talk |
| Audio | Mic + small speaker | Voice first; the screen supports what's said |
| Motion | IMU on board (unused so far) | Face-down / pick-up / shake gestures are possible |
| Rendering | LVGL 8 on an ESP32-S3, 8 MB PSRAM | **Everything must be implementable:** bitmap fonts at fixed sizes, flat fills, sprites. No blur, no heavy shadows, no gradients over large areas |
| Color | RGB565 (16-bit) | Palette must survive 16-bit quantization; avoid subtle near-duplicate tones |

## 3. Physical use context (derive directions from this, not from app fashion)

- **Where:** in the hand, on the desk next to the laptop, on the nightstand, on a keychain or bag.
- **How long:** a glance of 2–10 seconds. Nothing should need more than about 10 seconds of attention.
- **Hands:** one. The thumb reaches the whole screen.
- **Light:** everything from a dark bedroom (reading at night) to daylight. There's a dim night mode.
- **Languages:** English and Spanish (the owner is bilingual; Dex answers in the language spoken).
- **What it competes with:** his phone. If the charm pulls him into checking it constantly, it failed.
  **Dex waits to be looked at; he never pings.** No badges, streaks or nag sounds.
- **Cost of failure:** a wrong tap spending money is the worst case. Money actions need a deliberate
  2-second hold on a preview.

## 4. The character — Dex (LOCKED)

Reference: [`design/character/dex-reference.png`](design/character/dex-reference.png).

Pixel-art Dex: messy dark-brown hair, short beard, teal jacket over a white shirt, black trousers,
white-and-grey sneakers, a brown messenger bag, a lanyard badge, a coffee mug and a phone showing a
green-checked task list. Both the mug and the badge carry a small **ringed-planet** logo.

**The character is locked. Directions vary the world around him, not him.** Design tasks for Dex:

1. **Redraw him on a strict pixel grid.** The reference is an AI-generated image and isn't grid-perfect.
   Propose a sprite size (for example 48×64 or 56×72 logical pixels, shown at 3–4× scale) and a
   limited palette (about 12–16 colors).
2. **A pose set.** Each pose has 2–6 animation frames:

| State | Pose idea | Meaning |
|---|---|---|
| Idle | Breathing, blinking, sips coffee now and then | Ready, nothing needs you |
| Listening | Looks up, leans in, hand to ear; sound ripple | The mic is recording (never shown unless it truly is) |
| Thinking / working | Types on his phone, flips through the checklist | Dex or another agent is working |
| Something for you | Looks straight at you and holds up the phone | A card is waiting; never flashes or buzzes |
| Done / saved | Ticks the checklist, small nod | The backend **confirmed** it; only then |
| Speaking | Mouth frames synced loosely to the audio | The reply is playing |
| Asleep / night | Seated, head down, mug steaming | Dim mode, nothing pending |
| Offline | Looks at a phone with no signal | No connection. It's honest and plain, no joke |
| Error / needs more | Scratches his head | Needs clarification or failed |

3. **Outfits and props for modes.** One Dex with accessories, never a different character:

| Mode | Prop | Source agent |
|---|---|---|
| Default | Mug + checklist phone | Dex |
| Game day | Whistle + clipboard, maybe a cap | Coach Beard (NFL fantasy) |
| Reading | Reading glasses + a book | Margin reading mode |
| Food order | Delivery bag / takeout box | DeliveryCo |
| Code review | Laptop or magnifying glass | GitHub (future) |
| The cat | A cat on his shoulder | Ojo de Gato cat camera |

4. **Two sizes.** Full body for Home, and a **mini head-and-shoulders** that sits in a corner while a
   card is open (like the iPhone's Dynamic Island: Dex never disappears).

## 5. Surfaces to design (named)

Keep these names across every render so the critiques stay comparable.

1. **Home / Idle**: full-body Dex, time, one tiny status line. On true black.
2. **Listening**: Dex listening, a live level indicator, the elapsed-time limit.
3. **Working**: Dex working, with a one-line "what" ("Asking Coach Beard…") and a cancel.
4. **Answer card**: the mini Dex in a corner and a card of at most 60 words. The spoken version is at
   most 2 sentences. Link-out footer: "Full version in Telegram."
5. **Decision card**: one of Dex's questions with its **default and deadline** ("Pause the side project?
   Default: yes, Sunday"). ✓ / ✗ / snooze.
6. **Money card: DeliveryCo preview**: store, items, total in COP, ETA, address, and a **2-second
   hold-to-confirm ring**. It must be impossible to trigger by accident.
7. **Live tracker: DeliveryCo order**: Dex watches the rider; the steps are preparing, picked up, 5 min
   away, arrived.
8. **Pocket edition**: the daily newspaper as 6 swipeable cards (see § 6).
9. **Job done**: a finished long task, e.g. "PR #42: 1 blocking, 2 nits". Actions: Send to Claude
   Code / Later.
10. **Night / dim**: the minimal-light version of Home.
11. **Offline / error**: honest and plain.

## 6. The pocket edition (the newspaper on the charm)

Dex publishes a daily newspaper: an evening edition (6 pages) and a morning sheet. Its design language
lives in the vault at `agents/active/hermes/edition-design/`: the `_tokens.css` palette and fonts
(paper/ink serif broadsheet, Playfair display, mono kickers, an accent red; the dark variant uses
yellow `#f2d02e` on `#0d0d0d`), plus `phone-edition-brief.md` and the `design-v3-phone-*` pages.

The charm doesn't shrink that HTML. It renders the **same structured desk feeds** as its own edition.
Each card should feel like a clipping from Dex's paper, with Dex standing next to it:

1. **Masthead**: edition number, weekday, and tonight's verdict in one line.
2. **Today's one thing**: the single priority, with ✓ / ✗ / snooze.
3. **Sports desk**: Coach Beard's one-line verdict plus up to 3 "do now" rows with deadlines.
4. **Almanac**: temperature, a 4-day strip, sunrise/sunset, the moon phase as a pixel icon.
5. **Waiting on you**: the one-tap approvals.
6. **The Wire**: the ticker, 8–12 short items scrolling along the bottom.

Plus **"Read it to me"**: the same cards spoken as a 60-second briefing.

Open tension for the sprint: **a pixel-art character next to newspaper typography.** Is it a pixel
font everywhere, crisp serif cards with a pixel Dex, or something in between? Let renders decide.

## 7. Content and honesty rules (carry into every direction)

These rules come from the Margin prototype and Dex's charter:

- Spoken answers are at most **2 sentences**. Cards are at most **~60 words**. Anything longer goes
  to Telegram or a notes app, never read aloud.
- Never fake a state: no listening pose unless the mic is on, and no ✓ before the backend confirms.
- Stale data says so ("desk missed deadline").
- Money = a preview plus a deliberate hold. Messages to other people = approval. Dex reminds; the owner
  decides.
- No notification theater: no red dots, streaks or idle sounds.

## 8. What the sprint must hand back (so it's buildable)

- A sprite sheet spec: grid size, scale, palette hex values, and a frame list per pose and outfit.
- A UI palette in hex (checked for RGB565 survival), type choices mapped to **fixed bitmap sizes**
  (e.g. 14 / 18 / 24 / 32 px), and a spacing scale.
- Every named surface at **368×448**, plus motion timings (frame durations, card slide in/out).
- The winning direction's bones and the design section of this brief (per the `/design-sprint`
  Phase G).

## 9. Run it on the Mac before the device

The plan after design comes back: build the UI in **LVGL** and run it in LVGL's **macOS desktop
simulator**. The same C code compiles for the ESP32, so what the owner sees on the Mac is what the
device will show. A fake backend replays sample feeds (an edition, a DeliveryCo order, a decision) so every
surface can be tested with no hardware. Flashing comes after the simulator looks right. The board's
original firmware is already backed up (Margin repo, `.local/backups/`).

## 10. Decided / not decided

**Decided (2026-09-25):**
- The character is **Dex with a body**, using the owner's pixel-art reference.
- The charm is the platform. Margin (reading) becomes one mode of it.
- Design comes first, via `/design-sprint`. The design comes back here and the build runs from this
  repo.

**Not decided (not design blockers):**
- Whether a hold on the charm counts as the owner's explicit yes for DeliveryCo checkout. That's a charter
  amendment in `agents/active/hermes/charter.md`. Design the money card anyway.
- Read-only GitHub access for Dex. Hermes has no repo access today.
- Voice tier: A (free: local Whisper + Edge TTS), B (ElevenLabs voice with Dex as the brain), or C
  (fast realtime model plus a handoff to Dex).
- Where the server runs outside the house: probably next to Hermes on the VPS, with the charm on the
  phone's hotspot.

## Sources

- Meta Muse Charm coverage: TechCrunch 2026-09-23 and 2026-09-24; Meta Connect 2026 recap blog; Irish
  Times 2026-09-24; TechEBlog. Meta has published no official spec sheet; details are as reported.
- Margin prototype: `margin` (README, `docs/hardware.md`, `docs/hermes.md`).
- Dex charter and DeliveryCo gate: vault `agents/active/hermes/charter.md`.
- Newspaper design system: vault `agents/active/hermes/edition-design/`.
