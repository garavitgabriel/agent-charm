---
title: Dex Charm FINAL: Coach Beard
type: design-character
created: 2026-09-28
source: src/coach.py (character + poses), src/build_coach.py (screens, sheet, accent test, frames)
---

# Coach Beard

Coach Beard is the charm's second character (the `coach` Hermes profile; plan in `docs/COACH.md`).
He follows the BRIEF § 11.7 character-swap contract. The design system does not change: § 11
tokens, layout, motion, separator, anchor and the one gold accent. He is drawn smooth in Dex's
idiom. The pixel reference (`docs/coach/coach-reference.jpg`) is used for identity only.

**Look at these:** `coach-sheet.png` (every pose), `c0-home.png`, `c1-on-it.png`, `c2-call.png`,
`c3-night.png`, `accent-compare.png`, and `frames/` (the sprite set).

## How he's built

- `src/coach.py` imports `dex.py` read-only and reuses its primitives unchanged: `hand`, `leg`,
  `shoe`, `ell/path/line/g`, the face outline and eye/mouth vocabulary, and `dim_pal` for night.
  New parts: the pom beanie (a navy ribbed cuff and a tag), the headset (the band over the beanie,
  ear cups, a boom mic and an LED), the full beard with a mustache, the whistle on a cord, a jacket
  torso (navy collar/hood, hem and zip), a two-tone arm (the jacket upper arm with a navy band over
  a grey long-sleeve forearm), and the props (a spiral calendar with a circled date, a tablet
  showing a play diagram, a thumbs-up hand).
- `coach.figure()` keeps Dex's keyword schema (`dex.DEFAULT`), so a `dex_export`-style capture can
  record Coach's poses the same way it records Dex's.
- The style rules are Dex's: 3 flat tonal steps per material, one ink `#1B1412`, the 3 px outline
  weight, and no gradients, blur or glass.
- Footprint: the hip is at (236, 379), scale 0.62 (via `build.place`), in the 192×224 cell at
  (160, 218). Every frame is checked with resvg (the exporter's renderer). The extents run from
  y = 223 to 441 and from x = 173 to 320, so nothing is above y = 214 and nothing is outside the
  cell.
- Nothing under `final/src/` or `reading/` was edited. Scripts run with `sys.dont_write_bytecode`
  so no `__pycache__` lands in `final/src`.

## Palette (`coach.PAL`; night = `dex.dim_pal(PAL)` = `coach.PAL_NIGHT`)

| Material | Highlight | Base | Side plane | Note |
|---|---|---|---|---|
| Jacket, beanie, calendar header (**burnt orange**) | `#E07A45` | **`#C8551E`** | `#9A3F14` | Chosen by the accent test below |
| Navy trim (cuff, collar/hood, hem, sleeve band) | `#44557F` | `#2B3A60` | `#1C2744` | |
| Long sleeve (forearms) | `#E6E9EC` | `#C3C9CF` | `#949CA5` | White/grey |
| Beard | `#8E5A38` | `#6A4029` | `#4A2A1B` | Brows `#4A2A1B` |
| Skin | `#F6CBA4` | `#E4A67C` | `#C4825C` | A shade ruddier than Dex |
| Trousers (brown) | `#B88A5E` | `#96693F` | `#6E4B2B` | |
| Shoes (dark) | `#5E636C` | `#43474F` | `#2C2F35` | |
| Headset | `#4A4F58` | `#30343B` | `#1E2126` | LED `#AEB8BF` (grey, never green) |
| Whistle (steel) | `#E4E8EC` | `#AEB6BE` | `#7D868F` | Cord `#2A3038` |
| Calendar page | `#FFFFFF` | `#E9EEF0` | `#C3CDD2` | The circled date uses his orange side plane `#9A3F14`, **never gold** |

### Accent check (§ 11.7 rule 5): `accent-compare.png`

I rendered the Coach's-call screen, where the gold "Hear it" pill sits right next to him, with
four jackets. CIEDE2000 against the gold `#F2C14E`:

| Candidate | Jacket base | ΔE00 vs gold | vs gold side `#D19F2B` | L* (gold 80.5) |
|---|---|---|---|---|
| Dex teal (the baseline) | `#1F97A6` | 45.4 | 43.0 | 57.2 |
| A: the reference orange | `#E8742C` | 26.1 | 21.1 | 61.5 |
| **B: burnt (chosen)** | **`#C8551E`** | **34.6** | **28.0** | **50.5** |
| C: rust | `#A84E2E` | 39.7 | 32.7 | 44.2 |
| D: navy jacket, burnt trim | (beanie `#C8551E`) | 34.6 | 28.0 | 50.5 |

- **A fails.** At 26 ΔE, the bright orange and the gold read as one warm family, so the pill stops
  being the only "hot" thing on the screen.
- **B is chosen.** It sits 30 L* below the gold, and its hue moves toward red. On the render the
  gold pill and text are clearly the brightest, lightest warm element, and he still reads as
  "orange coach".
- C clears the gold further but goes muddy brown next to the beard and trousers. It's the
  fallback if the device panel makes B read too close.
- D keeps the most distance on the body but loses the reference's identity (orange jacket).
- The gold itself is unchanged.

## Poses and frames (`frames/`, export-coach input)

The names follow `ui/dex_sprite.h`. `export-coach` gives Coach Dex's timing **by frame index**, so
the counts match Dex's manifest:

| Pose | Frames | Timing (from Dex) | What he does |
|---|---|---|---|
| `idle` | 3 | 250 ms loop, breath day | Calendar tucked under his arm. The whistle swings on its cord (Dex's steam slot). |
| `listening` | 2 | 300 ms | Leans in, hand pressed to the headset's ear cup, 2-frame head bob |
| `working` | 2 | 300 ms | Head down over the tablet ("watching film"); the play route draws a step further on frame 1 |
| `speaking` | 2 | 200 ms | Palm lifted toward the answer; mouth open / "o" |
| `attention` | 1 | 1000 ms | Looks at you, holding the calendar at his chest with both hands |
| `done` | 4 | 120 ms, holds the last | Thumbs-up, whistle in his teeth, eyes creased; the nod is head +4 / +7 / +4 / 0 |
| `ask_yes` | 1 | 1000 ms | Holds the calendar up high beside his head, circled date toward you (his "call") |
| `asleep` | 3 | 400 ms, breath night | Seated on the stool, beanie pulled over his eyes, LED off, `PAL_NIGHT`; slow head sway |
| `offline` | 1 | 1000 ms | Taps the dead headset: the LED is off and the boom mic droops |
| `error` | 1 | 1000 ms | Shrug, both palms up, one brow up |

That's 20 frames, 192×224 cells, opaque on `#000` with the ground shadow baked in. I verified them
through `charm_assets.coach.export()` into a scratch folder: all 10 poses load with the timing
above. Nothing under `ui/` or `tools/` was written. There are no money, tracker, paper, show-phone
or reading poses: those stay on the gray placeholder, by design.

`frames-extra/` holds frames the current exporter **can't take**, because it only accepts
`<pose>-<n>` sequences:
- the blink half/closed pairs for every open-eyed frame (`<frame>-half.png`, `<frame>-closed.png`,
  18 files);
- `idle-glance.png`, the idle beat (Dex's sip slot).

**Don't put them into `frames/`,** or `export-coach` rejects the names.

## Re-export

```sh
cd docs/design/final/coach/src
PY=../../../../../tools/.venv/bin/python     # any Python with resvg-py 0.5.0 + pillow (tools' venv)
$PY build_coach.py --frames   # -> ../frames/*.png, ../frames-extra/*.png (fails if anything leaves the cell)
$PY build_coach.py            # -> ../c0..c3.png, ../coach-sheet.png, ../accent-compare.png (headless Chrome)
cd ../../../../../tools && uv run charm-assets export-coach ../docs/design/final/coach/frames
```

The screens use the same Chrome screenshot path as `build_reading.py`, with a per-call profile.
Each shot can take up to about 45 s.

## Surfaces

| # | File | Pose | Content |
|---|---|---|---|
| C0 | `c0-home.png` | idle | "Nothing needs you" (24, FG2), the same as Dex's 01-home |
| C1 | `c1-on-it.png` | working | "Coach is on it" (32) + "You can put it down." (18, FG2). **No Cancel** (a background job). |
| C2 | `c2-call.png` | ask_yes | "Start Purdy" (32); "Sun 12:00" (18, FG2); "Flip only if Purdy is out before Sun 12:00" (18, FG2). Actions: **Hear it** (gold pill, primary), Why? and Later (gold text). |
| C3 | `c3-night.png` | asleep | No text, `LINE_N` / `FLOOR_N`, `PAL_NIGHT` |

## § 11.6 checklist, per screen

| Check | C0 | C1 | C2 | C3 |
|---|---|---|---|---|
| No clock / hero numerals (times inside content are fine) | ✓ | ✓ | ✓ ("Sun 12:00" is content) | ✓ |
| Full body, one anchor, one scale | ✓ | ✓ | ✓ | ✓ (seated, same hip) |
| Pose unique on this screen | ✓ idle | ✓ working | ✓ ask_yes | ✓ asleep |
| ≤ 3 type sizes from 18/24/32/40; secondary ≥ `#BDBDBD` | ✓ 24 | ✓ 32/18 | ✓ 32/18/24 | ✓ none |
| One dominant element in 2 s | ✓ | ✓ headline | ✓ verdict | ✓ |
| Accent only for "you can act" | ✓ none | ✓ none | ✓ the 3 actions only (the circled date is his orange) | ✓ none |
| No boxes / outlined cards / 1px borders | ✓ | ✓ | ✓ | ✓ |
| No blur / soft shadow / gradient / glass | ✓ | ✓ | ✓ | ✓ |
| Night-safe | ✓ | ✓ | ✓ | ✓ (dim palette; the moon is capped at `#B4`) |
| Money rules | n/a | n/a | n/a | n/a |
| Character part of the interaction (Decision-type) | n/a | n/a | ✓ he holds up the call | n/a |
| Kill list (bubbles, eyebrow labels, badges, Siri bars, hold ring, ✓✗⏰ rows, pixel art…) | ✓ | ✓ | ✓ | ✓ |

- **Pose reuse across characters:** C1 reuses the Working slot's layout and C2 reuses the Decision
  layout, as COACH.md intends. Each Coach screen still has its own Coach pose.
- **No name label.** The character is the identity cue.

## Open / couldn't do

1. **Blinks and the idle beat aren't playable yet.** `export-coach` takes only `<pose>-<n>`
   sequences and gives no `blink`/`sip` slots. The art is in `frames-extra/`. Suggested tools
   change (a chief call, not mine): accept `<pose>-<n>-half|closed.png` and
   `idle-glance-<n>.png` and map them onto Dex's blink/sip.
2. **No `points` metadata.** The voice stream lands in Dex's `DEX_POINT_HAND`, and the UI falls
   back to fixed coordinates. Coach's listening hand is at the ear cup (about screen (278, 300)),
   not Dex's cupped hand. The builder should check the stream endpoint on Listening.
3. **COACH.md said "Got it / Why?"; this brief said "Hear it / Why? / Later".** I rendered the
   brief's version. The server `call` card needs to match.
4. **Accent read on the real AMOLED:** B was chosen on sRGB renders. Confirm on the device, and
   fall back to C (rust) if the pill loses.
5. **BRIEF § 11.7 still says a 192×192 cell.** The pipeline (tools/README) and these frames use
   192×224. The chief should reconcile the text.
6. Sprite budget: 20 frames (+19 if the blinks/glance land), about half of Dex's base set.
   `charm-assets budget` wasn't run, because it would write through `ui/`.
