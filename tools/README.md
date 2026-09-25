# charm-assets — sprites and fonts → device-ready code

`charm-assets` turns the design sprint's sprite sheets and chosen fonts into C++ that both the
firmware and the Mac simulator compile unchanged (both builds glob `ui/*.cpp`):

| Command | Writes |
|---|---|
| `uv run charm-assets sprites MANIFEST` | `ui/charm_assets_sprites.{h,cpp}`: LVGL 8.3 `lv_img_dsc_t` frames + the pose × outfit frame table |
| `uv run charm-assets fonts MANIFEST` | `ui/charm_assets_fonts.{h,cpp}`: `lv_font_t` per face × size, through `lv_font_conv` |
| `uv run charm-assets check MANIFEST` | nothing: validates, prints the RGB565 palette report, flash sizes and the poses still on the gray placeholder |
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

## Design handoff: what to export

The real art drops in with **one manifest and one command** per output. Export this layout:

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

**Player check.** `player_check/check_dex_player.cpp` links the real `ui/dex_sprite.cpp` against
the sim's built libraries. It checks that the frames change on their `ms`, loop, and scale to full
and mini, and that a pose with no art falls back to the gray box. `tests/test_player.py` builds and
runs it, and is skipped until `build/sim` exists.

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
