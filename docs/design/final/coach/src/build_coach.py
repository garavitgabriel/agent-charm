"""Coach Beard on the charm — pose sheet, surfaces C0–C3, the accent test, and the sprite frames.

Imports the final system unchanged from ../../src (build.py tokens, zones, helpers, place()) and
Coach's parts and poses from coach.py. Nothing in final/src is modified.

Run:  python3 build_coach.py      -> html/*.html, ../*.png (C0–C3, the sheet, accent-compare)
      <python with resvg-py + pillow> build_coach.py --frames
                                  -> ../frames/<pose>-<n>.png (the export-coach input) and
                                     ../frames-extra/ (blinks, glance); renders with resvg and fails
                                     if any pixel leaves the 192x224 cell (dex_export's test)
"""
import os, sys, math, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True   # no __pycache__ inside final/src
sys.path.insert(0, HERE)

import coach as C              # noqa: E402  (puts ../../src on sys.path)
import build as B              # noqa: E402  locked tokens, zones, helpers
from build import (W, H, FG, FG2, PAD, SEP_Y, RAIL_X, ACCENTS, FONT, FONT_LINK, T18, T24, T32,  # noqa: E402
                   place, floor, separator, svg, txt, act, pill, screen_div, DEX_X, DEX_Y, S)
import sheet as DS             # noqa: E402  Dex's sheet, for the side-by-side reference tile

HERE = os.path.dirname(os.path.abspath(__file__))   # re-pin after the star-ish imports
OUT = os.path.abspath(os.path.join(HERE, ".."))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ACC = ACCENTS["b"]             # the one accent, gold
CELL_ORIGIN, CELL = (160, 218), (192, 224)   # CLAUDE.md ruling; tools/charm_assets/dex_export.py


# ---- surfaces ------------------------------------------------------------------
def s_home(P, u="c0"):
    """C0 home: Coach idle, calendar tucked, the house status line. Same layout as Dex's 01-home."""
    art = floor() + separator() + place(C.pose_idle(P, u, 0))
    t = txt(PAD, SEP_Y - 20 - 28, T24, "Nothing needs you", FG2, 500)
    return art, t


def s_on_it(P, u="c1"):
    """C1 'Coach is on it': the walk-away working state (~3 min). One headline, one secondary line.
    No Cancel: it's a background job, the card carries no actions."""
    art = floor() + separator() + place(C.pose_working(P, u))
    t = txt(PAD, PAD, T32, "Coach is on it")
    t += txt(PAD, PAD + 46, T18, "You can put it down.", FG2, 400)
    return art, t


def s_call(P, u="c2", acc=ACC):
    """C2 'Coach's call': the Decision layout. Verdict 32; deadline and flip condition 18 (FG2).
    Hear it is the primary (the gold pill); Why? and Later are gold text actions."""
    art = floor() + separator() + place(C.pose_call(P, u))
    t = txt(PAD, PAD, T32, "Start Purdy")
    t += txt(PAD, PAD + 46, T18, "Sun 12:00", FG2, 400)
    t += txt(PAD, PAD + 80, T18, "Flip only if Purdy is out<br>before Sun 12:00", FG2, 400)
    t += pill(232, "Hear it", acc, w=128, padx=20)
    t += act(300, "Why?", acc, w=96) + act(362, "Later", acc, w=96)
    return art, t


def s_night(P, u="c3"):
    """C3 night: Coach asleep on the stool, beanie pulled down, PAL_NIGHT, dim tokens, no text."""
    art = floor(night=True) + separator(night=True) + place(C.pose_sleep(C.PAL_NIGHT, u))
    return art, ""


SURFACES = [("c0-home", "Home", s_home), ("c1-on-it", "Coach is on it", s_on_it),
            ("c2-call", "Coach&#8217;s call", s_call), ("c3-night", "Night", s_night)]


# ---- the pose sheet ---------------------------------------------------------------
def sheet_tiles():
    P, N = C.PAL, C.PAL_NIGHT

    def t(cap, fig, night=False):
        return (cap, floor(night=night) + separator(night=night) + place(fig), night)
    return [
        t("Dex idle (reference)", DS.pose_idle(B.P, "dx", 0)),
        t("idle", C.pose_idle(P, "i0", 0)),
        t("idle beat (glance)", C.pose_idle(P, "i3", 3)),
        t("listening", C.pose_listen(P, "l")),
        t("working (on it)", C.pose_working(P, "w")),
        t("speaking", C.pose_speak(P, "s")),
        t("attention", C.pose_attention(P, "a")),
        t("ask_yes (the call)", C.pose_call(P, "c")),
        t("done", C.pose_done(P, "d")),
        t("offline", C.pose_offline(P, "o")),
        t("error (shrug)", C.pose_error(P, "e")),
        t("asleep (night)", C.pose_sleep(N, "z"), True),
    ]


def page(title, cells, cols):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<link href="{FONT_LINK}" rel="stylesheet">
<style>
html,body{{margin:0;background:#2B2C30;font-family:{FONT}}}
.g{{display:grid;grid-template-columns:repeat({cols},{W}px);gap:28px 32px;padding:32px;width:max-content}}
.t{{width:{W}px}}
.c{{color:#C9C6C0;font-size:16px;line-height:22px;padding-top:8px;white-space:nowrap}}
button{{cursor:pointer}}
</style></head><body><div class="g">{cells}</div></body></html>"""


def cell(body, caption=""):
    return f'<div class="t">{screen_div(body)}' + (f'<div class="c">{caption}</div>' if caption else "") + "</div>"


def single(body):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Coach screen</title>
<link href="{FONT_LINK}" rel="stylesheet">
<style>html,body{{margin:0;background:#000;overflow:hidden}}button{{cursor:pointer}}</style></head>
<body>{screen_div(body)}</body></html>"""


# ---- accent test: CIEDE2000 of each jacket candidate against the gold -------------
def _lab(hexc):
    h = hexc.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
    fx, fy, fz = [t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116 for t in (x, y, z)]
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def de2000(c1, c2):
    L1, a1, b1 = _lab(c1)
    L2, a2, b2 = _lab(c2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    if C1p * C2p == 0:
        dh = 0
    elif dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hbp = h1p + h2p
    if C1p * C2p != 0:
        hbp = (h1p + h2p + 360) / 2 if abs(h1p - h2p) > 180 else (h1p + h2p) / 2
    T = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dth = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * dth)) * Rc
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


CANDIDATES = [
    ("ref", "A · reference orange #E8742C", dict(jacket="ref")),
    ("burnt", "B · burnt #C8551E (chosen)", dict(jacket="burnt")),
    ("rust", "C · rust #A84E2E", dict(jacket="rust")),
    ("navy", "D · navy jacket, burnt trim", dict(jacket="burnt", navy_led=True)),
]


def accent_rows():
    rows = []
    dex_teal = B.P["teal"][1]
    rows.append(("Dex teal (the baseline gold was picked against)", dex_teal,
                 de2000(ACC[0], dex_teal), de2000(ACC[1], dex_teal), _lab(dex_teal)[0]))
    for key, label, kw in CANDIDATES:
        P = C.make_pal(**kw)
        base = P["jacket"][1]
        # the collision that matters is the largest orange area next to the gold pill: the jacket
        # body, or for D the beanie (the biggest orange left)
        probe = P["beanie"][1] if kw.get("navy_led") else base
        rows.append((label, probe, de2000(ACC[0], probe), de2000(ACC[1], probe), _lab(probe)[0]))
    return rows


# ---- output --------------------------------------------------------------------------
def shot(html_path, png, w, h):
    """headless Chrome, per-call profile (parallel Chromes don't collide). A fresh profile can keep
    Chrome alive after the screenshot is written, so a timeout with the PNG on disk is success."""
    if os.path.exists(png):
        os.remove(png)
    with tempfile.TemporaryDirectory() as prof:
        try:
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            "--no-default-browser-check", "--allow-file-access-from-files",
                            "--virtual-time-budget=4000", f"--user-data-dir={prof}", f"--window-size={w},{h}",
                            f"--screenshot={png}", "file://" + html_path], capture_output=True, timeout=45)
        except subprocess.TimeoutExpired:
            pass
    if not os.path.exists(png):
        raise SystemExit(f"screenshot failed: {png}")


def main():
    os.makedirs(os.path.join(HERE, "html"), exist_ok=True)
    # C1, C2 at 1x
    for slug, _, fn in SURFACES:
        art, t = fn(C.PAL)
        hp = os.path.join(HERE, "html", slug + ".html")
        open(hp, "w").write(single(svg(art) + t))
        shot(hp, os.path.join(OUT, slug + ".png"), W, H)
    # pose sheet, 6 x 2
    cells = "".join(cell(svg(a), cap) for cap, a, _ in sheet_tiles())
    hp = os.path.join(HERE, "html", "coach-sheet.html")
    open(hp, "w").write(page("Coach pose sheet", cells, 6))
    shot(hp, os.path.join(OUT, "coach-sheet.png"), 6 * W + 5 * 32 + 64, 2 * (H + 30) + 28 + 64)
    # accent test on the call screen (the gold pill sits next to the orange), 4 across
    cells = ""
    for key, label, kw in CANDIDATES:
        art, t = s_call(C.make_pal(**kw), "x" + key)
        cells += cell(svg(art) + t, label)
    hp = os.path.join(HERE, "html", "accent-compare.html")
    open(hp, "w").write(page("Coach accent test", cells, 4))
    shot(hp, os.path.join(OUT, "accent-compare.png"), 4 * W + 3 * 32 + 64, H + 30 + 64)
    # night check: C1 under PAL_NIGHT is not a shipped surface; asleep is on the sheet.
    print("rendered:", ", ".join(s for s, _, _ in SURFACES), "coach-sheet, accent-compare")
    print(f"\n{'candidate':<48} {'hex':<8} {'dE00 vs gold':>12} {'vs gold side':>12} {'L*':>6}")
    for label, hx, d1, d2, L in accent_rows():
        print(f"{label:<48} {hx:<8} {d1:>12.1f} {d2:>12.1f} {L:>6.1f}")
    print(f"{'gold ' + ACC[0]:<57} {'':>12} {'':>12} {_lab(ACC[0])[0]:>6.1f}")


# ---- sprite frames (tools/README.md § Coach: <pose>-<n>.png, cell 192x224, opaque on #000) --------
# Frame counts follow Dex's manifest per pose, because export-coach gives Coach Dex's timing by
# frame index: idle 3 x 250 ms, listening 2 x 300, working 2 x 300, speaking 2 x 200, done 4 x 120
# (holds the last), asleep 3 x 400, and one 1000 ms still for attention / ask_yes / offline / error.
def frame_set():
    P, N = C.PAL, C.PAL_NIGHT
    fr = [
        # idle: the whistle swings on its cord (Dex's steam slot); breathing is the player's offset
        ("idle-0", C.pose_idle(P, "f", 0, sway=0), False),
        ("idle-1", C.pose_idle(P, "f", 0, sway=5), False),
        ("idle-2", C.pose_idle(P, "f", 0, sway=-4), False),
        ("listening-0", C.pose_listen(P, "f", bob=0), False),
        ("listening-1", C.pose_listen(P, "f", bob=3), False),
        ("working-0", C.pose_working(P, "f", 0), False),
        ("working-1", C.pose_working(P, "f", 1), False),
        ("speaking-0", C.pose_speak(P, "f", mouth="open"), False),
        ("speaking-1", C.pose_speak(P, "f", mouth="o"), False),
        ("attention-0", C.pose_attention(P, "f"), False),
        ("ask_yes-0", C.pose_call(P, "f"), False),
        # done: the nod, head +4 / +7 / +4 / 0 over the pose's resting head (Dex's done beat)
        ("done-0", C.pose_done(P, "f", head_dy=10), False),
        ("done-1", C.pose_done(P, "f", head_dy=13), False),
        ("done-2", C.pose_done(P, "f", head_dy=10), False),
        ("done-3", C.pose_done(P, "f", head_dy=6), False),
        # asleep: a slow head sway (Dex's steam slot), night palette
        ("asleep-0", C.pose_sleep(N, "f", lean=0), True),
        ("asleep-1", C.pose_sleep(N, "f", lean=2), True),
        ("asleep-2", C.pose_sleep(N, "f", lean=4), True),
        ("offline-0", C.pose_offline(P, "f"), False),
        ("error-0", C.pose_error(P, "f"), False),
    ]
    # Not consumable by export-coach yet (it takes <pose>-<n> sequences only; see coach.md § Open):
    # blink half/closed for every open-eyed frame, and the idle glance beat (Dex's sip slot).
    extra = [("idle-glance", C.pose_idle(P, "f", 3), False)]
    blinkable = {
        "idle-0": lambda e: C.pose_idle(P, "f", 0, eyes=e),
        "listening-0": lambda e: C.pose_listen(P, "f", bob=0, eyes=e),
        "listening-1": lambda e: C.pose_listen(P, "f", bob=3, eyes=e),
        "speaking-0": lambda e: C.pose_speak(P, "f", mouth="open", eyes=e),
        "speaking-1": lambda e: C.pose_speak(P, "f", mouth="o", eyes=e),
        "attention-0": lambda e: C.pose_attention(P, "f", eyes=e),
        "ask_yes-0": lambda e: C.pose_call(P, "f", eyes=e),
        "offline-0": lambda e: C.pose_offline(P, "f", eyes=e),
        "error-0": lambda e: C.pose_error(P, "f", eyes=e),
    }
    for name, fn in blinkable.items():
        extra.append((name + "-half", fn("down"), False))
        extra.append((name + "-closed", fn("blink"), False))
    return fr, extra


def render_cell(fig, night, name):
    """resvg (the exporter's renderer) -> full screen -> the 192x224 cell; fail if anything leaves it."""
    import io
    import resvg_py
    from PIL import Image
    png = resvg_py.svg_to_bytes(svg_string=svg(floor(night=night) + place(fig)))
    im = Image.open(io.BytesIO(bytes(png))).convert("RGB")
    assert im.size == (W, H), (name, im.size)
    box = (CELL_ORIGIN[0], CELL_ORIGIN[1], CELL_ORIGIN[0] + CELL[0], CELL_ORIGIN[1] + CELL[1])
    outside = im.copy()
    outside.paste((0, 0, 0), box)
    if outside.getbbox():
        raise SystemExit(f"{name}: pixels outside the cell at {outside.getbbox()}")
    return im.crop(box), im.getbbox()


def export_frames():
    fr, extra = frame_set()
    for folder, items in (("frames", fr), ("frames-extra", extra)):
        d = os.path.join(OUT, folder)
        os.makedirs(d, exist_ok=True)
        for old in os.listdir(d):
            if old.endswith(".png"):
                os.remove(os.path.join(d, old))
        for name, fig, night in items:
            im, bb = render_cell(fig, night, name)
            im.save(os.path.join(d, name + ".png"))
            if folder == "frames":
                print(f"OK {name:<14} screen extent {bb}")
    print(f"\n{len(fr)} frames -> frames/, {len(extra)} extras -> frames-extra/ (all inside the cell)")


if __name__ == "__main__":
    if "--frames" in sys.argv:
        export_frames()
    else:
        main()
