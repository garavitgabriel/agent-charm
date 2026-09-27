---
title: Dex Charm FINAL — tokens
type: design-tokens
created: 2026-09-27
source: src/build.py (values below are the exact constants used)
---

# Dex Charm FINAL — tokens

Screen: 368 × 448 px, portrait, true black `#000000`. All values are in device px at 1×.

## UI palette

| Token | Hex | Use |
|---|---|---|
| `BG` | `#000000` | Background, every screen |
| `FG` | `#F2EFE9` | Primary text |
| `FG2` | `#D6D3CC` | Secondary text and completed tracker stops (≥ `#BDBDBD`; one step brighter than BCKO `#C4C1BA`) |
| `ON_ACC` | `#0B0A12` | Text set on an accent fill (pills, placard) |
| `LINE` | `#3B3A40` | Separator rule; upcoming tracker stop ring and track |
| `FLOOR` | `#141316` | Dex's ground shadow |
| `LINE_N` | `#1C1B20` | Separator, night |
| `FLOOR_N` | `#0A0A0C` | Ground shadow, night |
| `ACC_N` | `#5E4A1C` | Dimmed gold, the accent at night. Nothing on Night is bright. The rendered Night screen has no accent element; use this for any night action or fill. |

Night uses no UI text and no full-brightness accent. The character switches to `PAL_NIGHT` from `dex.py`, the locked dim palette.

### Accent: one accent, one meaning ("you can act on this")

Each candidate has three steps. The base is used for UI. The side-plane and highlight steps appear only inside accent-owned props (the placard and the filled bag).

**Chosen: B, warm gold.** It is used on all 14 screens.

| Token | Hex |
|---|---|
| `ACC` | `#F2C14E` |
| `ACC_D` (side plane) | `#D19F2B` |
| `ACC_L` (highlight) | `#F9DC94` |
| `ACC_N` (night) | `#5E4A1C` |

Rejected candidates, kept for reference (see `accent-compare.html`, `accent-a.png`, `accent-c.png`):

| Candidate | Base | Side plane | Highlight |
|---|---|---|---|
| A: purple (BCKO) | `#B3A6FF` | `#8E7FEA` | `#D4CCFF` |
| C: soft mint | `#9FE3C4` | `#6CC39D` | `#CBF3E0` |

Where the accent appears: text actions, filled pills, the decision placard, the bag fill (mid-hold and Done), the voice stream and the elapsed part of the listening fuse. Nothing else uses it.

Character colours are locked and taken from `dex.py` `PAL`. The UI uses no other colour.

## Type

- Family: **Instrument Sans** (Google Fonts), weights 400 / 500 / 600. Fallback: `'Helvetica Neue', Arial, sans-serif`.
- Fixed sizes: **18 / 24 / 32 / 40 px**. No other size exists. Each screen uses at most 3 of them.
- Line height = round(size × 1.18): 18→21, 24→28, 32→38, 40→47. Buttons use a 28 px line height.
- Letter spacing: −0.4 px at 32 and 40; −0.1 px at 18 and 24.

| Size | Weight | Role |
|---|---|---|
| 40 | 500 | The money total only (`$58.400`). The largest text anywhere. |
| 32 | 500 / 600 | Headline (the spoken line). The tracker's current stop. On the money screens: "COP" (set on the total's row), "Hold Dex to order" and "Ordering…" (600, accent, 36 px line height). |
| 24 | 500 / 600 | Answer rows, Done second line. All other actions (600). |
| 18 | 400 / 500 | Secondary text (FG2, 400). The money merchant name (FG, 500). |

Money screens (6, 7) use exactly 18 / 32 / 40.

Suggested LVGL bitmap fonts: `instrument_18_400`, `instrument_18_500`, `instrument_24_500`, `instrument_24_600`, `instrument_32_500`, `instrument_32_600`, `instrument_40_500`.

## Spacing

- Scale: **4 / 8 / 16 / 24 / 32 px**. The outer gutter `PAD` is 24.
- Text blocks start at y = 24. Gaps between lines follow the line heights plus 4–10 px (headline to secondary: 46 px baseline step at 32 → 18).
- Touch targets are at least 56 px tall. Pills are 56 px, or 72 px for two lines, with a 28 px radius and 14–20 px side padding. Text actions have a 56 px transparent hit box.
- No outlines, borders or card boxes anywhere. The only strokes are the separator and the tracker track (3 px).

## Zones

| Zone | Rectangle (x, y, w, h) | Notes |
|---|---|---|
| Content zone | (24, 24, 320, 166) | Reading content. Nothing below y = 190. |
| Separator | line (24, 206) → (344, 206), 3 px, round caps | On every screen. It is the listening fuse on screen 2. |
| **Anchor zone** | **(0, 209, 368, 239)** | Dex, his props, the action rail and the voice stream |
| Action rail | (24, 222, ≤172, 210) | Left of Dex, inside the anchor zone. Actions sit here. |

## Dex placement (identical on every board)

- Hip anchor: **(236, 379)**
- Scale: **0.62**, applied to the locked `dex.py` figure units
- Ground shadow: ellipse centred at (236, 433), rx 46, ry 7.4
- Footprint at 0.62: the tallest hair tuft is at about y = 222 and the shoe soles at about y = 433, so the full body is about 211 px tall. Raised props stay below y = 214. On the decision screen the placard centre is (307, 261).
- No crop, no corner mini, no second scale. The seated night pose keeps the same hip anchor. All 14 boards use this placement.

## Screen → pose (no pose repeats)

| # | Screen | Pose |
|---|---|---|
| 1 | Home | idle hero: mug raised, steam |
| 2 | Listening | MZCL lean-in, cupped hand at the ear |
| 3 | Working | head down over his phone |
| 4 | Answer | talking, palm raised toward the answer |
| 5 | Decision | holds up the "Yes" placard |
| 6 | Money preview | bag held at the chest, both hands |
| 7 | Money mid-hold | on his toes, one arm lifting the filling bag (scale 1.72, 60 % gold) overhead |
| 8 | Done | steps forward, hands over the full bag, eyes closed in a nod |
| 9 | Live tracker | arms folded, leaning back, eyes on the door, toe tapping |
| 10 | Pocket edition | holds tonight's paper open |
| 11 | Job done | holds his phone up to show you |
| 12 | Night | asleep on the stool, mug steaming (`PAL_NIGHT`) |
| 13 | Offline | frowns at a no-signal phone |
| 14 | Needs more | shrugs with both palms up |
