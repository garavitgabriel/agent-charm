---
title: Dex Charm FINAL — reading mode
type: design-spec
created: 2026-09-27
source: src/build_reading.py (imports ../../src unchanged; every value below is a constant there)
related: [../tokens.md, ../motion.md, ../../../BRIEF.md, ../../../PROTOCOL.md]
---

# Dex Charm FINAL — reading mode (R1–R6)

These screens extend the final system and don't restyle it. Everything from `tokens.md` still applies:
true black, FG/FG2, gold `#F2C14E` used only for "you can act", the separator at y = 206, the content
zone (24, 24, 320, 166) and Dex at hip (236, 379), scale 0.62, full body.

| File | Surface | Dex pose |
|---|---|---|
| `r1-home.png` | Reading home (quiet, the default) | book-hug: glasses on, the book held to his chest |
| `r2-lead.png` | Answer, lead (top of the scroll column) | show-page: holds the open page out to you and nudges his glasses |
| `r3-detail.png` | Answer, detail scrolled (22 px, default) | read: cover toward you, eyes down on the page |
| `r4-quiet.png` | Toggle confirmed: quiet | shh: finger to his lips, book under his arm |
| `r4-speak.png` | Toggle confirmed: voice on | crier: open book raised beside his head, chin up |
| `r5-size-small.png` / `r5-size-large.png` | Detail at 18 px and at 26 px | read (same surface as R3) |
| `r6-saved.png` | Saved notice (only after the store confirms) | tuck: presses the note down into the book, eyes closed in a nod |
| `reading-sheet.png` | All eight side by side | |

## Tokens added

**Reading type scale.** This scale is used only by the answer `detail`, and it's the one exception to
the 18/24/32/40 rule. Each step has its own line height and a viewport of whole lines, so at rest the
scroll view never shows a clipped line.

| Token | Size | Line height | Lines visible | Viewport (y from 24) | Weight / colour |
|---|---|---|---|---|---|
| `READ_S` | 18 px | 26 px | 6 | 156 px (to y = 180) | 400, `FG2`; paragraph lead-ins 600, `FG` |
| `READ_M` (default) | 22 px | 32 px | 5 | 160 px (to y = 184) | same |
| `READ_L` | 26 px | 38 px | 4 | 152 px (to y = 176) | same |

- Letter spacing is −0.1 px at every step.
- Paragraphs are separated by exactly one empty line (margin = line height), so the whole detail stays
  on one line grid.
- Suggested LVGL fonts: `instrument_22_400`, `instrument_26_400`, `instrument_22_600`,
  `instrument_26_600`. The 18 px step reuses `instrument_18_400` and needs a new `instrument_18_600`.
- **The lead** (`body`, ≤ 60 words) uses the system step: 18/500 `FG`, 21 px line height. A 45-word
  lead takes 7 lines (147 px). A 60-word lead runs to about 10 lines, which is more than the content zone
  holds, so the lead is the top of the same scroll column rather than a fixed card (see R2).

**Scroll cue.** The separator doubles as the scroll track. The thumb is an `FG2` segment, 3 px with round
caps, riding on the `LINE` rule:
`len = max(24, 320 × view / total)` and `x = 24 + (320 − len) × offset / (total − view)`.
It isn't the accent, because it isn't an action. It isn't a pager either, because there are no dots and
no pages. If the column fits the viewport, there's no thumb.

**Character colours (props only, never UI).** These are added to the character palette. At night they
go through `dex.dim()` like every other character colour.

| Name | Hex (lit / side / shadow) | Use |
|---|---|---|
| `book` | `#7274B8` / `#50529A` / `#3A3B72` | Book cover (indigo). It clears both the gold accent and the teal jacket. |
| glasses frame | `ink` `#1B1412` | Reading glasses: the one outline ink, 3.4 units. There's one flat `eyehi` glint per lens and no lens tint. |
| pages, note | `shirt` tones | Pages and the note card; the text marks use `line` |

## Element budget per surface

| Surface | Content zone | Anchor zone (rail, left of Dex) | Type sizes | Accent |
|---|---|---|---|---|
| R1 Reading home | title (32), author · chapter (18 FG2), mode status "Quiet · text only" (24 FG2, the Home status slot) | "Turn voice on" | 32 / 24 / 18 | the toggle only |
| R2 Lead | the lead, 18/500 FG, top of the scroll column | "Read more" (top); book title (18 FG) + "Clarke · ch 7" (18 FG2) at the foot, like Answer's footer | 18 / 24 | "Read more" |
| R3 Detail | the scroll view (READ_M), nothing else | "Larger" / "Smaller" stacked, up above down | READ_M + 24 | the size control |
| R4 Quiet | as R1 | "Turn voice on" | 32 / 24 / 18 | the toggle |
| R4 Voice on | as R1, status "Voice on · lead only" | "Go quiet" | 32 / 24 / 18 | the toggle |
| R5 Small / Large | the scroll view at READ_S / READ_L | only the control that can still act: "Larger" at 18 px, "Smaller" at 26 px | READ + 24 | the size control |
| R6 Saved | "Saved." (32), the verbatim thought in quotes (24 FG) | book title + chapter (18 FG2) at the foot | 32 / 24 / 18 | none (nothing to act on) |

- **Speak/quiet at a glance.** The mode is said in words, in the slot Home uses for its one status
  line: "Quiet · text only" or "Voice on · lead only". The rail's single gold action always names the
  other state. There's no badge, dot or icon. On R2 and R3 the mode shows through Dex instead. In quiet
  mode his mouth stays closed on the lead, because a talking mouth there would fake speech. In voice
  mode the R2 pose uses the speaking mouth frames while the lead is playing.
- **The state comes from the server echo** (PROTOCOL, `setting`). The status line changes only when the
  echo arrives, never on the tap itself.
- **Saved** appears only for `notice{data.saved:true}`. The thought is shown verbatim, in curly quotes,
  and never paraphrased. On `saved:false` the notice renders the same way with the headline "Not saved."
  and Dex's Offline frown. No new pose is needed for that.

## Gestures

| Where | Gesture | Result |
|---|---|---|
| Reading home | tap "Turn voice on" / "Go quiet" (56 px hit box) | Sends `setting{speech}`. The label drops to 70 % for 80 ms and the state flips on the echo (R4). |
| Anywhere | hold BOOT | Talk, unchanged. "Save this: …" goes to Saved; any other speech is a question. |
| R2 | tap "Read more", or drag up in the content zone | Scrolls to the first detail line; Dex swaps to the read pose |
| R2 / R3 | drag in the content zone | Scrolls 1:1. A flick keeps momentum. |
| R2 / R3 | tap the lower half of the content zone | Pages forward by (lines − 1), keeping one line of context. The upper half pages back. One thumb, no precision needed. |
| R3 / R5 | tap "Larger" / "Smaller" | Steps READ_S ↔ READ_M ↔ READ_L. At an end, that control isn't drawn. |
| R2 / R3 / R6 | swipe right | Back one level: detail → lead → reading home |

## New sprite frames (192 × 192, opaque RGB565 on `#000`)

| Pose | Frames | Count |
|---|---|---|
| Glasses on/off (entering or leaving reading mode) | reach, glasses on | 2 |
| R1 book-hug | rest, blink-half, blink-closed | 3 |
| R2 show-page | rest, blink-half, blink-closed, mouth-open, mouth-mid (the last two only when voice is on) | 5 |
| R3/R5 read | rest, page-turn A, page-turn B (eyes are down, so there's no blink) | 3 |
| R4 shh | finger rising, finger at lips | 2 |
| R4 crier | book rising, book up | 2 |
| R6 tuck | note above, note half in, note in + nod | 3 |
| **Total** | | **20** (about 1.47 MB raw at 73,728 B each; roughly 0.4–0.6 MB after RLE/LZ4) |

- Breathing uses the shared whole-sprite offset, so it needs no frames.
- No reading prop goes outside the extents of the final set. The highest point is the raised book on
  R4 voice on, whose top is at y ≈ 262 (the limit is 214). The rightmost point is the book or note on
  R6, at x ≈ 290.
- Night copies (`PAL_NIGHT`, via `book_cols()`) aren't budgeted here. Baking the reading poses for
  night adds another 20 frames.
- The poses are code: `pose_book_hug`, `pose_show_page`, `pose_read`, `pose_shh`, `pose_call` and
  `pose_tuck` in `src/build_reading.py`. The glasses are a head overlay applied through the `@reading`
  decorator.

## Motion

All timings are in 40 ms ticks. Content enter and exit follows `motion.md` (180 ms up-and-fade with a
40 ms stagger in, 120 ms fade out).

- **Scroll.** The column moves in integer px inside a clip of exactly the viewport. Drag is 1:1; a flick
  uses LVGL momentum with its default deceleration. On release, the column **snaps to the line grid**
  in 160 ms (ease-out) so no half line is left showing. A page tap takes 240 ms (ease-out). The
  separator thumb moves every tick with the column. Nothing fades at the edges: there's a hard clip,
  because gradients aren't allowed.
- **Lead → detail.** "Read more" scrolls the column to the first detail line in 240 ms. When the lead
  has left the viewport, Dex swaps from show-page to read using 2 cross frames × 80 ms. Scrolling back
  up past the lead's last line reverses that.
- **Page turns.** Each time a page tap or a scroll passes a full viewport, Dex plays page-turn A → B →
  rest (80 / 80 / 120 ms). A drag with no page crossing plays nothing.
- **Text size.** The controls are text actions. The old size fades out (120 ms), the column re-flows,
  and the paragraph that was at the top stays at the top, snapped to its line. The new size fades in
  (180 ms). The thumb jumps to the new position without animating. Dex doesn't react.
- **Speak/quiet toggle.** On tap, the label drops to 70 % for 80 ms. On the echo, the status line exits
  (120 ms) and re-enters with the new words (180 ms), and the rail label swaps at the same moment. Dex
  crosses to shh or crier (2 × 80 ms), holds for **1600 ms**, then crosses back to book-hug. If no echo
  arrives within 3 s, the label returns to 100 % and nothing changes, so the device never fakes the
  toggle.
- **Saved.** This plays on `notice{saved:true}` only (after `state{working, label:"Saving"}`, the
  Working screen). The sequence is note above → half in → in + nod, at 120 / 120 / 480 ms, played once.
  The text enters as standard content. There's no ✓ and no check animation.

## Rules bent, and why

1. **R5 reuses R3's pose.** R5 isn't a new surface; it's R3 at a different setting. The "unique pose"
   check is applied per surface.
2. **R1 and R4-quiet share a layout** and differ only in Dex's pose. R4 is the 1.6 s confirmation
   moment after a toggle; R1 is the rest state it settles back to. In voice mode, the resting home is R1
   with R4-speak's words.
3. **The reading scale adds 22 and 26 px and looser line heights (≈ 1.45 instead of 1.18).** These
   were requested as a separate token set, and prose at 1.18 is too tight to read for more than 10
   seconds. They're used only inside the detail scroll view.
4. **The lead is set at 18, not 24,** and it scrolls when it's long. At 24, a 60-word lead can't fit the
   166 px content zone, and even at 18 it's about 10 lines. That's why the lead and the detail share one
   column instead of the lead being a fixed card.
5. **The separator carries a second meaning** (the scroll thumb, in FG2). The final system already
   uses it as the listening fuse (in gold), so this repeats that precedent in a non-action colour.
