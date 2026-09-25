"""The asset manifest: what the design sprint fills in. Documented in tools/README.md."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The order of dex_pose_t / dex_outfit_t in ui/dex_sprite.h. tests/test_manifest.py checks that
# these still match the header.
POSES = (
    "idle",
    "listening",
    "working",
    "attention",
    "done",
    "speaking",
    "asleep",
    "offline",
    "error",
)
OUTFITS = ("default", "gameday", "reading", "food", "code", "cat")

# The boxes ui/dex_sprite.cpp draws Dex into.
FULL_BOX = (168, 224)
MINI_BOX = (76, 76)


class ManifestError(ValueError):
    """The manifest (or an input it names) is wrong. The message says what to fix."""


@dataclass(frozen=True)
class Frame:
    col: int
    row: int
    ms: int


@dataclass(frozen=True)
class Animation:
    pose: str
    outfit: str
    sheet: str
    frames: tuple[Frame, ...]


@dataclass(frozen=True)
class SpriteSpec:
    cell_w: int
    cell_h: int
    scale_full: int
    scale_mini: int
    mini_x: int
    mini_y: int
    palette: tuple[tuple[int, int, int], ...]
    sheets: dict[str, Path]
    animations: tuple[Animation, ...]
    outfit_fallback: bool


@dataclass(frozen=True)
class FontFace:
    name: str
    file: Path
    sizes: tuple[int, ...]
    ranges: tuple[str, ...]
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class FontSpec:
    lv_font_conv: str
    bpp: int
    symbols_file: Path
    faces: tuple[FontFace, ...]


@dataclass(frozen=True)
class Manifest:
    path: Path
    sprites: SpriteSpec | None
    fonts: FontSpec | None


def parse_hex(color: str) -> tuple[int, int, int]:
    s = color.strip().lstrip("#")
    if len(s) != 6:
        raise ManifestError(f"palette color {color!r} must be #RRGGBB")
    try:
        v = int(s, 16)
    except ValueError as e:
        raise ManifestError(f"palette color {color!r} is not hex") from e
    return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF


def _int(obj: dict[str, Any], key: str, where: str, lo: int, hi: int) -> int:
    v = obj.get(key)
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise ManifestError(f"{where}.{key} must be an integer in {lo}..{hi}, got {v!r}")
    return v


def _pair(obj: dict[str, Any], key: str, where: str, lo: int, hi: int) -> tuple[int, int]:
    v = obj.get(key)
    if (
        not isinstance(v, list)
        or len(v) != 2
        or not all(isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi for x in v)
    ):
        raise ManifestError(f"{where}.{key} must be [a, b] with integers in {lo}..{hi}, got {v!r}")
    return v[0], v[1]


def _sprites(raw: dict[str, Any], base: Path) -> SpriteSpec:
    w = "sprites"
    cell_w, cell_h = _pair(raw, "cell", w, 1, 256)
    scale = raw.get("scale")
    if not isinstance(scale, dict):
        raise ManifestError('sprites.scale must be {"full": N, "mini": N}')
    scale_full = _int(scale, "full", "sprites.scale", 1, 16)
    scale_mini = _int(scale, "mini", "sprites.scale", 1, 16)
    if cell_w * scale_full > FULL_BOX[0] or cell_h * scale_full > FULL_BOX[1]:
        raise ManifestError(
            f"sprites: cell {cell_w}x{cell_h} at full scale {scale_full} is "
            f"{cell_w * scale_full}x{cell_h * scale_full}, bigger than the {FULL_BOX[0]}x"
            f"{FULL_BOX[1]} Dex box"
        )
    mini_x, mini_y = _pair(raw, "mini_origin", w, 0, 255)
    if mini_x >= cell_w or mini_y >= cell_h:
        raise ManifestError(f"sprites.mini_origin {mini_x},{mini_y} is outside the cell")

    pal_raw = raw.get("palette")
    if not isinstance(pal_raw, list) or not pal_raw:
        raise ManifestError('sprites.palette must be a non-empty list of "#RRGGBB"')
    palette = tuple(parse_hex(str(c)) for c in pal_raw)
    if len(set(palette)) != len(palette):
        raise ManifestError("sprites.palette lists the same color twice")

    sheets_raw = raw.get("sheets")
    if not isinstance(sheets_raw, dict) or not sheets_raw:
        raise ManifestError('sprites.sheets must map a sheet name to a PNG path: {"base": "x.png"}')
    sheets = {str(k): (base / str(v)).resolve() for k, v in sorted(sheets_raw.items())}

    anims: list[Animation] = []
    seen: set[tuple[str, str]] = set()
    anims_raw = raw.get("animations", [])
    if not isinstance(anims_raw, list):
        raise ManifestError("sprites.animations must be a list")
    for i, a in enumerate(anims_raw):
        aw = f"sprites.animations[{i}]"
        if not isinstance(a, dict):
            raise ManifestError(f"{aw} must be an object")
        pose, outfit = a.get("pose"), a.get("outfit", "default")
        if pose not in POSES:
            raise ManifestError(f"{aw}.pose {pose!r} is not one of {', '.join(POSES)}")
        if outfit not in OUTFITS:
            raise ManifestError(f"{aw}.outfit {outfit!r} is not one of {', '.join(OUTFITS)}")
        if (pose, outfit) in seen:
            raise ManifestError(f"{aw}: {pose}/{outfit} is listed twice")
        seen.add((pose, outfit))
        sheet = str(a.get("sheet", next(iter(sheets))))
        if sheet not in sheets:
            raise ManifestError(f"{aw}.sheet {sheet!r} is not in sprites.sheets")
        row = a.get("row", 0)
        frames_raw = a.get("frames")
        if not isinstance(frames_raw, list) or not 1 <= len(frames_raw) <= 255:
            raise ManifestError(f"{aw}.frames must list 1..255 frames")
        frames = []
        for j, f in enumerate(frames_raw):
            fw = f"{aw}.frames[{j}]"
            if not isinstance(f, dict):
                raise ManifestError(f"{fw} must be an object")
            frames.append(
                Frame(
                    col=_int(f, "col", fw, 0, 255),
                    row=_int({"row": f.get("row", row)}, "row", fw, 0, 255),
                    ms=_int(f, "ms", fw, 16, 60000),
                )
            )
        anims.append(Animation(pose, outfit, sheet, tuple(frames)))

    return SpriteSpec(
        cell_w=cell_w,
        cell_h=cell_h,
        scale_full=scale_full,
        scale_mini=scale_mini,
        mini_x=mini_x,
        mini_y=mini_y,
        palette=palette,
        sheets=sheets,
        animations=tuple(anims),
        outfit_fallback=bool(raw.get("outfit_fallback", True)),
    )


def _str_list(obj: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    v = obj.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ManifestError(f"{where}.{key} must be a list of strings")
    return tuple(v)


def _fonts(raw: dict[str, Any], base: Path) -> FontSpec:
    w = "fonts"
    version = raw.get("lv_font_conv")
    if not isinstance(version, str) or not version:
        raise ManifestError('fonts.lv_font_conv must pin a version, e.g. "1.5.3"')
    bpp = raw.get("bpp", 4)
    if bpp not in (1, 2, 4, 8):
        raise ManifestError("fonts.bpp must be 1, 2, 4 or 8")
    symbols_file = raw.get("symbols_file")
    if not isinstance(symbols_file, str):
        raise ManifestError("fonts.symbols_file must name the LVGL symbol font")
    faces = []
    faces_raw = raw.get("faces")
    if not isinstance(faces_raw, list) or not faces_raw:
        raise ManifestError("fonts.faces must be a non-empty list")
    names: set[str] = set()
    for i, f in enumerate(faces_raw):
        fw = f"{w}.faces[{i}]"
        if not isinstance(f, dict):
            raise ManifestError(f"{fw} must be an object")
        name = f.get("name")
        if not isinstance(name, str) or not name.isidentifier() or not name.islower():
            raise ManifestError(f"{fw}.name must be a lowercase C identifier, got {name!r}")
        if name in names:
            raise ManifestError(f"{fw}.name {name!r} is used twice")
        names.add(name)
        file = f.get("file")
        if not isinstance(file, str):
            raise ManifestError(f"{fw}.file must be a font path")
        sizes = f.get("sizes")
        if (
            not isinstance(sizes, list)
            or not sizes
            or not all(isinstance(s, int) and 6 <= s <= 96 for s in sizes)
        ):
            raise ManifestError(f"{fw}.sizes must list pixel sizes in 6..96")
        faces.append(
            FontFace(
                name=name,
                file=(base / file).resolve(),
                sizes=tuple(sorted(set(sizes))),
                ranges=_str_list(f, "ranges", fw) or ("0x20-0x7E", "0xA0-0xFF"),
                symbols=_str_list(f, "symbols", fw),
            )
        )
    return FontSpec(
        lv_font_conv=version,
        bpp=int(bpp),
        symbols_file=(base / symbols_file).resolve(),
        faces=tuple(faces),
    )


def load(path: Path) -> Manifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ManifestError(f"can't read manifest {path}: {e}") from e
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ManifestError('manifest must be a JSON object with "version": 1')
    base = path.resolve().parent
    sprites = raw.get("sprites")
    fonts = raw.get("fonts")
    if sprites is not None and not isinstance(sprites, dict):
        raise ManifestError("sprites must be an object")
    if fonts is not None and not isinstance(fonts, dict):
        raise ManifestError("fonts must be an object")
    return Manifest(
        path=path.resolve(),
        sprites=_sprites(sprites, base) if sprites is not None else None,
        fonts=_fonts(fonts, base) if fonts is not None else None,
    )
