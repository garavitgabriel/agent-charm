"""Character packs: pack.json + RGBA frames at 2x the charm's cell (pack format 1).

`charm-assets export-pack --character dex|coach --out <pack-dir>` renders a character from its
vector design source at 2x the charm's cell, RGBA with a transparent background (no screen
background, no ground shadow: the app draws those), into

    <pack-dir>/pack.json
    <pack-dir>/frames/<frame>.png      384x448 RGBA

with the charm manifest's animation schema. Nothing under ui/ is written and nothing is compiled.

- Dex: the same frame set as `export-dex` (dex_export.frame_set: the same poses, frames, blinks,
  sip, exits and timing), re-rendered with resvg at 2x. The review-only `unplayed` frames are left
  out (a pack has no orphans).
- Coach: his design source is vector too (docs/design/final/coach/src/coach.py, framed by
  build_coach.py's `frame_set()`), so he gets the same treatment: build_coach's frames and
  extras (blink pairs, the idle glance) rendered at 2x, with Dex's timing per pose, as
  `export-coach` gives him. A frame of a blinking pose without its own blink pair is drawn
  from the same design pose call with eyes='down' / 'blink' (build_coach's lid convention).

Geometry: the charm's screen is 368x448 with the hip at (236, 379); the 192x224 cell sits at
(160, 218). At 2x the screen renders at 736x896 and the cell is (320, 436, 384x448); any visible
pixel outside it fails the export. The anchor is the hip: CELL_ANCHOR x 2 = (152, 322).
"""

from __future__ import annotations

import importlib
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from . import coach as coach_export
from . import dex_export
from .manifest import ManifestError

SCALE = 2
SCREEN = dex_export.SCREEN
CELL = (dex_export.CELL[0] * SCALE, dex_export.CELL[1] * SCALE)
CELL_ORIGIN = (dex_export.CELL_ORIGIN[0] * SCALE, dex_export.CELL_ORIGIN[1] * SCALE)
ANCHOR = (dex_export.CELL_ANCHOR[0] * SCALE, dex_export.CELL_ANCHOR[1] * SCALE)
PRODUCER = "svg-export"
PACK_VERSION = "1.0.0"
CHARACTERS = {
    # id: (display name, Hermes agent profile)
    "dex": ("Dex", "default"),
    "coach": ("Coach Beard", "coach"),
}
COACH_SRC = Path("../coach/src")  # relative to the final design source


# ---------------------------------------------------------------- rendering


def svg_doc(inner: str) -> str:
    """The design's screen at 2x, without its background rect and without the floor."""
    w, h = SCREEN
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w * SCALE}" height="{h * SCALE}" '
        f'viewBox="0 0 {w} {h}">{inner}</svg>'
    )


# Frames whose anti-aliased edge spilled into the 1 px band around the 2x cell and was cropped
# (a half 1x pixel the 1x export rounds away). Anything further out fails the export.
FRINGE_CROPPED: set[str] = set()
FRINGE = 1  # px, at 2x


def render_cell(svg: str, name: str) -> Image.Image:
    """Render a 2x screen and crop the cell; fail if anything visible lands outside it, except an
    anti-aliased fringe in the 1 px band around the cell (recorded in FRINGE_CROPPED)."""
    import resvg_py  # imported here: only the export needs it

    png = resvg_py.svg_to_bytes(svg_string=svg)
    with Image.open(io.BytesIO(bytes(png))) as im:
        rgba: Image.Image = im.convert("RGBA")
    want = (SCREEN[0] * SCALE, SCREEN[1] * SCALE)
    if rgba.size != want:
        raise ManifestError(f"export-pack: {name} rendered at {rgba.size}, want {want}")
    x0, y0 = CELL_ORIGIN
    box = (x0, y0, x0 + CELL[0], y0 + CELL[1])
    band = (x0 - FRINGE, y0 - FRINGE, box[2] + FRINGE, box[3] + FRINGE)
    alpha = rgba.getchannel("A")
    beyond = alpha.copy()
    beyond.paste(0, band)
    if (bb := beyond.getbbox()) is not None:
        raise ManifestError(f"export-pack: {name} has pixels at {bb}, outside the 2x cell {box}")
    alpha.paste(0, box)
    if alpha.getbbox() is not None:
        FRINGE_CROPPED.add(name)
    cell = rgba.crop(box)
    if cell.getchannel("A").getbbox() is None:
        raise ManifestError(f"export-pack: {name} rendered empty")
    return cell


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- the pack


@dataclass
class PackAnim:
    pose: str
    outfit: str
    frames: list[tuple[str, int]]
    loop_from: int = 0
    blink: list[tuple[str, str]] | None = None
    sip: list[tuple[str, int]] | None = None
    exit_to: str | None = None
    exit: list[tuple[str, int]] | None = None
    breath: str = "day"


def _seq(xs: list[tuple[str, int]]) -> list[dict[str, Any]]:
    return [{"frame": n, "ms": ms} for n, ms in xs]


def write_pack(
    out: Path,
    pack_id: str,
    images: dict[str, Image.Image],
    anims: list[PackAnim],
    generated: str,
    notes: list[str],
) -> dict[str, Any]:
    """Write frames/ (only the referenced ones; stale PNGs removed) and pack.json. Keeps an
    existing pack.json's `voice_hint` (an opaque id this exporter doesn't own)."""
    name, profile = CHARACTERS[pack_id]
    used: list[str] = []
    for a in anims:
        used += [f for f, _ in a.frames]
        used += [x for pair in a.blink or [] for x in pair]
        used += [f for f, _ in a.sip or []]
        used += [f for f, _ in a.exit or []]
    missing = sorted({u for u in used if u not in images})
    if missing:
        raise ManifestError(f"export-pack: animations reference unrendered frames {missing}")
    keep = dict.fromkeys(used)  # ordered, unique

    voice_hint = None
    pj = out / "pack.json"
    if pj.is_file():
        try:
            old = json.loads(pj.read_text(encoding="utf-8"))
            if isinstance(old, dict) and isinstance(old.get("voice_hint"), str):
                voice_hint = old["voice_hint"]
        except json.JSONDecodeError:
            pass

    (out / "frames").mkdir(parents=True, exist_ok=True)
    for n in keep:
        data = _png(images[n])
        path = out / "frames" / f"{n}.png"
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    for p in sorted((out / "frames").iterdir()):
        if p.is_file() and p.stem not in keep:
            p.unlink()

    entries = []
    for a in anims:
        e: dict[str, Any] = {"pose": a.pose, "outfit": a.outfit, "frames": _seq(a.frames)}
        if a.loop_from:
            e["loop_from"] = a.loop_from
        if a.blink:
            e["blink"] = [list(x) for x in a.blink]
        if a.sip:
            e["sip"] = _seq(a.sip)
        if a.exit:
            e["exit"] = {"to": a.exit_to, "frames": _seq(a.exit)}
        e["breath"] = a.breath
        entries.append(e)
    pack = {
        "format": 1,
        "id": pack_id,
        "name": name,
        "version": PACK_VERSION,
        "cell": list(CELL),
        "anchor": list(ANCHOR),
        "agent_profile": profile,
        "voice_hint": voice_hint,
        "producer": PRODUCER,
        "_generated": f"{generated}  (do not edit by hand)",
        "_notes": notes,
        "animations": entries,
    }
    text = json.dumps(pack, indent=1) + "\n"
    if not pj.exists() or pj.read_text(encoding="utf-8") != text:
        pj.write_text(text, encoding="utf-8")
    return pack


def _fringe_note(images: dict[str, Image.Image]) -> list[str]:
    hit = sorted(FRINGE_CROPPED & images.keys())
    if not hit:
        return []
    return [
        f"cropped a 1 px anti-aliased edge just outside the 2x cell (inside the 1x cell's "
        f"rounding): {', '.join(hit)}"
    ]


# ---------------------------------------------------------------- Dex


def _dex_anims(fs: dex_export.FrameSet) -> list[PackAnim]:
    return [
        PackAnim(
            a.pose, a.outfit, a.frames, a.loop_from, a.blink, a.sip, a.exit_to, a.exit, a.breath
        )
        for a in fs.anims
    ]


def render_dex(d: dex_export.Design, frame: dex_export.Frame) -> Image.Image:
    gl = d.reading.GL if d.reading is not None else {"on": False}
    gl["on"] = frame.pose.glasses
    try:
        fig = d.dex.figure(frame.pose.pal, "x", **frame.pose.kw)
    finally:
        gl["on"] = False
    return render_cell(svg_doc(d.build.place(fig)), frame.name)


def export_dex(design_src: Path, out: Path, generated: str) -> dict[str, Any]:
    d = dex_export.load_design(design_src)
    fs = dex_export.frame_set(d)
    unplayed = set(fs.unplayed)
    images = {f.name: render_dex(d, f) for f in fs.frames.values() if f.name not in unplayed}
    notes = [
        "Dex from the SVG design source (docs/design/final/src + reading/src) via resvg at 2x, "
        "RGBA, transparent: no screen background, no ground shadow.",
        "Same frames and timing as `charm-assets export-dex` (the charm's manifest).",
        *dex_export.EXPORT_NOTES,
        f"left out (review-only, no pose plays them): {', '.join(sorted(unplayed)) or 'none'}",
        *_fringe_note(images),
    ]
    return write_pack(out, "dex", images, _dex_anims(fs), generated, notes)


# ---------------------------------------------------------------- Coach


def load_coach_build(design_src: Path) -> Any:
    """Import docs/design/final/coach/src/build_coach.py (and coach.py, dex.py, build.py,
    sheet.py) without writing bytecode next to them or leaving them in sys.modules."""
    coach_src = (design_src / COACH_SRC).resolve()
    if not (coach_src / "build_coach.py").is_file():
        raise ManifestError(f"export-pack: no Coach design source at {coach_src}")
    names = ("build_coach", "coach", "build", "sheet", "dex")
    saved_path, saved_flag = list(sys.path), sys.dont_write_bytecode
    saved_mods = {k: sys.modules.pop(k) for k in names if k in sys.modules}
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(coach_src), str(design_src.resolve())]
    try:
        return importlib.import_module("build_coach")
    finally:
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_flag
        for k in names:
            sys.modules.pop(k, None)
        sys.modules.update(saved_mods)


Fig = tuple[str, Any, bool]  # (frame name, SVG fragment, night)


def coach_frames(bc: Any) -> tuple[list[Fig], list[Fig]]:
    """build_coach.frame_set(), with every coach.pose_*() result remembering its call (a
    dex_export.Call), so a frame can be re-drawn with one argument changed."""
    mod = bc.C
    saved = {n: getattr(mod, n) for n in dir(mod) if n.startswith("pose_")}

    def record(real: Any) -> Any:
        return lambda *a, **k: dex_export.Call.make(real, a, k)

    try:
        for n, fn in saved.items():
            setattr(mod, n, record(fn))
        fr, extras = bc.frame_set()
    finally:
        for n, fn in saved.items():
            setattr(mod, n, fn)
    return list(fr), list(extras)


def coach_vector_lids(fr: list[Fig], extras: list[Fig]) -> list[Fig]:
    """Half/closed lids for frames of a pose the design blinks (some frame has a pair) that lack
    their own pair: the same pose call with eyes='down' / eyes='blink'."""
    have = set()
    for n, _, _ in extras:
        if b := coach_export.BLINK.match(n):
            have.add(b["frame"])
    poses = set()
    for n in have:
        if m := coach_export.NAME.match(n):
            poses.add((m["pose"], m["outfit"]))
    out: list[Fig] = []
    for name, fig, night in fr:
        m = coach_export.NAME.match(name)
        if not m or name in have or (m["pose"], m["outfit"]) not in poses:
            continue
        if isinstance(fig, dex_export.Call) and "eyes" in fig.bound:
            out.append((f"{name}-half", fig.with_(eyes="down"), night))
            out.append((f"{name}-closed", fig.with_(eyes="blink"), night))
    return out


def coach_anims(images: dict[str, Image.Image], dex_fs: dex_export.FrameSet) -> list[PackAnim]:
    """Group Coach's rendered frames into animations with Dex's timing (coach.export's rules),
    with blink pairs and the idle glance as the sip."""
    groups: dict[tuple[str, str], dict[int, str]] = {}
    lids: dict[str, dict[str, str]] = {}
    glances: dict[int, str] = {}
    for name in images:
        if b := coach_export.BLINK.match(name):
            lids.setdefault(b["frame"], {})[b["lid"]] = name
        elif g := coach_export.GLANCE.match(name):
            if g["pose"] != "idle":
                raise ManifestError(f"export-pack: {name}: only idle has a glance beat")
            glances[int(g["n"] or 0)] = name
        elif m := coach_export.NAME.match(name):
            groups.setdefault((m["pose"], m["outfit"] or "default"), {})[int(m["n"])] = name
        else:
            raise ManifestError(f"export-pack: Coach frame {name} has an unknown name")
    dex = {(a.pose, a.outfit): a for a in dex_fs.anims}
    order = [a.pose for a in dex_fs.anims]
    anims = []
    for (pose, outfit), by_n in sorted(
        groups.items(),
        key=lambda kv: (order.index(kv[0][0]) if kv[0][0] in order else 99, kv[0][1]),
    ):
        if sorted(by_n) != list(range(len(by_n))):
            raise ManifestError(f"export-pack: Coach {pose}/{outfit} frames aren't 0..n-1")
        like = dex.get((pose, outfit)) or dex.get((pose, "default"))
        dex_ms = [ms for _, ms in like.frames] if like else [250]
        names = [by_n[n] for n in range(len(by_n))]
        timed = [(n, dex_ms[min(i, len(dex_ms) - 1)]) for i, n in enumerate(names)]
        a = PackAnim(pose, outfit, timed)
        # Blinks: every frame needs its pair (the design's or a vector-drawn one), else the pose
        # doesn't blink (never a popping frame).
        if any(n in lids for n in names):
            ok = all(n in lids and set(lids[n]) == {"half", "closed"} for n in names)
            a.blink = [(lids[n]["half"], lids[n]["closed"]) for n in names] if ok else None
        if pose == "idle" and outfit == "default" and glances:
            sip_ms = [ms for _, ms in like.sip or []] if like else []
            sip_ms = sip_ms or [1200]
            gl = [glances[n] for n in sorted(glances)]
            a.sip = [
                (n, max(sip_ms) if len(gl) == 1 else sip_ms[min(i, len(sip_ms) - 1)])
                for i, n in enumerate(gl)
            ]
        loop_from = like.loop_from if like else 0
        if 0 < loop_from < len(names):
            a.loop_from = loop_from
        elif loop_from and len(names) > 1:
            a.loop_from = len(names) - 1
        a.breath = like.breath if like else "day"
        anims.append(a)
    return anims


def export_coach(design_src: Path, out: Path, generated: str) -> dict[str, Any]:
    bc = load_coach_build(design_src)
    fr, extras = coach_frames(bc)
    vector_lids = coach_vector_lids(fr, extras)
    images: dict[str, Image.Image] = {}
    for name, fig, _night in [*fr, *extras, *vector_lids]:
        images[name] = render_cell(svg_doc(bc.place(fig)), name)
    dex_fs = dex_export.frame_set(dex_export.load_design(design_src))
    anims = coach_anims(images, dex_fs)
    notes = [
        "Coach from his SVG design source (docs/design/final/coach/src/coach.py, frames from "
        "build_coach.py frame_set()) via resvg at 2x, RGBA, transparent: no screen background, "
        "no ground shadow.",
        "Dex's timing, loop point and breathing per pose (as export-coach). The night palette "
        "is baked into asleep.",
        "Blink pairs: build_coach's own; for a frame of a blinking pose without its own pair, "
        "the same design pose call with eyes='down' (half) / eyes='blink' (closed), as "
        f"build_coach draws the others ({', '.join(n for n, _, _ in vector_lids) or 'none'}).",
        "No money, tracker, paper, show-phone or reading poses: the app plays attention.",
        *_fringe_note(images),
    ]
    return write_pack(out, "coach", images, anims, generated, notes)


def export(character: str, design_src: Path, out: Path, generated: str) -> dict[str, Any]:
    if character == "dex":
        return export_dex(design_src, out, generated)
    if character == "coach":
        return export_coach(design_src, out, generated)
    raise ManifestError(f"export-pack: unknown character {character!r} (dex, coach)")
