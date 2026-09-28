# charm-assets — sprites and fonts → device-ready code

`charm-assets` turns the design sprint's sprite sheets and chosen fonts into C++ that both the
firmware and the Mac simulator compile unchanged (both builds glob `ui/*.cpp`):

| Command | Writes |
|---|---|
| `uv run charm-assets export-dex` | `ui/assets-src/dex/`: the smooth Dex rendered from the design source, one PNG per frame + `manifest.json` |
| `uv run charm-assets sprites MANIFEST` | `ui/charm_assets_sprites.{h,cpp}`: the frames + the pose × outfit table (smooth LZ4 RGB565, or indexed pixel art) |
| `uv run charm-assets fonts MANIFEST` | `ui/charm_assets_fonts.{h,cpp}`: `lv_font_t` per face × size, through `lv_font_conv` |
| `uv run charm-assets check MANIFEST` | nothing: validates, prints the RGB565 palette report, flash sizes and the poses still on the gray placeholder |
| `uv run charm-assets budget MANIFEST` | nothing: raw / RLE16 / LZ4 bytes per pose vs the 6.25 MiB app partition and the built firmware |
| `uv run charm-assets strips MANIFEST` | `out/dex-strips/<pose>-<outfit>.png`: every frame side by side, decoded from the generated LZ4, points outlined |
| `uv run charm-assets dummy` | `fixtures/dummy/dummy-sheet.png`, the fake test sheet |

Add `--check` to `sprites`/`fonts` to fail (exit 1) when the committed files are stale. Output is
deterministic: the same inputs produce the same bytes. Every generated file starts with a
`GENERATED — do not edit` banner naming the command and the sha256 of each input.

```sh
cd tools
uv run charm-assets sprites fixtures/dummy/manifest.json
uv run charm-assets fonts fixtures/dummy/manifest.json    # needs Node (npx) for lv_font_conv
uv run ruff check . && uv run mypy src && uv run pytest -q
```

Then rebuild: `cmake --build build/sim && ./build/sim/charm-sim --shots out/shots`, and
`cd firmware && pio run -e charm`.

## The smooth Dex (the real art)

Dex is a smooth illustrated character (BRIEF § 11). **The poses are code**, in
`docs/design/final/src/{dex,sheet,build}.py` plus the reading mode's
`docs/design/final/reading/src/build_reading.py`, so nobody exports frames by hand.

### Re-export after a pose tweak (design session)

```sh
cd tools
uv run charm-assets export-dex                                   # docs/design -> ui/assets-src/dex
uv run charm-assets sprites ../ui/assets-src/dex/manifest.json  # -> ui/charm_assets_sprites.*
uv run charm-assets budget ../ui/assets-src/dex/manifest.json   # sizes vs the flash budget
uv run charm-assets strips ../ui/assets-src/dex/manifest.json   # -> out/dex-strips/ for review
uv run ruff check . && uv run mypy src && uv run pytest -q
```

Then rebuild the sim and the firmware (see above). `export-dex` imports the design modules
read-only: it writes no bytecode or file next to them. It renders with resvg (`resvg-py`, pinned),
which matches the Chrome-rendered reference PNGs, and it's deterministic. `pytest` checks that a
fresh export reproduces the committed frames byte for byte.

**What `export-dex` does.** `tools/src/charm_assets/dex_export.py` (`frame_set()`) lists every frame:

- It calls each design pose function with `figure()` swapped for a recorder. That captures the pose's
  parameters, and the props (`mug`, `takeout_fill`, `note_card`) remember their arguments.
- Motion frames that the design describes but doesn't draw are that same call with one design
  parameter changed:
  - blinks: `eyes="down"` for half, `"blink"` for closed;
  - steam: the mug's `lean`;
  - head bob and nod: `head_dy`;
  - toe-tap: `shoeR`;
  - speaking mouth: `mouth="o"`.
- The lift in-betweens interpolate `pose_offer_bag` → `pose_lift` at ⅓ and ⅔.
- Every such choice is listed in `EXPORT_NOTES`, which ends up in the manifest's `_notes`.
- To add or retime a frame, edit `frame_set()` and re-run. To change how Dex looks, edit the design
  source and re-run. Never edit the PNGs or `manifest.json` by hand.

### Format and geometry

| | |
|---|---|
| Pixels | Opaque RGB565 (little-endian, `LV_COLOR_16_SWAP 0`), pre-composited on `#000`, with Dex's ground shadow baked in. No alpha: every screen is true black behind Dex. |
| Cell | **192 × 224**, top-left on screen at (160, 218). The width is the designed 192 px; the height is 224 because Dex is ~211 px tall, plus the shadow and the lifted bag. A 192-px-tall cell would crop him. The export fails if any pixel of any frame lands outside the cell. |
| Anchor | The hip is cell (76, 161), which lands on screen (236, 379). Scale 0.62 is baked in. **Dex is never scaled**, and the player never moves the anchor. |
| Compression | One LZ4 block per frame (lz4 HC 12). `budget` measures a 16-bit RLE on the same frames: LZ4 comes out ~40% smaller (anti-aliased edges make runs short), and it decodes at memcpy speed. Identical frames are stored once. |
| Player | `ui/dex_sprite.cpp` decodes the current frame into **one** 86,016 B buffer (PSRAM on the device), shown as an unscaled `LV_IMG_CF_TRUE_COLOR` image. Each frame carries a FNV-1a hash, and `player_check/check_dex_smooth.cpp` compares it with the framebuffer. |
| Points | Each frame carries `hand` (the right hand: it cups your voice, holds the sign, lifts the bag) and `bag` (the takeout bag's body, the clip the hold fills bottom → top). Both are computed from the design geometry, and `dex_get_point_area()` returns them on screen, breathing offset included. |
| Mini | `DEX_SIZE_MINI` (main's cards; the final UI never uses it) is an unscaled 76 × 76 head crop in the corner, from `mini_origin`. It has no points. |

### Motion (`motion` in the manifest, from `docs/design/final/motion.md`)

Each animation has:
- `frames` (per-frame `ms`) with `loop_from` (a single last frame holds: the done nod plays once);
- optional per-frame `blink` variants `[half, closed]`;
- an optional `sip` clip (idle: every 20–40 s);
- an optional `exit` clip that plays when the pose changes to `exit.to` (`lift_bag` → `offer_bag`
  goes back through the in-betweens in 200 ms);
- a `breath` of `day` (4.0 s: 1600 / 200 / 200 / 1600 / 200 / 200 ms at 0 / −1 / −2 / −2 / −1 / 0 px),
  `night` (6.0 s) or `none` (the lift, which bobs instead).

Blinks come every 3–6 s, never while inhaling, and every 5th is double (150 ms gap). The player's
random numbers use a fixed seed, so the sim's shots are reproducible.

### Outfits

`reading` is drawn from `build_reading.py`:

| Pose | Reading frames | Design screen |
|---|---|---|
| `idle` | book-hug | R1 |
| `speaking` | show-page, talking | R2, voice on |
| `attention` | show-page, mouth closed | R2, quiet: a card is up and nothing is spoken |
| `paper` | read | R3 / R5 |
| `done` | tuck, note sinking in, once | R6 |

Every other pose/outfit borrows the default frames (`outfit_fallback`). R4's shh and crier are
exported for review but not compiled, because no `dex_pose_t` plays them. Night reading isn't
exported. A pose with no frames still falls back to the gray placeholder.

## Pixel-art sheets (indexed; the dummy fixture)

The indexed pipeline below still works: `fixtures/dummy/` uses it, and the player picks the mode
from the generated header. Export this layout:

```
tools/art/
  manifest.json          # copy fixtures/dummy/manifest.json and edit it
  dex-default.png        # e.g. one sheet per outfit (rows are free-form)
  dex-gameday.png
  ...
```

1. **Grid.** Every frame is one cell of a fixed size (e.g. 48×64 or 56×72 logical pixels), at
   1× (one PNG pixel = one sprite pixel). Cells tile from the top-left with no gutters. Keep one
   animation per row, frames left to right. That convention matches the manifest, but any cell
   can be listed explicitly.
2. **Pixels.** Export RGBA PNG. Every pixel is fully opaque and in the palette, or fully
   transparent (alpha 0). Anti-aliased edges and soft alpha are rejected, with the coordinates of
   the first offending pixels.
3. **Palette.** List every color in `sprites.palette`. Up to 15 colors fit 4-bit indexed frames;
   16–255 colors go to 8-bit. `check` warns when two colors become the same RGB565 value on the
   panel.
4. **Size.** `cell × scale.full` must fit the 168×224 Dex box. Dex is centered, feet on the
   bottom edge. For the mini (the 76×76 corner box while a card is open), choose `scale.mini` and
   `mini_origin`, the top-left cell pixel of the head-and-shoulders region.
   `76 / scale.mini` cell pixels show in each direction.
5. **Names.** Poses and outfits use the `dex_sprite.h` names:
   - poses: `idle listening working attention done speaking asleep offline error`
   - outfits (the protocol `mode` values): `default gameday reading food code cat`
6. **Timing.** Each frame carries its own `ms` (16–60000). An animation loops.

Then run `uv run charm-assets check art/manifest.json`, followed by `sprites art/manifest.json`
(and `fonts art/manifest.json` once the face is chosen).

Missing art is fine. With `"outfit_fallback": true`, a pose without an outfit variant borrows the
default outfit's frames. A pose with no frames at all shows the gray placeholder box. Nothing
breaks while the set is incomplete.

## Manifest format (`version: 1`)

Paths are relative to the manifest file.

```jsonc
{
  "version": 1,
  "sprites": {
    "cell": [32, 40],                  // cell width, height in sprite pixels
    "scale": {"full": 5, "mini": 4},   // integer zoom for each size
    "mini_origin": [6, 2],             // top-left of the mini's head-and-shoulders region
    "palette": ["#FF00FF", "#00C8B4"], // every opaque color in the sheets, #RRGGBB
    "outfit_fallback": true,           // missing pose/outfit -> that pose's default frames
    "sheets": {"base": "dummy-sheet.png"},
    "animations": [
      {"pose": "idle", "outfit": "default", "sheet": "base", "row": 0,
       "frames": [{"col": 0, "ms": 600}, {"col": 1, "ms": 400}]}
      // a frame may also give its own "row"
    ]
  },
  "fonts": {
    "lv_font_conv": "1.5.3",           // pinned; runs as `npx -y lv_font_conv@1.5.3`
    "bpp": 4,                          // anti-aliasing depth: 1, 2, 4 or 8
    "symbols_file": "../../fonts/lvgl-symbols.ttf",
    "faces": [
      {"name": "body",                 // -> charm_font_body_<size>
       "file": "../../fonts/AtkinsonHyperlegible-Regular.ttf",
       "sizes": [14, 18, 24, 32],      // fixed bitmap pixel sizes
       "ranges": ["0x20-0x7E", "0xA0-0xFF"],
       "symbols": ["OK", "WIFI"]}      // LV_SYMBOL_<name>s to include
    ]
  }
}
```

Either section may be left out.

## What gets generated, and why

**Sprites: indexed color, expanded at play time.** Each frame is an `lv_img_dsc_t` in
`LV_IMG_CF_INDEXED_{1,2,4,8}BIT` (a palette, then packed rows, index 0 transparent), or
`LV_IMG_CF_TRUE_COLOR_ALPHA` (RGB565 + alpha, 3 B/px), whichever is smaller. The tool picks, and
the header says which. For a 12–16 color pixel-art palette, indexed wins by 2–6×. A 48×64 frame is
1.6 KB at 4-bit against 9.2 KB true color. LVGL 8.3 zooms only images it can read whole, so
`ui/dex_sprite.cpp` expands the current frame into one static RGB565+alpha buffer
(cell w × h × 3 bytes: 3.8 KB for the dummy, ~9–12 KB for a real cell) and lets `lv_img` zoom it
with nearest-neighbor scaling. Identical frames are stored once.

The frame table is `charm_sprite_anims[pose][outfit]`, in `dex_pose_t`/`dex_outfit_t` order. Each
entry is `{frames, count}` with `{img, ms}` per frame. `dex_sprite.cpp` `static_assert`s that the
table matches the enums.

**Flash estimate.** `check` prints it. A full set is 9 poses × 6 outfits × 4 frames = 216 frames:

| Cell and palette | Full set |
|---|---|
| Dummy's 32×40 cells | ~148 KiB |
| 48×64, ≤15 colors (4-bit) | ~340 KiB |
| 48×64, 16 colors (8-bit) | ~860 KiB |

Against the 6.25 MiB app partition, any of these fits. Borrowed outfits and repeated frames cost
nothing.

**Fonts.** `lv_font_conv` (pinned in the manifest) renders each face × size with
`--no-compress` (the UI's `lv_conf.h` doesn't enable compressed fonts). The tool:

- checks that the ranges cover ASCII + Latin-1, including **ñ á é í ó ú ü ¿ ¡ ° ·**;
- adds every `LV_SYMBOL_*` the hand-written `ui/` uses (today `OK`, the ✓ on confirmed cards),
  plus the manifest's `symbols`;
- verifies each glyph really came out;
- wraps each font in its own C++ namespace, so several fonts can share one file, and defines the
  `lv_font_t` `extern "C"` to match the header.

The dummy set (body 14/18/24/32 + 16 symbols) compiles to ~93 KiB.

The fonts are **generated but not used yet.** Wiring them into the cards means editing
`ui/charm_ui.cpp`/`ui/ui_card.cpp`, outside this pipeline's files. Until then the linker drops
them from the firmware.

**Player checks.** `tests/test_player.py` builds two programs against the sim's libraries and runs
them. Both tests are skipped until `build/sim` exists.

- `player_check/check_dex_player.cpp` runs the real `ui/dex_sprite.cpp` on the dummy table, which is
  generated into a temp dir. It checks that frames change on their `ms`, loop, and scale to full and
  mini, and that a pose with no art falls back to the gray box.
- `player_check/check_dex_smooth.cpp` runs it on the committed smooth table. It checks that:
  - every sampled frame is bit-exact on the framebuffer at the anchor, unscaled;
  - frames loop from `loop_from`;
  - breathing moves the whole sprite by −1 / −2 px, and the points follow;
  - blinks come 3–6 s apart, with doubles, and the sip plays;
  - the lift and its exit clip play as specified;
  - the bag goes from chest to overhead;
  - the reading outfit shows its own frames;
  - mini works.

## Fonts and licenses

| File | What | License |
|---|---|---|
| `fonts/AtkinsonHyperlegible-Regular.ttf` | Placeholder text face (Braille Institute), from google/fonts | SIL OFL 1.1, `fonts/AtkinsonHyperlegible-OFL.txt` |
| `fonts/lvgl-symbols.ttf` | Font Awesome 5 Free cut down to LVGL 8.3's 60 `LV_SYMBOL_*` codepoints (provenance in the license file) | SIL OFL 1.1, `fonts/lvgl-symbols-OFL.txt` |

The design sprint picks the real face. Drop the file and its license into `fonts/`, then point
`faces[].file` at it.

## Dummy art

`fixtures/dummy/` is a fake test sheet, deliberately nothing like Dex: magenta dashed test-card
borders, a checker corner, and a circle, triangle and square. It has 3 poses × 2 frames (idle,
listening, working) plus a game-day variant of idle, and it exists only to prove the pipeline.
`uv run charm-assets dummy` regenerates the sheet, and a test checks that the committed PNG
matches it.
