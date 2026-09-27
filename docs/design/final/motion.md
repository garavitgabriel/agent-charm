---
title: Dex Charm FINAL — motion spec
type: design-motion
created: 2026-09-27
---

# Dex Charm FINAL — motion spec

Target: LVGL on ESP32 at **25 fps (40 ms ticks)**. All character motion is swaps between pre-rendered sprite frames, plus integer px offsets of whole sprites. There is no blur, no soft easing on the character, and no scaling of Dex. Dex never leaves the anchor (236, 379).

## Idle: breathing and blink (Home, and under every other pose)

| Beat | Frames | Duration |
|---|---|---|
| Rest | idle-rest | 1600 ms |
| Inhale | whole body sprite −2 px | 400 ms (step at 200 ms: −1 px, then −2 px) |
| Hold | idle-inhaled | 1600 ms |
| Exhale | back to 0 px | 400 ms (two 1 px steps) |
| **Cycle** | | **4.0 s** |
| Blink | half → closed → half → open | 60 / 90 / 60 ms. Random interval 3–6 s, never during inhale. Every 5th blink is a double blink (150 ms gap). |
| Sip (Home only) | raise → sip (happy eyes) → lower | 400 / 1200 / 400 ms, every 20–40 s |
| Mug steam | 3-frame loop | 250 ms per frame |

Night: the breathing cycle stretches to **6.0 s** (2400 / 600 / 2400 / 600). There is no blink, only closed eyes. Steam runs at 400 ms per frame. There is no sip.

## Listening: voice stream

- The stream enters at the left screen edge, arcs over Dex's head and lands in the cupped hand. Path: cubic Bézier (−6, 322) → (90, 196) → (420, 190) → (306, 306).
- Capsules travel along the path from the edge to the hand. **Edge-to-hand transit is 900 ms**, advanced every 40 ms tick. A capsule is removed when it reaches the hand.
- Spawning comes from mic amplitude, sampled every **80 ms**. Above threshold, one capsule is spawned. Length is 4–12 % of the path and width is 4–10 px, both mapped from amplitude. Speech gives irregular capsules; silence gives no spawns.
- Capsules taper by position: full width near the edge, down to 4 px at the hand.
- After silence longer than **1.2 s**, the stream drains (no new capsules) and Dex's head eases back 1 frame.
- Dex while voice is present: head bob, 2 frames, 300 ms each.
- 30 s allowance: the separator's accent segment grows left → right from 0 to 320 px over 30 s. Redraw every 250 ms (≈ 2.7 px per step). There are no numerals. When it reaches 344, the recording ends as if the button were released.
- Enter: the stream's first capsule leaves the edge 120 ms after the button goes down. Exit (release): remaining capsules finish their transit (≤ 900 ms). The fuse fades out over 200 ms. Cross to Working.

## Money: the 2-second hold

| t (ms) | Bag fill | Pose |
|---|---|---|
| 0 | 0 % | Preview (bag at chest) |
| 0–200 | fills | 2 in-between frames at 100 ms: arms rise |
| 200–400 | fills | lift frame: bag goes overhead, up on his toes |
| 400–2000 | fills | Lift held. The bag bobs 1 px every 200 ms. |
| 2000 | 100 % | Full frame held **120 ms** |
| 2120 | — | Cut to Done (hand-off) |

- Fill: **linear 0 → 100 % over 2000 ms**, bottom → top inside the bag clip, drawn in **20 steps (100 ms each)**. The fill edge carries a 2.5 px ink line.
- Label: "Hold Dex to order" swaps to "Ordering…" on the first tick of the hold.
- Early release: the fill drains to 0 in **300 ms** (linear, 3 steps). The pose returns through the in-betweens in 200 ms and the label swaps back. No message is shown.
- Done: nod. The head goes +4 px, then +7 px, then +4 px, then 0 over 480 ms (4 frames at 120 ms), once. The bag is held out, full accent, and does not animate further.

## Content ("card") enter and exit

This applies to the content zone above the separator. Dex, the separator and the rail do not move with it.

- **Enter:** each text line fades 0 → 100 % opacity and moves up 8 → 0 px over **180 ms**, ease-out (cubic). Lines are staggered by **40 ms**, top to bottom. The rail actions enter last, fade only, 120 ms.
- **Exit:** all content fades 100 → 0 % over **120 ms**, ease-in, with no movement and no stagger.
- Between states: exit (120 ms) → Dex pose swap (2 cross frames × 80 ms, same anchor) → enter (180 ms + stagger). Total is about 400 ms for a 3-line screen.
- Tap feedback on an action: the pill or text drops to 70 % for 80 ms, then the exit begins.
- Working: "…" steps through 1 / 2 / 3 dots every 400 ms. Dex's thumb-tap loop has 2 frames at 300 ms. Cancel uses the standard exit.
- Tracker: when the stage advances, the old headline (32) shrinks to an 18 px row by swapping font. It does not scale. The next stop swaps to the 32 px line. Both happen within 120 ms. The dot grows 5 → 8 px in 2 steps.
