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
    "ask_yes",
    "offer_bag",
    "lift_bag",
    "lookout",
    "paper",
    "show_phone",
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
class SmoothFrame:
    name: str
    file: Path
    points: dict[str, tuple[int, int, int, int]]  # point name -> x, y, w, h in cell px


@dataclass(frozen=True)
class Clip:
    frames: tuple[tuple[str, int], ...]  # (frame name, ms)


@dataclass(frozen=True)
class SmoothAnimation:
    pose: str
    outfit: str
    frames: tuple[tuple[str, int], ...]
    loop_from: int
    blink: tuple[tuple[str, str], ...] | None  # (half, closed) per frame
    sip: Clip | None
    exit_to: str | None
    exit: Clip | None
    breath: str  # "none" | "day" | "night"


@dataclass(frozen=True)
class Motion:
    tick_ms: int
    breath: dict[str, tuple[int, ...]]  # 6 steps: rest, -1, -2, hold, -1, 0
    blink_half_ms: int
    blink_closed_ms: int
    blink_every_ms: tuple[int, int]
    blink_double_every: int
    blink_double_gap_ms: int
    sip_every_ms: tuple[int, int]


@dataclass(frozen=True)
class SmoothSpec:
    """`"format": "rgb565"`: opaque full-color frames, one PNG each, compressed, never scaled."""

    cell_w: int
    cell_h: int
    anchor: tuple[int, int]  # the cell pixel on Dex's hip
    screen_anchor: tuple[int, int]  # where the hip lands on screen
    mini_x: int
    mini_y: int
    compression: str
    outfit_fallback: bool
    motion: Motion
    frames: dict[str, SmoothFrame]
    animations: tuple[SmoothAnimation, ...]


POINTS = ("hand", "bag")  # dex_point_t order in ui/dex_sprite.h
BREATHS = ("none", "day", "night")
COMPRESSIONS = ("lz4",)  # RLE was measured and lost: see smooth.py


@dataclass(frozen=True)
class Manifest:
    path: Path
    sprites: SpriteSpec | SmoothSpec | None
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


def _range(obj: dict[str, Any], key: str, where: str, lo: int, hi: int) -> tuple[int, int]:
    a, b = _pair(obj, key, where, lo, hi)
    if a > b:
        raise ManifestError(f"{where}.{key} must be [min, max]")
    return a, b


def _motion(raw: Any) -> Motion:
    w = "sprites.motion"
    if not isinstance(raw, dict):
        raise ManifestError(f"{w} must be an object (tick, breath, blink and sip timing)")
    breath_raw = raw.get("breath")
    if not isinstance(breath_raw, dict) or set(breath_raw) != {"day", "night"}:
        raise ManifestError(f'{w}.breath must give "day" and "night" step lists')
    breath: dict[str, tuple[int, ...]] = {}
    for k, v in breath_raw.items():
        if (
            not isinstance(v, list)
            or len(v) != 6
            or not all(
                isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 60000 for x in v
            )
        ):
            raise ManifestError(
                f"{w}.breath.{k} must be 6 step durations in ms (rest, -1 px, "
                "-2 px, hold, -1 px, 0 px)"
            )
        breath[k] = tuple(v)
    blink = raw.get("blink")
    if not isinstance(blink, dict):
        raise ManifestError(f"{w}.blink must be an object")
    bw = f"{w}.blink"
    return Motion(
        tick_ms=_int(raw, "tick_ms", w, 1, 1000),
        breath=breath,
        blink_half_ms=_int(blink, "half_ms", bw, 1, 1000),
        blink_closed_ms=_int(blink, "closed_ms", bw, 1, 1000),
        blink_every_ms=_range(blink, "every_ms", bw, 100, 600000),
        blink_double_every=_int(blink, "double_every", bw, 0, 255),
        blink_double_gap_ms=_int(blink, "double_gap_ms", bw, 1, 5000),
        sip_every_ms=_range(raw, "sip_every_ms", w, 1000, 3600000),
    )


def _frame_refs(
    raw: Any, where: str, frames: dict[str, SmoothFrame]
) -> tuple[tuple[str, int], ...]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 255:
        raise ManifestError(f"{where} must list 1..255 frames")
    out = []
    for j, f in enumerate(raw):
        fw = f"{where}[{j}]"
        if not isinstance(f, dict) or f.get("frame") not in frames:
            raise ManifestError(
                f"{fw}.frame must name a frame in sprites.frames, got "
                f"{f.get('frame') if isinstance(f, dict) else f!r}"
            )
        out.append((str(f["frame"]), _int(f, "ms", fw, 16, 60000)))
    return tuple(out)


def _smooth(raw: dict[str, Any], base: Path) -> SmoothSpec:
    w = "sprites"
    cell_w, cell_h = _pair(raw, "cell", w, 1, 1024)
    ax, ay = _pair(raw, "anchor", w, 0, 1023)
    if ax >= cell_w or ay >= cell_h:
        raise ManifestError(f"sprites.anchor {ax},{ay} is outside the cell")
    sx, sy = _pair(raw, "screen_anchor", w, 0, 1023)
    mini_x, mini_y = _pair(raw, "mini_origin", w, 0, 1023)
    if mini_x + MINI_BOX[0] > cell_w or mini_y + MINI_BOX[1] > cell_h:
        raise ManifestError(
            f"sprites.mini_origin {mini_x},{mini_y}: the {MINI_BOX[0]}x"
            f"{MINI_BOX[1]} mini crop leaves the cell"
        )
    compression = raw.get("compression", "lz4")
    if compression not in COMPRESSIONS:
        raise ManifestError(f"sprites.compression must be one of {', '.join(COMPRESSIONS)}")
    if "scale" in raw:
        raise ManifestError('sprites.scale: "rgb565" frames are never scaled; remove it')

    frames_raw = raw.get("frames")
    if not isinstance(frames_raw, dict) or not frames_raw:
        raise ManifestError('sprites.frames must map a frame name to {"file": "x.png"}')
    frames: dict[str, SmoothFrame] = {}
    for name, f in sorted(frames_raw.items()):
        fw = f"sprites.frames.{name}"
        if not isinstance(f, dict) or not isinstance(f.get("file"), str):
            raise ManifestError(f'{fw} must be {{"file": "x.png", "points": {{...}}}}')
        pts_raw = f.get("points", {})
        if not isinstance(pts_raw, dict):
            raise ManifestError(f"{fw}.points must be an object")
        points: dict[str, tuple[int, int, int, int]] = {}
        for pname, box in pts_raw.items():
            if pname not in POINTS:
                raise ManifestError(f"{fw}.points.{pname}: not one of {', '.join(POINTS)}")
            if (
                not isinstance(box, list)
                or len(box) != 4
                or not all(isinstance(v, int) and not isinstance(v, bool) for v in box)
                or box[2] <= 0
                or box[3] <= 0
                or box[0] < 0
                or box[1] < 0
                or box[0] + box[2] > cell_w
                or box[1] + box[3] > cell_h
            ):
                raise ManifestError(
                    f"{fw}.points.{pname} must be [x, y, w, h] inside the cell, got {box!r}"
                )
            points[pname] = (box[0], box[1], box[2], box[3])
        frames[str(name)] = SmoothFrame(str(name), (base / f["file"]).resolve(), points)

    anims: list[SmoothAnimation] = []
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
        seq = _frame_refs(a.get("frames"), f"{aw}.frames", frames)
        loop_from = a.get("loop_from", 0)
        if not isinstance(loop_from, int) or not 0 <= loop_from < len(seq):
            raise ManifestError(f"{aw}.loop_from must index one of its {len(seq)} frames")
        blink = None
        if "blink" in a:
            b = a["blink"]
            if (
                not isinstance(b, list)
                or len(b) != len(seq)
                or not all(
                    isinstance(x, list) and len(x) == 2 and all(n in frames for n in x) for x in b
                )
            ):
                raise ManifestError(
                    f"{aw}.blink must give [half, closed] frame names for each "
                    f"of its {len(seq)} frames"
                )
            blink = tuple((str(x[0]), str(x[1])) for x in b)
        sip = Clip(_frame_refs(a["sip"], f"{aw}.sip", frames)) if "sip" in a else None
        exit_to, exit_clip = None, None
        if "exit" in a:
            e = a["exit"]
            if not isinstance(e, dict) or e.get("to") not in POSES or e.get("to") == pose:
                raise ManifestError(f'{aw}.exit must be {{"to": <another pose>, "frames": [...]}}')
            exit_to = str(e["to"])
            exit_clip = Clip(_frame_refs(e.get("frames"), f"{aw}.exit.frames", frames))
        breath = a.get("breath", "day")
        if breath not in BREATHS:
            raise ManifestError(f"{aw}.breath must be one of {', '.join(BREATHS)}")
        anims.append(
            SmoothAnimation(
                str(pose), str(outfit), seq, loop_from, blink, sip, exit_to, exit_clip, str(breath)
            )
        )

    return SmoothSpec(
        cell_w=cell_w,
        cell_h=cell_h,
        anchor=(ax, ay),
        screen_anchor=(sx, sy),
        mini_x=mini_x,
        mini_y=mini_y,
        compression=str(compression),
        outfit_fallback=bool(raw.get("outfit_fallback", True)),
        motion=_motion(raw.get("motion")),
        frames=frames,
        animations=tuple(anims),
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
    if sprites is not None and sprites.get("format", "indexed") not in ("indexed", "rgb565"):
        raise ManifestError('sprites.format must be "indexed" (pixel art) or "rgb565" (smooth)')
    if fonts is not None and not isinstance(fonts, dict):
        raise ManifestError("fonts must be an object")
    return Manifest(
        path=path.resolve(),
        sprites=(
            None
            if sprites is None
            else _smooth(sprites, base)
            if sprites.get("format") == "rgb565"
            else _sprites(sprites, base)
        ),
        fonts=_fonts(fonts, base) if fonts is not None else None,
    )
