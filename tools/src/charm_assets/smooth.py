"""The smooth Dex (`"format": "rgb565"`): opaque RGB565 frames -> LZ4 blocks in
ui/charm_assets_sprites.{h,cpp}, played by ui/dex_sprite.cpp without scaling.

Each frame is one PNG the size of the cell, fully opaque, pre-composited on #000. The generator:
  * converts it to RGB565 little-endian (LV_COLOR_DEPTH 16, no swap: ui/lv_conf.h);
  * compresses it as one LZ4 block (lz4 HC level 12; the player's decoder is ~30 lines of C);
  * stores identical frames once (pixels and overlay points both equal);
  * emits a FNV-1a hash of the decoded pixels, so the player check can prove the round trip on
    the real framebuffer;
  * emits the overlay points (hand, bag) per frame, in cell pixels;
  * emits the motion from the manifest: per-animation frames and loop point, blink variants, the
    idle sip, the exit clip (lift -> offer), and the breathing/blink/sip timing.

Why LZ4 and not RLE: `charm-assets budget` measures both on the real frames. The frames are
anti-aliased illustration, not pixel art, so runs are short at every edge; LZ4 also matches the
repeated rows and shapes. LZ4 comes out ~35-45% smaller than a 16-bit RLE, and decodes at memcpy
speed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import lz4.block
from PIL import Image, ImageDraw

from . import cgen
from .manifest import OUTFITS, POINTS, POSES, ManifestError, SmoothSpec

BREATH_IDS = {"none": 0, "day": 1, "night": 2}
NO_IMG = 0xFFFF
NO_POSE = 0xFF


def rgb565(img: Image.Image) -> bytes:
    """RGB -> RGB565 little-endian, row-major."""
    r, g, b = (c.tobytes() for c in img.split())
    out = bytearray(2 * len(r))
    for i in range(len(r)):
        v = ((r[i] >> 3) << 11) | ((g[i] >> 2) << 5) | (b[i] >> 3)
        out[2 * i] = v & 0xFF
        out[2 * i + 1] = v >> 8
    return bytes(out)


def from_rgb565(raw: bytes, w: int, h: int) -> Image.Image:
    """What the panel shows for an RGB565 frame (bit-replicated to 8 bits)."""
    px = bytearray(3 * w * h)
    for i in range(w * h):
        v = raw[2 * i] | raw[2 * i + 1] << 8
        r5, g6, b5 = v >> 11, (v >> 5) & 0x3F, v & 0x1F
        px[3 * i] = (r5 << 3) | (r5 >> 2)
        px[3 * i + 1] = (g6 << 2) | (g6 >> 4)
        px[3 * i + 2] = (b5 << 3) | (b5 >> 2)
    return Image.frombytes("RGB", (w, h), bytes(px))


def lz4_compress(raw: bytes) -> bytes:
    return bytes(lz4.block.compress(raw, mode="high_compression", compression=12, store_size=False))


def lz4_decompress(data: bytes, size: int) -> bytes:
    return bytes(lz4.block.decompress(data, uncompressed_size=size))


def rle16(raw: bytes) -> bytes:
    """A 16-bit PackBits RLE, for the budget's comparison only (the player decodes LZ4)."""
    px = [raw[i] | raw[i + 1] << 8 for i in range(0, len(raw), 2)]
    out = bytearray()
    i, n = 0, len(px)
    while i < n:
        j = i
        while j < n and px[j] == px[i] and j - i < 128:
            j += 1
        if j - i >= 2:
            out.append(0x80 | (j - i - 1))
            out += raw[2 * i : 2 * i + 2]
            i = j
            continue
        k = i + 1
        while k < n and k - i < 128 and not (k + 1 < n and px[k] == px[k + 1]):
            k += 1
        out.append(k - i - 1)
        out += raw[2 * i : 2 * k]
        i = k
    return bytes(out)


def fnv1a16(raw: bytes) -> int:
    """FNV-1a over the RGB565 values (as ui/dex_sprite.cpp's check hashes lv_color_t.full)."""
    h = 2166136261
    for i in range(0, len(raw), 2):
        h = ((h ^ (raw[i] | raw[i + 1] << 8)) * 16777619) & 0xFFFFFFFF
    return h


@dataclass
class SmoothImage:
    names: list[str]  # frame names that share these pixels + points
    raw: bytes
    lz4: bytes
    fnv: int
    points: dict[str, tuple[int, int, int, int]]


@dataclass
class SmoothAnim:
    frames: list[tuple[int, int]]  # (image index, ms)
    loop_from: int
    blink: list[tuple[int, int]] | None
    sip: list[tuple[int, int]] | None
    exit_to: str | None
    exit: list[tuple[int, int]] | None
    breath: str

    def images(self) -> set[int]:
        out = {i for i, _ in self.frames}
        for clip in (self.sip, self.exit):
            out |= {i for i, _ in clip or []}
        for half, closed in self.blink or []:
            out |= {half, closed}
        return out


@dataclass
class SmoothBuild:
    images: list[SmoothImage] = field(default_factory=list)
    by_name: dict[str, int] = field(default_factory=dict)
    table: dict[tuple[str, str], SmoothAnim] = field(default_factory=dict)
    fallbacks: list[tuple[str, str]] = field(default_factory=list)
    unplayed: list[str] = field(default_factory=list)  # manifest frames no animation uses

    @property
    def data_bytes(self) -> int:
        return sum(len(i.lz4) for i in self.images)


def load_frame(spec: SmoothSpec, name: str) -> Image.Image:
    f = spec.frames[name]
    try:
        with Image.open(f.file) as im:
            im.load()
            src: Image.Image = im.copy()
    except OSError as e:
        raise ManifestError(f"sprites.frames.{name}: can't open {f.file}: {e}") from e
    if src.size != (spec.cell_w, spec.cell_h):
        raise ManifestError(
            f"sprites.frames.{name}: {src.size[0]}x{src.size[1]}, the cell is "
            f"{spec.cell_w}x{spec.cell_h}"
        )
    if src.mode in ("RGBA", "LA", "PA") or "transparency" in src.info:
        alpha = src.convert("RGBA").getchannel("A")
        if alpha.getextrema() != (255, 255):
            raise ManifestError(
                f"sprites.frames.{name}: has transparent pixels; rgb565 frames are opaque, "
                "pre-composited on #000"
            )
    rgb: Image.Image = src.convert("RGB")
    return rgb


def build(spec: SmoothSpec) -> SmoothBuild:
    result = SmoothBuild()
    used: set[str] = set()
    for a in spec.animations:
        used |= {n for n, _ in a.frames}
        used |= {n for pair in a.blink or () for n in pair}
        used |= {n for n, _ in (a.sip.frames if a.sip else ())}
        used |= {n for n, _ in (a.exit.frames if a.exit else ())}
    seen: dict[tuple[bytes, tuple[tuple[str, tuple[int, ...]], ...]], int] = {}
    for name in sorted(used):
        raw = rgb565(load_frame(spec, name))
        pts = spec.frames[name].points
        key = (raw, tuple(sorted(pts.items())))
        if key in seen:
            result.images[seen[key]].names.append(name)
        else:
            seen[key] = len(result.images)
            z = lz4_compress(raw)
            if lz4_decompress(z, len(raw)) != raw:
                raise ManifestError(f"lz4 round trip failed for {name}")
            result.images.append(SmoothImage([name], raw, z, fnv1a16(raw), dict(pts)))
        result.by_name[name] = seen[key]
    if len(result.images) >= NO_IMG:
        raise ManifestError(f"too many unique frames ({len(result.images)})")
    result.unplayed = sorted(set(spec.frames) - used)

    def seq(xs: tuple[tuple[str, int], ...]) -> list[tuple[int, int]]:
        return [(result.by_name[n], ms) for n, ms in xs]

    for a in spec.animations:
        result.table[(a.pose, a.outfit)] = SmoothAnim(
            frames=seq(a.frames),
            loop_from=a.loop_from,
            blink=[(result.by_name[h], result.by_name[c]) for h, c in a.blink] if a.blink else None,
            sip=seq(a.sip.frames) if a.sip else None,
            exit_to=a.exit_to,
            exit=seq(a.exit.frames) if a.exit else None,
            breath=a.breath,
        )
    if spec.outfit_fallback:
        for pose in POSES:
            base = result.table.get((pose, "default"))
            if base is None:
                continue
            for outfit in OUTFITS[1:]:
                if (pose, outfit) not in result.table:
                    result.table[(pose, outfit)] = base
                    result.fallbacks.append((pose, outfit))
    return result


def render(
    spec: SmoothSpec, result: SmoothBuild, command: str, sources: list[str]
) -> tuple[str, str]:
    head = cgen.banner("Dex sprite frames for ui/dex_sprite.cpp.", command, sources)
    raw_frame = spec.cell_w * spec.cell_h * 2
    drawn = sorted(k for k in result.table if k not in result.fallbacks)
    mo = spec.motion
    n_refs = sum(len(result.table[k].images()) for k in drawn)
    h = [
        head,
        "#pragma once",
        "#include <stdint.h>",
        "#include <lvgl.h>",
        "",
        f"// Smooth Dex: {len(drawn)} pose/outfit animations drawn, {len(result.fallbacks)} "
        f"borrowed from the default outfit; {len(result.images)} unique frames ({n_refs} uses).",
        f"// Opaque RGB565 (little-endian) on #000, one LZ4 block each: {raw_frame:,} bytes a "
        f"frame decoded, {result.data_bytes:,} bytes compressed in all.",
        "#define CHARM_SPRITE_SMOOTH 1",
        "#define CHARM_SPRITE_INDEXED_BPP 0",
        f"#define CHARM_SPRITE_CELL_W {spec.cell_w}",
        f"#define CHARM_SPRITE_CELL_H {spec.cell_h}",
        "// The cell pixel on Dex's hip, and where the hip lands on screen. Dex is never scaled.",
        f"#define CHARM_SPRITE_ANCHOR_X {spec.anchor[0]}",
        f"#define CHARM_SPRITE_ANCHOR_Y {spec.anchor[1]}",
        f"#define CHARM_SPRITE_SCREEN_ANCHOR_X {spec.screen_anchor[0]}",
        f"#define CHARM_SPRITE_SCREEN_ANCHOR_Y {spec.screen_anchor[1]}",
        "// Top-left of the unscaled 76x76 head-and-shoulders crop DEX_SIZE_MINI shows, cell px.",
        f"#define CHARM_SPRITE_MINI_X {spec.mini_x}",
        f"#define CHARM_SPRITE_MINI_Y {spec.mini_y}",
        f"#define CHARM_SPRITE_POSES {len(POSES)}",
        f"#define CHARM_SPRITE_OUTFITS {len(OUTFITS)}",
        f"#define CHARM_SPRITE_POINTS {len(POINTS)}  // " + ", ".join(POINTS),
        f"#define CHARM_SPRITE_IMAGES {len(result.images)}",
        f"#define CHARM_SPRITE_NO_IMG 0x{NO_IMG:04X}",
        f"#define CHARM_SPRITE_NO_POSE 0x{NO_POSE:02X}",
        "",
        "// Motion (docs/design/final/motion.md, via the manifest).",
        f"#define CHARM_SPRITE_TICK_MS {mo.tick_ms}",
        f"#define CHARM_SPRITE_BLINK_HALF_MS {mo.blink_half_ms}",
        f"#define CHARM_SPRITE_BLINK_CLOSED_MS {mo.blink_closed_ms}",
        f"#define CHARM_SPRITE_BLINK_EVERY_MIN_MS {mo.blink_every_ms[0]}",
        f"#define CHARM_SPRITE_BLINK_EVERY_MAX_MS {mo.blink_every_ms[1]}",
        f"#define CHARM_SPRITE_BLINK_DOUBLE_EVERY {mo.blink_double_every}",
        f"#define CHARM_SPRITE_BLINK_DOUBLE_GAP_MS {mo.blink_double_gap_ms}",
        f"#define CHARM_SPRITE_SIP_EVERY_MIN_MS {mo.sip_every_ms[0]}",
        f"#define CHARM_SPRITE_SIP_EVERY_MAX_MS {mo.sip_every_ms[1]}",
        "enum { CHARM_BREATH_NONE, CHARM_BREATH_DAY, CHARM_BREATH_NIGHT };",
        "",
        "struct charm_sprite_img_t {",
        "    const uint8_t *lz4;  // one LZ4 block: CELL_W x CELL_H RGB565 pixels",
        "    uint32_t size;",
        "    uint32_t fnv;        // FNV-1a over the decoded 16-bit pixels",
        "    int16_t points[CHARM_SPRITE_POINTS][4];  // x, y, w, h in cell px; w == 0: none",
        "};",
        "",
        "struct charm_sprite_frame_t {",
        "    uint16_t img;  // index into charm_sprite_imgs",
        "    uint16_t ms;",
        "};",
        "",
        "struct charm_sprite_clip_t {",
        "    const charm_sprite_frame_t *frames;  // nullptr: none",
        "    uint8_t count;",
        "};",
        "",
        "struct charm_sprite_anim_t {",
        "    const charm_sprite_frame_t *frames;  // nullptr when this pose/outfit has no art",
        "    uint8_t count;",
        "    uint8_t loop_from;       // frames[loop_from..count) loop; a single last frame holds",
        "    const uint16_t (*blink)[2];  // per frame: half, closed; nullptr: no blinks",
        "    charm_sprite_clip_t sip;     // one-shot every SIP_EVERY ms (idle only)",
        "    charm_sprite_clip_t exit;    // plays first when the pose changes to exit_to",
        "    uint8_t exit_to;             // dex_pose_t, or CHARM_SPRITE_NO_POSE",
        "    uint8_t breath;              // CHARM_BREATH_*",
        "};",
        "",
        "// Breathing: whole-sprite y offset steps (0, -1, -2, -2, -1, 0 px) and their ms.",
        "extern const uint16_t charm_sprite_breath[3][6];",
        "extern const charm_sprite_img_t charm_sprite_imgs[CHARM_SPRITE_IMAGES];",
        "// [pose][outfit] in dex_pose_t / dex_outfit_t order:",
        "//   poses:   " + ", ".join(POSES),
        "//   outfits: " + ", ".join(OUTFITS),
        "extern const charm_sprite_anim_t charm_sprite_anims[CHARM_SPRITE_POSES]"
        "[CHARM_SPRITE_OUTFITS];",
        "",
    ]

    c = [
        head,
        '#include "charm_assets_sprites.h"',
        "",
        "#if LV_COLOR_DEPTH != 16 || LV_COLOR_16_SWAP != 0",
        "#error charm_assets_sprites: frames are RGB565 little-endian; match ui/lv_conf.h",
        "#endif",
        "",
        "namespace {",
        "",
    ]
    for i, im in enumerate(result.images):
        c += [
            f"// image {i}: {', '.join(im.names)}",
            f"LV_ATTRIBUTE_LARGE_CONST const uint8_t img{i}[] = {{",
            cgen.byte_array(im.lz4),
            "};",
            "",
        ]
    names: dict[int, str] = {}

    def arr(name: str, frames: list[tuple[int, int]]) -> str:
        body = ", ".join(f"{{{i}, {ms}}}" for i, ms in frames)
        c.append(f"const charm_sprite_frame_t {name}[] = {{{body}}};")
        return name

    for pose, outfit in drawn:
        a = result.table[(pose, outfit)]
        base = f"{pose}_{outfit}"
        names[id(a)] = base
        arr(base, a.frames)
        if a.blink:
            body = ", ".join(f"{{{h_}, {c_}}}" for h_, c_ in a.blink)
            c.append(f"const uint16_t {base}_blink[][2] = {{{body}}};")
        if a.sip:
            arr(f"{base}_sip", a.sip)
        if a.exit:
            arr(f"{base}_exit", a.exit)
    c += ["", "}  // namespace", ""]

    c.append("const uint16_t charm_sprite_breath[3][6] = {")
    c.append("    {0, 0, 0, 0, 0, 0},")
    for k in ("day", "night"):
        c.append("    {" + ", ".join(map(str, mo.breath[k])) + "},")
    c += ["};", ""]

    c.append("const charm_sprite_img_t charm_sprite_imgs[CHARM_SPRITE_IMAGES] = {")
    for i, im in enumerate(result.images):
        pts = []
        for p in POINTS:
            box = im.points.get(p, (0, 0, 0, 0))
            pts.append("{" + ", ".join(map(str, box)) + "}")
        c.append(f"    {{img{i}, sizeof img{i}, 0x{im.fnv:08X}u, {{{', '.join(pts)}}}}},")
    c += ["};", ""]

    c.append(
        "const charm_sprite_anim_t charm_sprite_anims[CHARM_SPRITE_POSES][CHARM_SPRITE_OUTFITS] = {"
    )
    for pose in POSES:
        c.append(f"    /* {pose} */ {{")
        for outfit in OUTFITS:
            a_ = result.table.get((pose, outfit))
            if a_ is None:
                c.append(
                    "        {nullptr, 0, 0, nullptr, {nullptr, 0}, {nullptr, 0}, "
                    "CHARM_SPRITE_NO_POSE, CHARM_BREATH_NONE},"
                )
                continue
            n = names[id(a_)]
            blink = f"{n}_blink" if a_.blink else "nullptr"
            sip = f"{{{n}_sip, {len(a_.sip)}}}" if a_.sip else "{nullptr, 0}"
            ex = f"{{{n}_exit, {len(a_.exit)}}}" if a_.exit else "{nullptr, 0}"
            to = str(POSES.index(a_.exit_to)) if a_.exit_to else "CHARM_SPRITE_NO_POSE"
            br = f"CHARM_BREATH_{a_.breath.upper()}"
            c.append(
                f"        {{{n}, {len(a_.frames)}, {a_.loop_from}, {blink}, {sip}, {ex}, {to}, "
                f"{br}}},  // {outfit}"
            )
        c.append("    },")
    c += ["};", ""]
    return "\n".join(h), "\n".join(c)


# ---------------------------------------------------------------- budget and strips

APP_PARTITION = 0x640000  # app0 in PlatformIO's default_16MB.csv: 6.25 MiB


@dataclass
class PoseCost:
    key: str
    frames: int
    raw: int
    rle: int
    lz4: int


def budget(spec: SmoothSpec, result: SmoothBuild, firmware_bin: Path | None) -> list[str]:
    raw_frame = spec.cell_w * spec.cell_h * 2
    rle_cache: dict[int, int] = {}

    def rle_len(i: int) -> int:
        if i not in rle_cache:
            rle_cache[i] = len(rle16(result.images[i].raw))
        return rle_cache[i]

    rows: list[PoseCost] = []
    counted: set[int] = set()
    for pose in POSES:
        for outfit in OUTFITS:
            a = result.table.get((pose, outfit))
            if a is None or (pose, outfit) in result.fallbacks:
                continue
            new = sorted(a.images() - counted)  # frames an earlier pose already paid for are free
            counted |= set(new)
            rows.append(
                PoseCost(
                    f"{pose}/{outfit}",
                    len(new),
                    len(new) * raw_frame,
                    sum(rle_len(i) for i in new),
                    sum(len(result.images[i].lz4) for i in new),
                )
            )
    out = [
        f"smooth Dex: cell {spec.cell_w}x{spec.cell_h} RGB565, {raw_frame:,} B a frame decoded",
        "",
        f"{'pose/outfit':<22}{'frames':>7}{'raw B':>12}{'RLE16 B':>11}{'LZ4-HC B':>11}"
        f"{'LZ4/raw':>9}",
    ]
    tot = PoseCost("total", 0, 0, 0, 0)
    for r in rows:
        out.append(
            f"{r.key:<22}{r.frames:>7}{r.raw:>12,}{r.rle:>11,}{r.lz4:>11,}"
            + (f"{r.lz4 / r.raw:>8.1%}" if r.raw else "  shared")
        )
        tot = PoseCost(
            "total", tot.frames + r.frames, tot.raw + r.raw, tot.rle + r.rle, tot.lz4 + r.lz4
        )
    out.append(
        f"{'total':<22}{tot.frames:>7}{tot.raw:>12,}{tot.rle:>11,}{tot.lz4:>11,}"
        f"{tot.lz4 / tot.raw:>8.1%}"
    )
    borrowed = ", ".join(f"{p}/{o}" for p, o in result.fallbacks if o == "reading")
    out += [
        f"  (+{len(result.fallbacks)} pose/outfits borrow the default frames at no cost"
        + (f"; reading borrows: {borrowed})" if borrowed else ")"),
        f"  LZ4 vs RLE16: LZ4 is {1 - tot.lz4 / tot.rle:.0%} smaller; the player decodes LZ4.",
    ]
    if result.unplayed:
        up = 0
        for n in result.unplayed:
            up += len(lz4_compress(rgb565(load_frame(spec, n))))
        out.append(
            f"  exported but not compiled (no pose plays them): {', '.join(result.unplayed)} "
            f"= {len(result.unplayed) * raw_frame:,} B raw, {up:,} B LZ4"
        )
    table = 16 * len(result.images) + 16 * len(POSES) * len(OUTFITS)
    flash = tot.lz4 + table
    out += [
        "",
        f"flash: ~{flash:,} B ({flash / 1024:,.0f} KiB) of sprite data + tables = "
        f"{flash / APP_PARTITION:.1%} of the {APP_PARTITION:,} B (6.25 MiB) app partition",
        f"RAM: one decode buffer, {raw_frame:,} B, in PSRAM on the device "
        "(heap_caps_malloc MALLOC_CAP_SPIRAM; internal heap only as a fallback)",
    ]
    if firmware_bin is not None and firmware_bin.exists():
        size = firmware_bin.stat().st_size
        out.append(
            f"firmware: {firmware_bin} is {size:,} B = {size / APP_PARTITION:.1%} of the app "
            f"partition, {APP_PARTITION - size:,} B free"
        )
    else:
        out.append("firmware: not built (cd firmware && pio run -e charm), no usage to report")
    return out


def strips(spec: SmoothSpec, result: SmoothBuild, out_dir: Path) -> list[Path]:
    """One PNG per drawn pose/outfit: its frames side by side, decoded from the generated LZ4
    data (what the device shows), with the overlay points outlined underneath."""
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h, gap = spec.cell_w, spec.cell_h, 6
    raw_frame = w * h * 2
    written = []
    for pose, outfit in sorted(k for k in result.table if k not in result.fallbacks):
        a = result.table[(pose, outfit)]
        seq = [(i, f"{ms}") for i, ms in a.frames]
        seq += [(i, f"sip {ms}") for i, ms in a.sip or []]
        seq += [(i, f"exit {ms}") for i, ms in a.exit or []]
        for k, (half, closed) in enumerate(a.blink or []):
            seq += [(half, f"f{k} half"), (closed, f"f{k} closed")]
        sheet = Image.new("RGB", (len(seq) * (w + gap) + gap, 2 * h + 3 * gap + 14), (40, 40, 44))
        draw = ImageDraw.Draw(sheet)
        for col, (i, label) in enumerate(seq):
            im = result.images[i]
            frame = from_rgb565(lz4_decompress(im.lz4, raw_frame), w, h)
            x = gap + col * (w + gap)
            sheet.paste(frame, (x, gap))
            boxed = frame.copy()
            bd = ImageDraw.Draw(boxed)
            for p, color in (("hand", (0, 230, 230)), ("bag", (240, 0, 240))):
                if p in im.points:
                    bx, by, bw, bh = im.points[p]
                    bd.rectangle((bx, by, bx + bw - 1, by + bh - 1), outline=color)
            sheet.paste(boxed, (x, 2 * gap + h))
            draw.text((x, 2 * h + 2 * gap + 1), f"{i}: {label}", fill=(200, 200, 200))
        path = out_dir / f"{pose}-{outfit}.png"
        sheet.save(path)
        written.append(path)
    return written


def sources_digest(spec: SmoothSpec, result: SmoothBuild) -> str:
    """One sha256 over every compiled frame PNG, for the generated banner."""
    h = hashlib.sha256()
    for name in sorted(result.by_name):
        h.update(name.encode())
        h.update(spec.frames[name].file.read_bytes())
    return h.hexdigest()[:16]
