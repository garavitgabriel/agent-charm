"""Export the smooth Dex from the design source (docs/design/final/src/{dex,sheet,build}.py).

The poses are code, so this module never draws Dex. It imports the locked design modules read-only
(no bytecode is written next to them), calls their pose functions, and renders the SVG they return
with resvg. Motion frames the design describes but doesn't draw as separate poses (blinks, steam,
head bob, lift in-betweens, the done nod, the toe-tap) are the same `figure()` call with one design
parameter changed (`eyes`, the mug's `lean`, `head_dy`, ...), or two poses' parameters
interpolated (the lift in-betweens). The export records every such change in `EXPORT_NOTES`.

Output (`charm-assets export-dex`): one opaque PNG per frame plus `manifest.json` in
ui/assets-src/dex/. `charm-assets sprites ui/assets-src/dex/manifest.json` compiles them.

Geometry. Screen 368x448, Dex's hip at SCREEN_ANCHOR (236, 379), scale 0.62, identical on every
screen (design § 11.2). The cell is the smallest rectangle that holds every exported frame and the
ground shadow uncropped: 192 px wide and 224 px tall (see CELL). Each frame is Dex plus his ground
shadow, pre-composited on #000.
"""

from __future__ import annotations

import importlib
import inspect
import io
import json
import math
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .manifest import ManifestError

SCREEN = (368, 448)
SCREEN_ANCHOR = (236, 379)  # Dex's hip on screen, design § 11.2
# Cell origin on screen and size. Measured over every exported frame (`export` fails if any pixel
# lands outside): x 161..351 (offline's phone to the lifted bag), y 218..441 (the lifted bag's
# handles to the ground shadow). 192 wide as designed; 224 tall, because Dex is ~211 px tall
# plus the shadow and the lift, which a 192 px cell would crop.
CELL_ORIGIN = (160, 218)
CELL = (192, 224)
CELL_ANCHOR = (SCREEN_ANCHOR[0] - CELL_ORIGIN[0], SCREEN_ANCHOR[1] - CELL_ORIGIN[1])
# The unscaled head-and-shoulders crop DEX_SIZE_MINI shows (76x76, cell px). Kept for main's card
# layout; the final UI never uses mini (design § 11.6).
MINI_ORIGIN = (38, 20)

EXPORT_NOTES = [
    "blink: half = the design's eyes='down' (heavy upper lid), closed = eyes='blink'",
    "steam: the design's single steam shape swayed with mug(lean=...) for the 3-frame loop",
    "idle sip: raise/lower is the hero and sip poses interpolated at 1/2",
    "listening head bob: head_dy +4 on the second frame",
    "working thumb-tap: right hand 3 units toward the phone on the second frame",
    "speaking mouth: the design's mouth='open' alternating with mouth='o'",
    "lift: 2 in-betweens interpolate offer_bag -> lift_bag at 1/3 and 2/3; bob = bag and hand "
    "1 screen px down (up pokes the handles out of the cell)",
    "done nod: head_dy 4, 7, 4, 0 (the reference frame is head_dy 7)",
    "lookout toe-tap: right shoe rot -24 -> -10 with the ankle 3 units down",
    "attention: no design pose of its own; it is the sheet's 'something for you', which the "
    "final design ships as job done (show_phone), so it plays show_phone's frames",
    "reading outfit: the design source has none yet, so reading borrows the default frames",
]


# ---------------------------------------------------------------- loading the design source


@dataclass
class Design:
    dex: Any
    sheet: Any
    build: Any
    src: Path


def load_design(src: Path) -> Design:
    """Import dex.py, sheet.py and build.py from `src` without writing anything next to them."""
    for name in ("dex.py", "sheet.py", "build.py"):
        if not (src / name).is_file():
            raise ManifestError(f"design source {src} has no {name}")
    saved_path, saved_flag = list(sys.path), sys.dont_write_bytecode
    saved_mods = {k: sys.modules.pop(k) for k in ("dex", "sheet", "build") if k in sys.modules}
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(src))
    try:
        mods = [importlib.import_module(m) for m in ("dex", "sheet", "build")]
    finally:
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_flag
        for k in ("dex", "sheet", "build"):
            sys.modules.pop(k, None)
        sys.modules.update(saved_mods)
    return Design(dex=mods[0], sheet=mods[1], build=mods[2], src=src)


# ---------------------------------------------------------------- capturing pose parameters


class Call(str):
    """A prop's SVG text plus the call that made it, so a variant can change one argument."""

    fn: Callable[..., str]
    bound: dict[str, Any]

    @staticmethod
    def make(fn: Callable[..., str], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Call:
        c = Call(fn(*args, **kwargs))
        c.fn = fn
        ba = inspect.signature(fn).bind(*args, **kwargs)
        ba.apply_defaults()
        c.bound = dict(ba.arguments)
        return c

    def with_(self, **over: Any) -> Call:
        return Call.make(self.fn, (), {**self.bound, **over})


@dataclass
class Pose:
    """One `figure(P, uid, **kw)` call from the design, captured."""

    pal: dict[str, Any]
    kw: dict[str, Any]

    def with_(self, **over: Any) -> Pose:
        return Pose(self.pal, {**self.kw, **over})


@contextmanager
def _capturing(d: Design) -> Iterator[None]:
    """Make the design's figure() return its parameters, and its props remember their args."""
    patches: list[tuple[Any, str, Any]] = []

    def patch(mod: Any, name: str, new: Any) -> None:
        patches.append((mod, name, getattr(mod, name)))
        setattr(mod, name, new)

    def record(real: Callable[..., str]) -> Callable[..., str]:
        return lambda *a, **k: Call.make(real, a, k)

    def fig(pal: dict[str, Any], uid: str, **kw: Any) -> Pose:
        return Pose(pal, {**d.dex.DEFAULT, **kw})

    for mod in (d.build, d.sheet):
        patch(mod, "figure", fig)
    patch(d.build, "takeout_fill", record(d.build.takeout_fill))
    patch(d.sheet, "mug", record(d.sheet.mug))
    try:
        yield
    finally:
        for mod, name, old in reversed(patches):
            setattr(mod, name, old)


def capture(d: Design, fn: Callable[..., Any], *args: Any) -> Pose:
    with _capturing(d):
        pose = fn(*args)
    if not isinstance(pose, Pose):
        raise ManifestError(f"design pose {fn.__name__} didn't come from figure()")
    return pose


def _lerp(a: Any, b: Any, t: float) -> Any:
    if isinstance(a, Call) and isinstance(b, Call) and a.fn is b.fn:
        return a.with_(**{k: _lerp(a.bound[k], b.bound[k], t) for k in a.bound})
    if isinstance(a, bool) or isinstance(b, bool):
        return a if t < 0.5 else b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a + (b - a) * t
    if isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b):
        return tuple(_lerp(x, y, t) for x, y in zip(a, b, strict=True))
    return a if t < 0.5 else b


def between(a: Pose, b: Pose, t: float) -> Pose:
    """The in-between of two captured poses: every numeric design parameter interpolated."""
    keys = a.kw.keys() | b.kw.keys()
    return Pose(a.pal, {k: _lerp(a.kw.get(k), b.kw.get(k), t) for k in keys})


# ---------------------------------------------------------------- geometry (the overlay points)


def _rot(x: float, y: float, deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    return x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r)


def _to_cell(pose: Pose, x: float, y: float, scale: float) -> tuple[float, float]:
    """A point in figure() body coordinates -> cell pixels."""
    kw = pose.kw
    rx, ry = _rot(x, y, kw["body_rot"])
    bx, by = rx + kw["body_dx"], ry + kw["body_dy"]
    return (
        SCREEN_ANCHOR[0] + bx * scale - CELL_ORIGIN[0],
        SCREEN_ANCHOR[1] + by * scale - CELL_ORIGIN[1],
    )


def _box(pts: list[tuple[float, float]]) -> list[int]:
    x0 = math.floor(min(p[0] for p in pts))
    y0 = math.floor(min(p[1] for p in pts))
    x1 = math.ceil(max(p[0] for p in pts))
    y1 = math.ceil(max(p[1] for p in pts))
    return [x0, y0, x1 - x0, y1 - y0]


def hand_box(pose: Pose, scale: float) -> list[int] | None:
    """The right hand (the one that cups your voice, holds the sign, lifts the bag): the palm
    ellipse from dex.hand(), centre W(0, 6.5) (W(0, 7) cupped), 13 units of radius with outline."""
    h = pose.kw.get("handR")
    if not h:
        return None
    x, y, ang = h[0], h[1], h[2]
    kind = h[3] if len(h) > 3 else "mitt"
    s = h[5] if len(h) > 5 else 1.0
    cx, cy = _rot(0, (7 if kind == "cup" else 6.5) * s, -(90 - ang))
    r = 13 * s
    corners = [(x + cx + dx * r, y + cy + dy * r) for dx in (-1, 1) for dy in (-1, 1)]
    return _box([_to_cell(pose, px, py, scale) for px, py in corners])


def bag_box(pose: Pose, scale: float) -> list[int] | None:
    """The takeout bag's body (build.BAG_BODY, -29..29 x -30..36): the clip the hold fills
    bottom -> top. Axis-aligned around the bag's rotation."""
    for prop in (*pose.kw["props_top"], *pose.kw["props_front"], *pose.kw["props_mid"]):
        if isinstance(prop, Call) and prop.fn.__name__ == "takeout_fill":
            a = prop.bound
            pts = []
            for bx, by in ((-29, -30), (29, -30), (29, 36), (-29, 36)):
                rx, ry = _rot(bx * a["s"], by * a["s"], a["rot"])
                pts.append(_to_cell(pose, a["x"] + rx, a["y"] + ry, scale))
            return _box(pts)
    return None


# ---------------------------------------------------------------- the frame set


@dataclass
class Frame:
    name: str
    pose: Pose
    night: bool = False


@dataclass
class Anim:
    pose: str
    frames: list[tuple[str, int]]  # (frame name, ms)
    loop_from: int = 0
    blink: list[tuple[str, str]] | None = None  # per frame: (half, closed)
    sip: list[tuple[str, int]] | None = None
    exit_to: str | None = None
    exit: list[tuple[str, int]] | None = None
    breath: str = "day"


@dataclass
class FrameSet:
    frames: dict[str, Frame] = field(default_factory=dict)
    anims: list[Anim] = field(default_factory=list)

    def add(self, name: str, pose: Pose, night: bool = False) -> str:
        if name in self.frames:
            raise ManifestError(f"export: frame {name} defined twice")
        self.frames[name] = Frame(name, pose, night)
        return name

    def blinking(self, name: str, pose: Pose) -> tuple[str, tuple[str, str]]:
        """A frame plus its half- and closed-eye variants."""
        base = self.add(name, pose)
        half = self.add(f"{name}-half", pose.with_(eyes="down"))
        closed = self.add(f"{name}-closed", pose.with_(eyes="blink"))
        return base, (half, closed)


def frame_set(d: Design) -> FrameSet:
    """Every frame motion.md needs for the 15 dex_sprite.h poses, from the design's pose code."""
    b, sh = d.build, d.sheet
    pal, night = b.P, b.N
    acc = b.ACCENTS["b"]  # gold, chosen 2026-09-27; only the placard is accent-owned
    fs = FrameSet()

    def still(pose: str, p: Pose) -> Anim:
        f, bl = fs.blinking(pose, p)
        fs.anims.append(Anim(pose, [(f, 1000)], blink=[bl]))
        return fs.anims[-1]

    # idle: the Home hero (mug at the chin) with a 3-frame steam loop, blinks and a sip.
    hero = capture(d, sh.pose_idle, pal, "i", 0)
    mug = hero.kw["props_top"][0]
    steam, blinks = [], []
    for i, lean in enumerate((22, 16, 28)):
        f, bl = fs.blinking(f"idle-s{i}", hero.with_(props_top=(mug.with_(lean=lean),)))
        steam.append((f, 250))
        blinks.append(bl)
    sip_pose = capture(d, sh.pose_idle, pal, "i", 3)
    mid = fs.add("idle-sip-mid", between(hero, sip_pose, 0.5))
    sip = fs.add("idle-sip", sip_pose)
    fs.anims.append(Anim("idle", steam, blink=blinks, sip=[(mid, 400), (sip, 1200), (mid, 400)]))

    # listening: lean in, cupped hand; 2-frame head bob at 300 ms.
    lis = capture(d, b.pose_listen_in, pal, "l")
    fa, ba = fs.blinking("listening-0", lis)
    fb, bb = fs.blinking("listening-1", lis.with_(head_dy=lis.kw["head_dy"] + 4))
    fs.anims.append(Anim("listening", [(fa, 300), (fb, 300)], blink=[ba, bb]))

    # working: head down over the phone (eyes down: no blinks); thumb-tap 2 frames at 300 ms.
    wk = capture(d, b.pose_working, pal, "w")
    x, y, *rest = wk.kw["handR"]
    wa = fs.add("working-0", wk)
    wb = fs.add("working-1", wk.with_(handR=(x - 1, y - 3, *rest)))
    fs.anims.append(Anim("working", [(wa, 300), (wb, 300)]))

    # speaking: palm toward the answer; the mouth alternates.
    sp = capture(d, b.pose_present, pal, "a")
    sa, sba = fs.blinking("speaking-0", sp)
    sb, sbb = fs.blinking("speaking-1", sp.with_(mouth="o"))
    fs.anims.append(Anim("speaking", [(sa, 200), (sb, 200)], blink=[sba, sbb]))

    still("ask_yes", capture(d, b.pose_ask, pal, acc, "d"))
    offer = capture(d, b.pose_offer_bag, pal, acc, "m")
    still("offer_bag", offer)

    # lift_bag (motion.md § Money): 2 in-betweens at 100 ms, the lift at 200 ms, then held with
    # the bag bobbing 1 px every 200 ms. Releasing early returns through the in-betweens (200 ms).
    lift = capture(d, b.pose_lift, pal, acc, "k", 0.0)
    ib1 = fs.add("lift_bag-in1", between(offer, lift, 1 / 3))
    ib2 = fs.add("lift_bag-in2", between(offer, lift, 2 / 3))
    up = fs.add("lift_bag-0", lift)
    s = b.S
    bag = lift.kw["props_top"][0]
    hx, hy, *hrest = lift.kw["handR"]
    sa_, se_, sh_ = lift.kw["armR"]
    dy = 1 / s  # one screen pixel down, in body units (up would leave the cell)
    bob = fs.add(
        "lift_bag-1",
        lift.with_(
            props_top=(bag.with_(y=bag.bound["y"] + dy),),
            handR=(hx, hy + dy, *hrest),
            armR=(sa_, se_, (sh_[0], sh_[1] + dy)),
        ),
    )
    fs.anims.append(
        Anim(
            "lift_bag",
            [(ib1, 100), (ib2, 100), (up, 200), (bob, 200), (up, 200)],
            loop_from=3,
            exit_to="offer_bag",
            exit=[(ib2, 100), (ib1, 100)],
            breath="none",
        )
    )

    # done: hands the bag over, nods once (head +4, +7, +4, 0 over 480 ms), then holds.
    ho = capture(d, b.pose_handoff, pal, acc, "o")
    nod = [fs.add(f"done-{i}", ho.with_(head_dy=h)) for i, h in enumerate((4, 7, 4, 0))]
    fs.anims.append(Anim("done", [(n, 120) for n in nod], loop_from=3))

    # lookout: arms folded, eyes on the door, toe-tap.
    lk = capture(d, b.pose_lookout, pal, "t")
    (hip, knee, ankle), (shx, shy, _) = lk.kw["legR"], lk.kw["shoeR"]
    la, lba = fs.blinking("lookout-0", lk)
    lb, lbb = fs.blinking(
        "lookout-1",
        lk.with_(legR=(hip, knee, (ankle[0], ankle[1] + 3)), shoeR=(shx, shy + 3, -10)),
    )
    fs.anims.append(Anim("lookout", [(la, 300), (lb, 300)], blink=[lba, lbb]))

    still("paper", capture(d, b.pose_paper, pal, "p"))
    phone = still("show_phone", capture(d, b.pose_review, pal, "j"))
    fs.anims.append(Anim("attention", phone.frames, blink=phone.blink))

    # asleep: the night palette baked in; slow steam, no blinks, 6.0 s breathing.
    sl = capture(d, sh.pose_sleep, night, "n")
    smug = sl.kw["props_top"][0]
    zs = [
        (fs.add(f"asleep-s{i}", sl.with_(props_top=(smug.with_(lean=lean),)), night=True), 400)
        for i, lean in enumerate((0, -6, 6))
    ]
    fs.anims.append(Anim("asleep", zs, breath="night"))

    still("offline", capture(d, sh.pose_offline, pal, "f"))
    still("error", capture(d, b.pose_shrug, pal, "q"))
    return fs


# ---------------------------------------------------------------- rendering


def render_screen(d: Design, frame: Frame) -> Image.Image:
    import resvg_py  # imported here: only the export needs it

    b = d.build
    art = b.floor(night=frame.night) + b.place(d.dex.figure(frame.pose.pal, "x", **frame.pose.kw))
    png = resvg_py.svg_to_bytes(svg_string=b.svg(art))
    with Image.open(io.BytesIO(bytes(png))) as im:
        out = im.convert("RGB")
    if out.size != SCREEN:
        raise ManifestError(f"export: {frame.name} rendered at {out.size}, want {SCREEN}")
    return out


def cell_of(screen: Image.Image, name: str) -> Image.Image:
    """Crop the cell, and fail if any of Dex (anything not black) falls outside it."""
    x0, y0 = CELL_ORIGIN
    box = (x0, y0, x0 + CELL[0], y0 + CELL[1])
    outside = screen.copy()
    outside.paste((0, 0, 0), box)
    bb = outside.getbbox()
    if bb:
        raise ManifestError(f"export: {name} has pixels at {bb}, outside the cell {box}")
    return screen.crop(box)


def export(design_src: Path, out: Path) -> dict[str, Any]:
    d = load_design(design_src)
    fs = frame_set(d)
    scale = float(d.build.S)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    frames: dict[str, Any] = {}
    for f in fs.frames.values():
        cell = cell_of(render_screen(d, f), f.name)
        rel = f"frames/{f.name}.png"
        buf = io.BytesIO()
        cell.save(buf, format="PNG")
        path = out / rel
        if not path.exists() or path.read_bytes() != buf.getvalue():
            path.write_bytes(buf.getvalue())
        points = {}
        if (hb := hand_box(f.pose, scale)) is not None:
            points["hand"] = hb
        if (bb := bag_box(f.pose, scale)) is not None:
            points["bag"] = bb
        frames[f.name] = {"file": rel, "points": points}
    stale = {p.name for p in (out / "frames").glob("*.png")} - {f"{n}.png" for n in frames}
    for name in sorted(stale):
        (out / "frames" / name).unlink()

    def seq(xs: list[tuple[str, int]]) -> list[dict[str, Any]]:
        return [{"frame": n, "ms": ms} for n, ms in xs]

    anims = []
    for a in fs.anims:
        e: dict[str, Any] = {"pose": a.pose, "outfit": "default", "frames": seq(a.frames)}
        if a.loop_from:
            e["loop_from"] = a.loop_from
        if a.blink:
            e["blink"] = [list(x) for x in a.blink]
        if a.sip:
            e["sip"] = seq(a.sip)
        if a.exit:
            e["exit"] = {"to": a.exit_to, "frames": seq(a.exit)}
        e["breath"] = a.breath
        anims.append(e)
    manifest = {
        "version": 1,
        "_generated": "cd tools && uv run charm-assets export-dex  (do not edit by hand)",
        "_notes": EXPORT_NOTES,
        "sprites": {
            "format": "rgb565",
            "compression": "lz4",
            "cell": list(CELL),
            "anchor": list(CELL_ANCHOR),
            "screen_anchor": list(SCREEN_ANCHOR),
            "mini_origin": list(MINI_ORIGIN),
            "outfit_fallback": True,
            "motion": {
                "tick_ms": 40,
                "breath": {
                    "day": [1600, 200, 200, 1600, 200, 200],
                    "night": [2400, 300, 300, 2400, 300, 300],
                },
                "blink": {
                    "half_ms": 60,
                    "closed_ms": 90,
                    "every_ms": [3000, 6000],
                    "double_every": 5,
                    "double_gap_ms": 150,
                },
                "sip_every_ms": [20000, 40000],
            },
            "frames": frames,
            "animations": anims,
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest
