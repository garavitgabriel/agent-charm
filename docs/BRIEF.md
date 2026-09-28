---
title: Dex Charm — product and design brief
type: brief
created: 2026-09-25
updated: 2026-09-27
status: designed (§ 11), in build
---

# Dex Charm — product and design brief

This brief was the context pack for the design sprint (`/design-sprint`). The canvas has no memory of the
brainstorm that produced it, so everything the sprint needs is here.

## 1. What it is

A pocket-sized device with a small, always-animated **Dex** on its screen. Dex is the owner's personal
chief-of-staff agent (in the original build, a Nous Hermes agent on a VPS). The charm is **Dex with a
body**. The owner can hold to talk, glance at what's pending, and approve things with one tap,
without opening a phone.

It is **not a new agent**. Dex, Coach Beard (fantasy football), food-delivery ordering tools, the daily
newspaper and a pet camera already exist. The charm is a **remote control and a face** for them.
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

Waveshare **ESP32-S3-Touch-AMOLED-1.8 V2**. The original build reused a board that ran the Margin
reading-companion prototype.

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
- **What it competes with:** the phone. If the charm pulls you into checking it constantly, it failed.
  **Dex waits to be looked at; he never pings.** No badges, streaks or nag sounds.
- **Cost of failure:** a wrong tap spending money is the worst case. Money actions need a deliberate
  2-second hold on a preview.

## 4. The character — Dex (LOCKED: smooth illustrated, 2026-09-25)

> **Superseded by the design sprint.** Pixel art is **retired**. The owner picked the smooth illustrated
> Dex on 2026-09-25 ("definitely smooth, it looks and feels more premium"). The canonical character is
> the code in [`design/character/smooth/`](design/character/smooth/) (`dex.py` parts, `sheet.py`
> poses), with the reference sheet [`design/character/dex-smooth-sheet.png`](design/character/dex-smooth-sheet.png).
> The original pixel reference, [`design/character/dex-reference.png`](design/character/dex-reference.png),
> now defines **identity only** (hair, beard, teal jacket, bag, badge, mug, phone, ringed-planet
> logo). The final pose list, placement and the character-swap contract are in **§ 11 Design**. The
> pixel-era tasks below are kept for history.

Identity: messy dark-brown hair, short beard, teal jacket over a white shirt, black trousers,
white-and-grey sneakers, a brown messenger bag, a lanyard badge, a coffee mug and a phone showing a
green-checked task list. Both the mug and the badge carry a small **ringed-planet** logo.

**The character is locked. Directions vary the world around him, not him.** Original design tasks
(historical; see § 11 for what shipped):

1. ~~**Redraw him on a strict pixel grid.**~~ Retired. He is smooth illustrated, flat tonal steps.
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
| Food order | Delivery bag / takeout box | A food-delivery agent |
| Code review | Laptop or magnifying glass | GitHub (future) |
| The cat | A cat on his shoulder | A pet camera |

4. ~~**Two sizes.**~~ **Superseded: one size, one anchor.** Dex is full body at one scale in one
   anchor zone on every screen, and content sits above him (§ 11). All the critics failed the corner
   mini-head as "sticker Dex".

## 5. Surfaces to design (named)

Keep these names across every render so the critiques stay comparable.

1. **Home / Idle**: full-body Dex, time, one tiny status line. On true black.
2. **Listening**: Dex listening, a live level indicator, the elapsed-time limit.
3. **Working**: Dex working, with a one-line "what" ("Asking Coach Beard…") and a cancel.
4. **Answer card**: the mini Dex in a corner and a card of at most 60 words. The spoken version is at
   most 2 sentences. Link-out footer: "Full version in <main chat>." (superseded, see § 11.3)
5. **Decision card**: one of Dex's questions with its **default and deadline** ("Pause the side project?
   Default: yes, Sunday"). ✓ / ✗ / snooze.
6. **Money card: delivery preview**: store, items, total in local currency, ETA, address, and a **2-second
   hold-to-confirm ring**. It must be impossible to trigger by accident.
7. **Live tracker: delivery order**: Dex watches the rider; the steps are preparing, picked up, 5 min
   away, arrived.
8. **Pocket edition**: the daily newspaper as 6 swipeable cards (see § 6).
9. **Job done**: a finished long task, e.g. "PR #42: 1 blocking, 2 nits". Actions: Send to Claude
   Code / Later.
10. **Night / dim**: the minimal-light version of Home.
11. **Offline / error**: honest and plain.

## 6. The pocket edition (the newspaper on the charm)

Dex publishes a daily newspaper: an evening edition (6 pages) and a morning sheet. Its design language
lives with the agent (not in this repo): a paper/ink serif broadsheet, Playfair display, mono
kickers, an accent red; the dark variant uses yellow `#f2d02e` on `#0d0d0d`.

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
  to the main chat or a notes app, never read aloud.
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
simulator**. The same C code compiles for the ESP32, so what you see on the Mac is what the
device will show. A fake backend replays sample feeds (an edition, a delivery order, a decision) so every
surface can be tested with no hardware. Flashing comes after the simulator looks right. The board's
original firmware is already backed up (Margin repo, `.local/backups/`).

## 10. Decided / not decided

**Decided (2026-09-27, design sprint):**
- Smooth illustrated Dex (pixel retired). No clock. Warm-gold accent `#F2C14E`. BCKO base + MZCL Listening. See § 11.

**Decided (2026-09-25):**
- The character is **Dex with a body**, using the owner's pixel-art reference (style superseded 2026-09-25 → smooth).
- The charm is the platform. Margin (reading) becomes one mode of it.
- Design comes first, via `/design-sprint`. The design comes back here and the build runs from this
  repo.

**Not decided (not design blockers):**
- Whether a hold on the charm counts as the owner's explicit yes for a real checkout. That's a
  change to the agent's own rules. Design the money card anyway.
- Read-only GitHub access for Dex. Hermes has no repo access today.
- Voice tier: A (free: local Whisper + Edge TTS), B (ElevenLabs voice with Dex as the brain), or C
  (fast realtime model plus a handoff to Dex).
- Where the server runs outside the house: probably next to the agent on a VPS, with the charm on
  the phone's hotspot. (Since done: see `deploy/vps/README.md`.)

## 11. Design (final, from /design-sprint 2026-09-25 → 27)

**Builders: read this section first.** Exact values live in
[`design/final/tokens.md`](design/final/tokens.md) and [`design/final/motion.md`](design/final/motion.md).
The reference screens are [`design/final/*.png`](design/final/) at 368×448, and their generating source
is [`design/final/src/`](design/final/src/). **Implement from the final render, not from a critic report
or a chat screenshot.** Evidence and history: [`design/bones.md`](design/bones.md),
and the design-sprint records in `docs/internal/design-sprint/`.

### 11.1 Direction

**Dex is the interface, not a mascot beside it.** The base is the clean, premium-wearable direction
(render `1-BCKO`), with the Listening screen and the character/content separator from `24-MZCL`. The
screen is true black. Content sits in one zone at the top, Dex lives full-body in one anchor zone
below it, and a thin rule separates the two. On every screen where you *act*, Dex physically does
the thing: he holds up the "Yes" sign, holds out the takeout bag (**the bag is the hold-to-pay
control**), catches your voice in his cupped hand, and hands the order over when it's done. The
premium feel comes from restraint (one accent, three type sizes, no boxes) and from a character who
is alive, not from decoration. **There is no clock anywhere.**

### 11.2 Tokens (summary; `tokens.md` is the source of truth)

| Token | Value |
|---|---|
| Background | `#000000` on every screen |
| Primary text `FG` | `#F2EFE9` |
| Secondary text `FG2` | `#D6D3CC` (never below `#BDBDBD`) |
| **Accent** (one accent, one meaning: "you can act on this") | **Warm gold `#F2C14E`**, side plane `#D19F2B`, highlight `#F9DC94`. Night accent `ACC_N` `#5E4A1C` (dimmed gold; reserved, since Night has no action today). |
| Text on accent `ON_ACC` | `#0B0A12` |
| Separator `LINE` | `#3B3A40`, 3 px, (24,206)→(344,206) |
| Type | **Instrument Sans** 400/500/600, fixed sizes **18 / 24 / 32 / 40 px**, at most 3 per screen. 40 is the money total only. Actions are 24/600. |
| Spacing | 4 / 8 / 16 / 24 / 32; outer gutter 24 |
| Touch targets | ≥ 56 px; pills 56 px tall, radius 28, no outline |
| Content zone | (24, 24, 320, 166); nothing below y=190 |
| Anchor zone | (0, 209, 368, 239): Dex, his props, the action rail (left of Dex), the voice stream |
| Dex placement | hip anchor **(236, 379)**, scale **0.62**, full body, **identical on every screen** |

Accent candidates tested: purple `#B3A6FF`, gold, mint `#9FE3C4`
(`design/final/accent-compare.png`). **Gold picked by the owner, 2026-09-27.**

### 11.3 Surfaces (reference PNG → pose)

| # | Surface | Reference | Dex pose | Element budget |
|---|---|---|---|---|
| 1 | Home / Idle | `01-home.png` | idle hero, mug, steam | Dex + one status line ("Nothing needs you") |
| 2 | Listening | `02-listening.png` | lean-in, cupped hand | "I'm listening." + voice stream + separator-as-fuse (**25 s**: the firmware/UI listen limit) |
| 3 | Working | `03-working.png` | head down over phone | one-line what ("Asking Coach Beard…") + Cancel |
| 4 | Answer | `04-answer.png` | talking, palm toward answer | ≤ 60 words; footer is **server-set**: "Shortened. Ask Dex for the rest." (PROTOCOL clarification #5). The PNG still shows the old chat-app footer; **the contract wins**. |
| 5 | Decision | `05-decision.png` | holds up the "Yes" sign (the default) | question + "Default: …" + Yes / No / Later |
| 6 | Money preview | `06-money-preview.png` | bag at chest | merchant (18), **total (40) + currency code (32)**, items · ETA · place (18), "Hold Dex to order" (32/600, gold) |
| 7 | Money mid-hold | `07-money-mid-hold.png` | on toes, bag overhead (1.72×), filling gold | "Ordering…" (32) |
| 8 | Done | `08-done.png` | hands the full bag over, nod | "Ordered." + arrival. Shown only after the backend confirms. |
| 9 | Live tracker | `09-live-tracker.png` | arms folded, leans back, looks to the door, toe-tap | current stop 32 px, others 18 px |
| 10 | Pocket edition | `10-pocket-edition.png` | holds the paper open | masthead line + Read |
| 11 | Job done | `11-job-done.png` | shows phone | result + Send to Claude Code / Later |
| 12 | Night | `12-night.png` | asleep on stool (`PAL_NIGHT`) | no text; dim tokens only |
| 13 | Offline | `13-offline.png` | frowns at no-signal phone | "No connection" + Try again |
| 14 | Needs more | `14-needs-more.png` | shrug, palms up | question + two choice pills |

Reading-mode surfaces are in **§ 11.8**.

### 11.4 Motion (summary; `motion.md` is the source of truth)

25 fps (40 ms ticks). All character motion is sprite-frame swaps plus integer px offsets of the whole
sprite. Dex never scales or leaves the anchor. Idle breathing runs on a 4.0 s cycle (6.0 s at night),
with random blinks every 3–6 s. The voice stream travels edge-to-hand in 900 ms and spawns from mic
amplitude. The **hold fills the bag linearly over 2000 ms in 20 steps**; an early release drains it in
300 ms with no message. Content enters in 180 ms (40 ms stagger) and exits in 120 ms, so a state
change is about 400 ms total.

### 11.5 Copy rules

- The spoken reply is **≤ 2 sentences**; cards are **≤ 60 words**. Anything longer is never read aloud.
  The truncation footer is server-set: "Shortened. Ask Dex for the rest." Nothing goes to the main chat yet,
  so never claim it does.
- Headline-first and short ("Light day.", "Nothing needs you"). State the default and the deadline
  on decisions ("Default: yes, Sunday.").
- **Dex never promises to nudge, remind or ping.** He waits to be looked at.
- Don't write copy that explains the UI ("2 seconds, not a tap"). The design shows it.
- Never fake a state: no listening pose unless the mic is on, and no Done before the backend
  confirms. Stale data says so.
- Voice (critics picked it independently as the thing to keep): "Nothing needs you" is the house tone.

### 11.8 Reading mode (rendered 2026-09-27)

Source of truth: [`design/final/reading/reading.md`](design/final/reading/reading.md) and
`design/final/reading/*.png`. It uses
the same tokens, anchor, separator and gold accent as § 11.2. Dex wears reading glasses and holds an
indigo book (`#7274B8` / `#50529A` / `#3A3B72`, chosen to stay clear of the gold and the teal).

| # | Surface | Reference | Notes |
|---|---|---|---|
| R1 | Reading home | `r1-home.png` | Book title (32), author · chapter (18), the state line ("Quiet · text only"), one gold action naming the *other* state |
| R2 | Answer, lead | `r2-lead.png` | `body` lead at 18 px in one scroll column with `detail`; "Read more"; book · chapter bottom-left. Mouth stays closed in quiet mode. |
| R3 | Answer, detail scrolled | `r3-detail.png` | The one long-text surface. Rests on whole lines. The scroll cue is an FG2 segment riding the separator (not gold, not a pager). |
| R4 | Quiet (default) / Voice on | `r4-quiet.png`, `r4-speak.png` | The state is written in words. It changes only after the server confirms. A 1.6 s confirmation pose, then back to R1. |
| R5 | Text size | `r5-size-small.png`, `r5-size-large.png` | The reading detail scale is **18 / 22 / 26 px**, line height ≈ 1.45, used **only** in the detail view. Larger / Smaller actions. |
| R6 | Saved | `r6-saved.png` | The verbatim thought in quotes, plus book · chapter, and Dex tucking a note into the book. **Only after the store confirms; no ✓.** A failed save reuses the Offline pose. |

Sanctioned exceptions to § 11.6 (reading only): R5 reuses R3's pose (same surface, different size); R1
and R4-quiet share a layout; the separator carries the scroll cue; the lead is set at 18 px.
**Sprites:** +20 frames (glasses 2, book-hug 3, show-page 5, read/page-turn 3, shh 2, voice-on 2,
tuck 3), about 1.47 MB raw. Night variants are not budgeted (+20 if baked).

### Contract overrides (build wins over the render)

- Answer footer: "Shortened. Ask Dex for the rest." (server-set, PROTOCOL #5), not "Full version in <main chat>".
- Listening fuse: 25 s (firmware listen limit), not 30 s. The fuse spans 320 px over 25 s.

### 11.6 Pre-merge checklist (the bones + kill list, verbatim from `design/bones.md`)

Every UI PR must pass all of these on the simulator:
- [ ] No clock, time display or hero numerals. Times inside content are fine.
- [ ] Dex is full body, at the one anchor, at the one scale, on this screen. He is never cropped, cornered or hidden.
- [ ] This screen's Dex pose is unique (no reused gesture).
- [ ] At most 3 type sizes on the screen, from 18/24/32/40 only; secondary text ≥ `#BDBDBD`.
- [ ] One dominant element readable in 2 s (blurred-thumbnail test).
- [ ] The accent is used only for "you can act on this". No second accent, green check, teal or blue UI.
- [ ] No boxes, outlined cards or 1px borders. Type sits on true black.
- [ ] No blur, soft shadow, gradient or glass. Flat fills, strokes and sprites only.
- [ ] Night-safe: no large bright areas.
- [ ] Money: total is the largest text, the confirm is Dex's 2 s hold (never a tap), and mid-hold is visibly different from preview.
- [ ] On Listening, Decision, Money and Done, Dex is part of the interaction.
- Kill list: chat bubbles · tracked micro-caps eyebrow labels · badges, red dots, streaks · symmetric
  Siri waveform bars · Apple-Watch/Apple-Pay hold ring · equal-weight ✓/✗/⏰ icon row · renderer brand
  palettes (Claude orange-on-cream) · pixel-art UI or fonts · decoration pagers · hairline serifs ·
  sparkle "AI" icons · grey cards on AMOLED.

### 11.7 Sprites, and the character-swap contract

**Sprite format:**
- **Opaque RGB565, pre-composited on `#000`, with no alpha.** Every screen is true black behind Dex,
  so he must never be drawn over anything else.
- Accent overlays that touch him (the bag fill, the voice stream) are drawn by LVGL on top, never
  baked into the sprite.
- Cell **192×192** (it covers the bag-overhead lift).
- About **46 frames** for the base pose set plus reading.
- About 3.4 MB raw; compress with RLE or LZ4, which should give roughly 1–1.5 MB. Night frames bake
  `PAL_NIGHT`.
- Export the frames from `design/final/src/` (the poses are code), not by hand.

**Character-swap contract (added at the owner's request).** A future character can replace Dex without
a UI redesign if it meets all of these:
1. **The same pose list** as § 11.3, plus the idle, listening, speaking and hold frame sets in `motion.md`.
2. **The same style rules:** flat tonal steps (2–3 per material), one outline weight, no gradients,
   and a night palette variant.
3. **The same footprint:** it fits the 192×192 cell with its hip at the anchor (236,379), about
   211 px tall, and never enters the content zone above y=214.
4. **Hands, or an equivalent that can present things.** It must *hold* the Yes sign, the bag (the
   hold control) and the paper. A handless character forces a redesign of Decision, Money and Done.
5. **Its colours don't collide with the accent.** Gold was chosen partly because it contrasts with
   Dex's teal jacket.

Cost of a swap: one pose-sheet render and a new sprite export. Tokens, layouts and motion are
unchanged.

### 11.9 Coach Beard (rendered 2026-09-28)

The source of truth is [`design/final/coach/coach.md`](design/final/coach/coach.md). The poses are
code in `design/final/coach/src/` (`coach.py` imports `dex.py` read-only; `build_coach.py` renders
everything). Coach is the second character on the same body, under the § 11.7 contract. Tokens,
layout, motion, separator, anchor and the gold accent don't change. There's no name label: the
character is the cue.

- **Look:** an orange pom beanie with a navy cuff, a black headset with a boom mic, a full brown
  beard, and a steel whistle on a cord. An orange jacket with navy collar/hood, hem and sleeve
  bands, over a white/grey long sleeve. Brown trousers and dark shoes. His props are a spiral
  calendar with one date circled and a tablet showing a play ("watching film"). Night is
  `dex.dim_pal`.
- **Accent (rule 5):** the jacket is burnt orange **`#E07A45 / #C8551E / #9A3F14`**, chosen from
  four candidates (`accent-compare.png`). It's ΔE00 34.6 from the gold and 30 L* darker; the
  reference orange `#E8742C` (ΔE 26) collided. The circled date uses his orange, never gold.
  Rust `#A84E2E` is the device fallback.
- **Poses** (the `dex_sprite.h` names; 20 frames in `coach/frames/`, `<pose>-<n>.png`, 192×224
  cells on `#000`, hip (236,379), scale 0.62):
  - idle 3 (the whistle swings);
  - listening 2 (hand to headset);
  - working 2 (tablet);
  - speaking 2;
  - attention 1 (calendar at chest);
  - done 4 (thumbs-up, whistle in teeth, nod);
  - ask_yes 1 (calendar held up high, circled date toward you);
  - asleep 3 (seated, beanie down, night);
  - offline 1 (taps the dead headset);
  - error 1 (shrug).

  He has no money, tracker, paper or show-phone poses; those stay on the gray placeholder.
  The blink pairs and the idle glance are in `coach/frames-extra/`, because `export-coach` can't
  take them yet (coach.md § Open).
- **Surfaces:**
  - `c0-home.png`: idle, "Nothing needs you".
  - `c1-on-it.png`: "Coach is on it" (32) + "You can put it down." (18). No Cancel; it's a
    walk-away job.
  - `c2-call.png`: the Decision layout. The verdict "Start Purdy" (32), the deadline "Sun 12:00"
    (18) and the flip condition "Flip only if Purdy is out before Sun 12:00" (18, FG2). Actions:
    **Hear it** (the gold pill) / Why? / Later.
  - `c3-night.png`: asleep, dim tokens, no text.

  All four pass § 11.6 (coach.md has the table).

## Sources

- Meta Muse Charm coverage: TechCrunch 2026-09-23 and 2026-09-24; Meta Connect 2026 recap blog; Irish
  Times 2026-09-24; TechEBlog. Meta has published no official spec sheet; details are as reported.
- Margin, the author's earlier reading-companion prototype for the same board (unpublished).
- Dex's charter and the newspaper design system live with the agent, outside this repo.
