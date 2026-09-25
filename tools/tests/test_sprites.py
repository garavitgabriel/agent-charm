from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import DUMMY_MANIFEST, TOOLS, UI, base_sprites
from PIL import Image

from charm_assets import cli, dummy, manifest, palette, sprites
from charm_assets.manifest import ManifestError

Writer = Callable[..., Path]


def test_rgb565_round_trip_and_collisions() -> None:
    assert palette.to_rgb565((0xFF, 0xFF, 0xFF)) == 0xFFFF
    assert palette.from_rgb565(0xFFFF) == (0xFF, 0xFF, 0xFF)
    assert palette.to_rgb565((0xF8, 0x00, 0x00)) == 0xF800
    rep = palette.check([(0x10, 0x20, 0x30), (0x11, 0x21, 0x31), (0xFF, 0, 0)])
    assert len(rep.collisions) == 1
    assert "look identical" in rep.warnings()[0]
    assert palette.check([(0, 0, 0), (0xFF, 0xFF, 0xFF)]).collisions == []


def test_encoding_choice() -> None:
    assert sprites.indexed_bpp(1) == 1
    assert sprites.indexed_bpp(3) == 2
    assert sprites.indexed_bpp(15) == 4
    assert sprites.indexed_bpp(16) == 8  # 16 colors + transparent
    assert sprites.indexed_bpp(300) is None
    assert sprites.choose_encoding(48, 64, 16).cf == "LV_IMG_CF_INDEXED_8BIT"
    assert sprites.choose_encoding(48, 64, 12).cf == "LV_IMG_CF_INDEXED_4BIT"
    # A tiny image isn't worth a 1 KiB palette.
    assert sprites.choose_encoding(4, 4, 100).cf == "LV_IMG_CF_TRUE_COLOR_ALPHA"


def test_indexed_rows_are_msb_first_and_byte_aligned() -> None:
    enc = sprites.Encoding("LV_IMG_CF_INDEXED_4BIT", 4)
    pal = ((0xFF, 0, 0), (0, 0xFF, 0), (0, 0, 0xFF))
    # 3x2: row 0 = [1, 2, 3], row 1 = [0, 0, 1]
    data = sprites.encode(bytes([1, 2, 3, 0, 0, 1]), 3, 2, pal, enc)
    assert len(data) == 16 * 4 + 2 * 2
    assert data[0:4] == bytes((0, 0, 0, 0))  # index 0: transparent
    assert data[4:8] == bytes((0, 0, 0xFF, 0xFF))  # red as {b, g, r, a}
    assert data[64:] == bytes((0x12, 0x30, 0x00, 0x10))


def test_true_color_alpha_is_rgb565_le_plus_alpha() -> None:
    enc = sprites.Encoding("LV_IMG_CF_TRUE_COLOR_ALPHA", 0)
    data = sprites.encode(bytes([0, 1]), 2, 1, ((0xF8, 0, 0),), enc)
    assert data == bytes((0, 0, 0, 0x00, 0xF8, 0xFF))


def test_off_palette_and_soft_alpha_pixels_are_rejected(write_manifest: Writer) -> None:
    m = manifest.load(write_manifest(sprites=base_sprites(palette=["#FF00FF"])))
    assert m.sprites
    with pytest.raises(ManifestError, match="not in the palette"):
        sprites.build(m.sprites)

    p = write_manifest(sprites=base_sprites())
    im = Image.open(p.parent / "sheet.png").convert("RGBA")
    im.putpixel((1, 1), (0xFF, 0x00, 0xFF, 128))
    im.save(p.parent / "sheet.png")
    m = manifest.load(p)
    assert m.sprites
    with pytest.raises(ManifestError, match="alpha 128"):
        sprites.build(m.sprites)


def test_cells_outside_the_sheet_are_rejected(write_manifest: Writer) -> None:
    anims = [{"pose": "idle", "row": 9, "frames": [{"col": 0, "ms": 100}]}]
    m = manifest.load(write_manifest(sprites=base_sprites(animations=anims)))
    assert m.sprites
    with pytest.raises(ManifestError, match="outside"):
        sprites.build(m.sprites)


def test_outfit_fallback_and_dedupe(write_manifest: Writer) -> None:
    anims = [
        {"pose": "idle", "row": 0, "frames": [{"col": 0, "ms": 100}, {"col": 0, "ms": 100}]},
        {"pose": "working", "outfit": "cat", "row": 2, "frames": [{"col": 1, "ms": 100}]},
    ]
    m = manifest.load(write_manifest(sprites=base_sprites(animations=anims)))
    assert m.sprites
    r = sprites.build(m.sprites)
    assert len(r.images) == 2  # the repeated idle frame is stored once
    assert r.table[("idle", "food")] is r.table[("idle", "default")]
    assert ("working", "default") not in r.table  # no default art -> placeholder
    assert ("working", "cat") in r.table

    m = manifest.load(write_manifest(sprites=base_sprites(animations=anims, outfit_fallback=False)))
    assert m.sprites
    assert ("idle", "food") not in sprites.build(m.sprites).table


def test_render_is_deterministic_and_marked_generated() -> None:
    m = manifest.load(DUMMY_MANIFEST)
    assert m.sprites
    a = sprites.render(m.sprites, sprites.build(m.sprites), "sprites x", ["x"])
    b = sprites.render(m.sprites, sprites.build(m.sprites), "sprites x", ["x"])
    assert a == b
    assert all(text.startswith("// GENERATED — do not edit.") for text in a)
    assert "{nullptr, 0}" in a[1]  # poses without art fall back to the placeholder


def test_dummy_sheet_is_reproducible() -> None:
    committed = Image.open(TOOLS / "fixtures/dummy/dummy-sheet.png").convert("RGBA")
    assert committed.tobytes() == dummy.make_sheet().tobytes()


def test_committed_sprite_files_are_up_to_date() -> None:
    rc = cli.main(["sprites", str(DUMMY_MANIFEST), "--out-dir", str(UI), "--check"])
    assert rc == 0, "ui/charm_assets_sprites.* are stale: run `uv run charm-assets sprites ...`"


def test_cli_writes_files_and_reports_errors(tmp_path: Path, write_manifest: Writer) -> None:
    out = tmp_path / "out"
    assert cli.main(["sprites", str(DUMMY_MANIFEST), "--out-dir", str(out)]) == 0
    first = (out / "charm_assets_sprites.cpp").read_bytes()
    assert cli.main(["sprites", str(DUMMY_MANIFEST), "--out-dir", str(out)]) == 0
    assert (out / "charm_assets_sprites.cpp").read_bytes() == first
    assert cli.main(["check", str(DUMMY_MANIFEST)]) == 0

    bad = write_manifest(sprites=base_sprites(palette=["#FF00FF"]))
    assert cli.main(["sprites", str(bad), "--out-dir", str(out)]) == 2
