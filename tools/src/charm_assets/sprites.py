"""Sprite sheets -> ui/charm_assets_sprites.{h,cpp}: LVGL 8.3 lv_img_dsc_t frames + a
character x pose x outfit table that ui/dex_sprite.cpp plays.

Pixel format. Every frame uses the same format, whichever of these is smaller:
  * LV_IMG_CF_INDEXED_{1,2,4,8}BIT: a (2**bpp)-entry lv_color32_t palette, then rows of indices
    packed MSB-first, each row byte-aligned. Index 0 is transparent; palette color i is index i+1.
  * LV_IMG_CF_TRUE_COLOR_ALPHA: RGB565 little-endian + one alpha byte per pixel.
A 12-16 color pixel-art palette makes indexed 3-6x smaller, so it wins for any real sheet.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from PIL import Image

from . import cgen, palette
from .manifest import CHARACTERS, OUTFITS, POSES, ManifestError, SpriteSpec

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Encoding:
    cf: str  # the LVGL color-format enum name
    bpp: int  # 0 = true color + alpha

    @property
    def indexed(self) -> bool:
        return self.bpp > 0


def indexed_bpp(n_colors: int) -> int | None:
    """Smallest LVGL index width for the palette plus the transparent index."""
    for bpp in (1, 2, 4, 8):
        if n_colors + 1 <= 1 << bpp:
            return bpp
    return None


def frame_bytes(w: int, h: int, enc: Encoding) -> int:
    if not enc.indexed:
        return 3 * w * h
    return 4 * (1 << enc.bpp) + (w * enc.bpp + 7) // 8 * h


def choose_encoding(w: int, h: int, n_colors: int) -> Encoding:
    tca = Encoding("LV_IMG_CF_TRUE_COLOR_ALPHA", 0)
    bpp = indexed_bpp(n_colors)
    if bpp is None:
        return tca
    idx = Encoding(f"LV_IMG_CF_INDEXED_{bpp}BIT", bpp)
    return idx if frame_bytes(w, h, idx) < frame_bytes(w, h, tca) else tca


def encode(indices: bytes, w: int, h: int, pal: tuple[RGB, ...], enc: Encoding) -> bytes:
    out = bytearray()
    if enc.indexed:
        entries = [(0, 0, 0, 0)] + [(b, g, r, 0xFF) for r, g, b in pal]
        entries += [(0, 0, 0, 0)] * ((1 << enc.bpp) - len(entries))
        for e in entries:  # lv_color32_t is {blue, green, red, alpha} in memory
            out += bytes(e)
        per_byte = 8 // enc.bpp
        for y in range(h):
            row = indices[y * w : (y + 1) * w]
            for x0 in range(0, w, per_byte):
                byte = 0
                for k in range(per_byte):
                    v = row[x0 + k] if x0 + k < w else 0
                    byte |= v << (8 - enc.bpp * (k + 1))
                out.append(byte)
    else:
        for i in indices:
            if i == 0:
                out += b"\x00\x00\x00"
            else:
                v = palette.to_rgb565(pal[i - 1])
                out += bytes((v & 0xFF, v >> 8, 0xFF))
    return bytes(out)


def cell_indices(img: Image.Image, col: int, row: int, spec: SpriteSpec, where: str) -> bytes:
    cw, ch = spec.cell_w, spec.cell_h
    x0, y0 = col * cw, row * ch
    if x0 + cw > img.width or y0 + ch > img.height:
        raise ManifestError(
            f"{where}: cell col {col}, row {row} ({x0},{y0} +{cw}x{ch}) is outside the "
            f"{img.width}x{img.height} sheet"
        )
    lookup = {c: i + 1 for i, c in enumerate(spec.palette)}
    out = bytearray()
    bad: list[str] = []
    px = img.load()
    assert px is not None
    for y in range(y0, y0 + ch):
        for x in range(x0, x0 + cw):
            p = px[x, y]
            assert isinstance(p, tuple)
            r, g, b, a = p[0], p[1], p[2], p[3]
            if a == 0:
                out.append(0)
            elif a != 255:
                bad.append(f"({x},{y}) alpha {a}: pixel art is fully opaque or fully clear")
                out.append(0)
            elif (r, g, b) in lookup:
                out.append(lookup[(r, g, b)])
            else:
                bad.append(f"({x},{y}) {palette.hexs((r, g, b))} is not in the palette")
                out.append(0)
    if bad:
        more = f" (+{len(bad) - 5} more)" if len(bad) > 5 else ""
        raise ManifestError(f"{where}: " + "; ".join(bad[:5]) + more)
    return bytes(out)


Table = dict[tuple[str, str], list[tuple[int, int]]]  # (pose, outfit) -> [(image index, ms)]


@dataclass
class SpriteBuild:
    encoding: Encoding
    images: list[bytes] = field(default_factory=list)  # unique encoded frames
    # character -> its table, after outfit fallback (within the character only)
    tables: dict[str, Table] = field(default_factory=lambda: {c: {} for c in CHARACTERS})
    # character -> the pose/outfits filled from its own default outfit
    borrowed: dict[str, list[tuple[str, str]]] = field(
        default_factory=lambda: {c: [] for c in CHARACTERS}
    )
    warnings: list[str] = field(default_factory=list)
    frame_refs: int = 0

    # Dex's table (the primary character), as before the character dimension.
    @property
    def table(self) -> Table:
        return self.tables["dex"]

    @property
    def fallbacks(self) -> list[tuple[str, str]]:
        return self.borrowed["dex"]

    @property
    def data_bytes(self) -> int:
        return sum(len(i) for i in self.images)


def build(spec: SpriteSpec) -> SpriteBuild:
    enc = choose_encoding(spec.cell_w, spec.cell_h, len(spec.palette))
    result = SpriteBuild(encoding=enc, warnings=palette.check(spec.palette).warnings())
    sheets: dict[str, Image.Image] = {}
    for name, path in spec.sheets.items():
        try:
            with Image.open(path) as im:
                sheets[name] = im.convert("RGBA")
        except OSError as e:
            raise ManifestError(f"sprites.sheets.{name}: can't open {path}: {e}") from e

    seen: dict[bytes, int] = {}
    for a in spec.animations:
        frames = []
        for j, f in enumerate(a.frames):
            where = f"{a.pose}/{a.outfit} frame {j} (sheet {a.sheet})"
            idx = cell_indices(sheets[a.sheet], f.col, f.row, spec, where)
            if idx not in seen:
                seen[idx] = len(result.images)
                result.images.append(encode(idx, spec.cell_w, spec.cell_h, spec.palette, enc))
            frames.append((seen[idx], f.ms))
            result.frame_refs += 1
        result.tables[a.character][(a.pose, a.outfit)] = frames

    if spec.outfit_fallback:  # never across characters: Coach doesn't borrow Dex's frames
        for character, table in result.tables.items():
            for pose in POSES:
                base = table.get((pose, "default"))
                if not base:
                    continue
                for outfit in OUTFITS[1:]:
                    if (pose, outfit) not in table:
                        table[(pose, outfit)] = base
                        result.borrowed[character].append((pose, outfit))
    return result


def estimate_full_set(spec: SpriteSpec, frames_per_anim: int = 4) -> int:
    """Flash for a complete set: every pose x outfit drawn, `frames_per_anim` frames each."""
    enc = choose_encoding(spec.cell_w, spec.cell_h, len(spec.palette))
    return len(POSES) * len(OUTFITS) * frames_per_anim * frame_bytes(spec.cell_w, spec.cell_h, enc)


def render(
    spec: SpriteSpec, result: SpriteBuild, command: str, sources: list[str]
) -> tuple[str, str]:
    enc = result.encoding
    head = cgen.banner("Dex sprite frames for ui/dex_sprite.cpp.", command, sources)
    fb = frame_bytes(spec.cell_w, spec.cell_h, enc)
    drawn = [
        (character, pose, outfit)
        for character, table in result.tables.items()
        for pose, outfit in sorted(k for k in table if k not in result.borrowed[character])
    ]
    h = [
        head,
        "#pragma once",
        "#include <stdint.h>",
        "#include <lvgl.h>",
        "",
        f"// {len(drawn)} character/pose/outfit animations drawn, "
        f"{sum(len(b) for b in result.borrowed.values())} borrowed from the character's default "
        f"outfit; {result.frame_refs} frames, {len(result.images)} unique images.",
        f"// Format {enc.cf}: {fb} bytes a frame, {result.data_bytes} bytes of pixel data in all.",
        f"// A full set (9 poses x 6 outfits x 4 frames) at this cell and palette: "
        f"~{estimate_full_set(spec) // 1024} KiB.",
        f"#define CHARM_SPRITE_CELL_W {spec.cell_w}",
        f"#define CHARM_SPRITE_CELL_H {spec.cell_h}",
        f"#define CHARM_SPRITE_SCALE_FULL {spec.scale_full}",
        f"#define CHARM_SPRITE_SCALE_MINI {spec.scale_mini}",
        "// Top-left of the head-and-shoulders region the mini size shows, in cell pixels.",
        f"#define CHARM_SPRITE_MINI_X {spec.mini_x}",
        f"#define CHARM_SPRITE_MINI_Y {spec.mini_y}",
        f"#define CHARM_SPRITE_CF {enc.cf}",
        f"#define CHARM_SPRITE_INDEXED_BPP {enc.bpp}  // 0 = true color + alpha",
        f"#define CHARM_SPRITE_CHARACTERS {len(CHARACTERS)}  // " + ", ".join(CHARACTERS),
        f"#define CHARM_SPRITE_POSES {len(POSES)}",
        f"#define CHARM_SPRITE_OUTFITS {len(OUTFITS)}",
        "",
        "struct charm_sprite_frame_t {",
        "    const lv_img_dsc_t *img;",
        "    uint16_t ms;",
        "};",
        "",
        "struct charm_sprite_anim_t {",
        "    const charm_sprite_frame_t *frames;  // nullptr when this pose/outfit has no art",
        "    uint8_t count;",
        "};",
        "",
        "// [character][pose][outfit] in dex_character_t / dex_pose_t / dex_outfit_t order:",
        "//   characters: " + ", ".join(CHARACTERS),
        "//   poses:      " + ", ".join(POSES),
        "//   outfits:    " + ", ".join(OUTFITS),
        "// A character never borrows another's frames: no art is {nullptr, 0}.",
        "extern const charm_sprite_anim_t charm_sprite_anims[CHARM_SPRITE_CHARACTERS]"
        "[CHARM_SPRITE_POSES][CHARM_SPRITE_OUTFITS];",
        "",
    ]

    c = [
        head,
        '#include "charm_assets_sprites.h"',
        "",
        "#if LV_BIG_ENDIAN_SYSTEM",
        "#error charm_assets_sprites: lv_img_header_t is initialized for little-endian targets",
        "#endif",
    ]
    if not enc.indexed:
        c += [
            "#if LV_COLOR_DEPTH != 16 || LV_COLOR_16_SWAP != 0",
            "#error charm_assets_sprites: frames are RGB565 little-endian; match ui/lv_conf.h",
            "#endif",
        ]
    c += ["", "namespace {", ""]
    for i, data in enumerate(result.images):
        digest = hashlib.sha256(data).hexdigest()[:12]
        c += [
            f"// image {i} (sha256 {digest})",
            f"LV_ATTRIBUTE_LARGE_CONST const uint8_t img{i}_px[] = {{",
            cgen.byte_array(data),
            "};",
            f"const lv_img_dsc_t img{i} = {{",
            f"    {{{enc.cf}, 0, 0, {spec.cell_w}, {spec.cell_h}}},",
            f"    sizeof img{i}_px,",
            f"    img{i}_px,",
            "};",
            "",
        ]
    names: dict[int, str] = {}  # id(frame list) -> array name, so fallbacks share one array
    for character, pose, outfit in drawn:
        frames = result.tables[character][(pose, outfit)]
        name = f"{pose}_{outfit}" if character == "dex" else f"{character}_{pose}_{outfit}"
        names[id(frames)] = name
        body = ", ".join(f"{{&img{i}, {ms}}}" for i, ms in frames)
        c.append(f"const charm_sprite_frame_t {name}[] = {{{body}}};")
    c += ["", "}  // namespace", ""]
    c.append(
        "const charm_sprite_anim_t charm_sprite_anims[CHARM_SPRITE_CHARACTERS][CHARM_SPRITE_POSES]"
        "[CHARM_SPRITE_OUTFITS] = {"
    )
    for character, table in result.tables.items():
        c.append(f"  /* {character} */ {{")
        for pose in POSES:
            cells = []
            for outfit in OUTFITS:
                got = table.get((pose, outfit))
                if got:
                    cells.append(f"{{{names[id(got)]}, {len(got)}}}")
                else:
                    cells.append("{nullptr, 0}")
            c.append(f"    /* {pose:<10} */ {{" + ", ".join(cells) + "},")
        c.append("  },")
    c += ["};", ""]
    return "\n".join(h), "\n".join(c)
