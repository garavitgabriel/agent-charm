"""Coach's frames: design renders -> ui/assets-src/coach/ (frames + a character manifest).

`charm-assets export-coach SRC` takes a folder of PNG renders, one per frame, named

    <pose>-<n>.png             the default outfit, frame n (0, 1, 2 ...)
    <pose>-<outfit>-<n>.png    another outfit

with the dex_sprite.h pose and outfit names (e.g. `idle-0.png`, `speaking-1.png`,
`paper-reading-0.png`). Each render is either the 192x224 cell or the full 368x448 screen (the
cell is cropped at (160, 218), and a pixel outside it fails the export, as for Dex). Transparent
renders are composited on #000. Coach stands on Dex's anchor and moves with Dex's motion: each pose
takes Dex's frame timing, loop point and breathing for that pose, from Dex's manifest next door.

`charm-assets dummy-coach` renders the clearly fake orange/navy test card through the same path.
It is not Coach: it only proves the character switch end to end until the design's Coach lands.
"""

from __future__ import annotations

import io
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import dex_export
from .manifest import OUTFITS, POSES, ManifestError, character_manifest

CELL = dex_export.CELL
NAME = re.compile(r"^(?P<pose>[a-z_]+)(?:-(?P<outfit>[a-z]+))?-(?P<n>\d+)$")


def _cell_image(path: Path) -> Image.Image:
    try:
        with Image.open(path) as im:
            im.load()
            src = im.convert("RGBA")
    except OSError as e:
        raise ManifestError(f"export-coach: can't open {path}: {e}") from e
    flat = Image.new("RGB", src.size, (0, 0, 0))
    flat.paste(src, mask=src.getchannel("A"))
    if flat.size == dex_export.SCREEN:
        return dex_export.cell_of(flat, path.name)
    if flat.size != CELL:
        raise ManifestError(
            f"export-coach: {path.name} is {flat.size[0]}x{flat.size[1]}; renders are the "
            f"{CELL[0]}x{CELL[1]} cell or the {dex_export.SCREEN[0]}x{dex_export.SCREEN[1]} screen"
        )
    return flat


def _dex_motion(out: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Dex's animations by (pose, outfit), for Coach's timing."""
    path = character_manifest(out / "manifest.json", "dex")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ManifestError(f"export-coach: Coach takes Dex's timing from {path}: {e}") from e
    return {(a["pose"], a.get("outfit", "default")): a for a in raw["sprites"]["animations"]}


def export(src: Path, out: Path, generated: str) -> dict[str, Any]:
    """Write out/frames/*.png and out/manifest.json from the renders in `src`."""
    groups: dict[tuple[str, str], dict[int, Path]] = {}
    for p in sorted(src.glob("*.png")):
        m = NAME.match(p.stem)
        if not m or m["pose"] not in POSES or (m["outfit"] or "default") not in OUTFITS:
            raise ManifestError(
                f"export-coach: {p.name}: name renders <pose>-<n>.png or <pose>-<outfit>-<n>.png "
                "with the dex_sprite.h names"
            )
        frames = groups.setdefault((m["pose"], m["outfit"] or "default"), {})
        frames[int(m["n"])] = p
    if not groups:
        raise ManifestError(f"export-coach: no <pose>-<n>.png renders in {src}")
    dex = _dex_motion(out)

    (out / "frames").mkdir(parents=True, exist_ok=True)
    frames_out: dict[str, Any] = {}
    anims = []
    for (pose, outfit), by_n in sorted(
        groups.items(), key=lambda kv: (POSES.index(kv[0][0]), kv[0][1])
    ):
        if sorted(by_n) != list(range(len(by_n))):
            raise ManifestError(f"export-coach: {pose}/{outfit} frames must be numbered 0..n-1")
        like = dex.get((pose, outfit)) or dex.get((pose, "default")) or {}
        dex_ms = [f["ms"] for f in like.get("frames", [])] or [250]
        seq = []
        for n in range(len(by_n)):
            name = f"{pose}-{n}" if outfit == "default" else f"{pose}-{outfit}-{n}"
            buf = io.BytesIO()
            _cell_image(by_n[n]).save(buf, format="PNG")
            path = out / "frames" / f"{name}.png"
            if not path.exists() or path.read_bytes() != buf.getvalue():
                path.write_bytes(buf.getvalue())
            frames_out[name] = {"file": f"frames/{name}.png", "points": {}}
            seq.append({"frame": name, "ms": dex_ms[min(n, len(dex_ms) - 1)]})
        e: dict[str, Any] = {"pose": pose, "outfit": outfit, "frames": seq}
        loop_from = like.get("loop_from", 0)
        if 0 < loop_from < len(seq):
            e["loop_from"] = loop_from
        elif loop_from and len(seq) > 1:
            e["loop_from"] = (
                len(seq) - 1
            )  # Dex holds his last frame here (the done nod): so does Coach
        e["breath"] = like.get("breath", "day")
        anims.append(e)
    stale = {p.name for p in (out / "frames").glob("*.png")} - {f"{n}.png" for n in frames_out}
    for name in sorted(stale):
        (out / "frames" / name).unlink()

    manifest = {
        "version": 1,
        "_generated": f"{generated}  (do not edit by hand)",
        "_notes": [
            "Coach's character manifest: Dex's cell and anchor, Dex's motion timing per pose.",
            "Compiled with Dex's: cd tools && uv run charm-assets sprites "
            "../ui/assets-src/dex/manifest.json",
            "A pose not listed here shows the gray placeholder while Coach is on the body.",
        ],
        "sprites": {
            "format": "rgb565",
            "character": "coach",
            "cell": list(CELL),
            "anchor": list(dex_export.CELL_ANCHOR),
            "outfit_fallback": True,
            "frames": frames_out,
            "animations": anims,
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


# ---------------------------------------------------------------- the dummy test card

ORANGE = (255, 122, 26)
NAVY = (27, 42, 82)
WHITE = (240, 240, 240)
SHADOW = (26, 26, 30)
# Frames per pose: enough to see each one animate. Poses not here stay on the gray placeholder.
DUMMY_POSES = {"idle": 2, "listening": 2, "working": 3, "speaking": 2}


def _text(
    draw_on: Image.Image, xy: tuple[int, int], text: str, color: tuple[int, int, int]
) -> None:
    """The bitmap default font at 2x, nearest neighbor: the same pixels on every machine."""
    font = ImageFont.load_default_imagefont()
    left, top, right, bottom = font.getbbox(text)
    small = Image.new("L", (right - left + 1, bottom - top + 1), 0)
    ImageDraw.Draw(small).text((-left, -top), text, fill=255, font=font)
    big = small.resize((small.width * 2, small.height * 2), Image.Resampling.NEAREST)
    draw_on.paste(Image.new("RGB", big.size, color), (xy[0] - big.width // 2, xy[1]), big)


def dummy_frame(pose: str, n: int) -> Image.Image:
    """One cell: a navy test card with an orange dashed border and hazard stripes, standing on
    Dex's anchor, with a per-pose shape that changes each frame. Nothing like Coach."""
    im = Image.new("RGB", CELL, (0, 0, 0))
    d = ImageDraw.Draw(im)
    ax, ay = dex_export.CELL_ANCHOR  # the hip: (76, 161)
    d.ellipse((ax - 60, ay + 46, ax + 60, ay + 60), fill=SHADOW)  # ground shadow
    x0, y0, x1, y1 = ax - 62, ay - 136, ax + 62, ay + 50
    d.rectangle((x0, y0, x1, y1), fill=NAVY)
    for x in range(x0, x1, 12):  # dashed test-card border
        d.line((x, y0, min(x + 6, x1), y0), fill=ORANGE, width=3)
        d.line((x, y1, min(x + 6, x1), y1), fill=ORANGE, width=3)
    for y in range(y0, y1, 12):
        d.line((x0, y, x0, min(y + 6, y1)), fill=ORANGE, width=3)
        d.line((x1, y, x1, min(y + 6, y1)), fill=ORANGE, width=3)
    for k in range(0, 36, 9):  # hazard stripes in the bottom corners
        for sx, edge in ((1, x0 + 3), (-1, x1 - 3)):
            d.polygon(
                [
                    (edge + sx * k, y1 - 3),
                    (edge + sx * (k + 4), y1 - 3),
                    (edge, y1 - 3 - (k + 4)),
                    (edge, y1 - 3 - k),
                ],
                fill=ORANGE,
            )
    _text(im, (ax, y0 + 10), "TEST", WHITE)
    _text(im, (ax, y0 + 32), "NOT COACH", ORANGE)
    _text(im, (ax, y1 - 58), pose.upper(), WHITE)
    cx, cy = ax, ay - 50  # the pose shape's center
    if pose == "idle":  # a square that steps side to side
        dx = -14 if n == 0 else 14
        d.rectangle((cx + dx - 10, cy - 10, cx + dx + 10, cy + 10), fill=ORANGE)
    elif pose == "listening":  # rings that grow
        for r in range(8, 20 + 12 * n, 8):
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ORANGE, width=3)
    elif pose == "working":  # a bar that turns 0 / 60 / 120 degrees
        a = math.radians(60 * n)
        dx, dy = round(22 * math.cos(a)), round(22 * math.sin(a))
        d.line((cx - dx, cy - dy, cx + dx, cy + dy), fill=ORANGE, width=7)
        d.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=WHITE)
    elif pose == "speaking":  # a mouth, open then shut
        h = 16 if n == 0 else 3
        d.rectangle((cx - 18, cy - h, cx + 18, cy + h), fill=ORANGE)
    return im


def export_dummy(out: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)
        for pose, count in DUMMY_POSES.items():
            for n in range(count):
                dummy_frame(pose, n).save(src / f"{pose}-{n}.png")
        return export(src, out, "cd tools && uv run charm-assets dummy-coach")
