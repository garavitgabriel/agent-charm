import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))
from dex import *

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 368, 448
S = 0.74          # hero scale
HIPY = 280        # hero hip line

P = PAL
N = PAL_NIGHT
FONT = "'Inter', 'SF Pro Display', -apple-system, 'Helvetica Neue', Arial, sans-serif"


def place(content, x=184, y=HIPY, s=S):
    return g(content, f"translate({f(x)} {f(y)}) scale({f(s)})")


def svg(inner):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'style="display:block">'
            f'<rect width="{W}" height="{H}" fill="#000"/>{inner}</svg>')


RELAX_L = dict(armL=((-42, -74), (-52, -38), (-50, -6)), handL=(-50, -6, 92, "mitt", 1))
RELAX_R = dict(armR=((42, -74), (52, -38), (50, -6)), handR=(50, -6, 88, "mitt", -1))


# ------------------------------------------------------------ 1 idle (+ strip frames)
def pose_idle(P, uid, frame=0):
    kw = dict(RELAX_L)
    eyes, mouth, head_dy, body_dy, feat = "open", "smile", 0, 0, (0, 0)
    if frame == 0:    # hero: mug raised to chin, about to sip
        mugp = mug(34, -100, P, rot=-10, steam=True, lean=22)
        armR = ((42, -74), (64, -62), (52, -96))
        handR = (51, -96, 240, "mitt", -1)
        feat = (-2, 0)
    elif frame == 1:  # breathe: mug low, chest up
        body_dy = -3
        mugp = mug(46, -2, P, rot=0, steam=True)
        armR = ((42, -74), (56, -40), (48, -8))
        handR = (48, -8, 110, "mitt", -1)
    elif frame == 2:  # blink
        eyes = "blink"
        mugp = mug(46, -2, P, rot=0, steam=True)
        armR = ((42, -74), (56, -40), (48, -8))
        handR = (48, -8, 110, "mitt", -1)
    else:             # sip
        eyes = "happy"
        mouth = "sleep"
        head_dy = 2
        mugp = mug(20, -114, P, rot=-28, steam=False)
        armR = ((42, -74), (60, -78), (42, -108))
        handR = (42, -106, 235, "mitt", -1)
        feat = (-2, 0)
    return figure(P, uid, eyes=eyes, mouth=mouth, head_dy=head_dy, body_dy=body_dy, feat=feat,
                  armR=armR, handR=handR, props_top=(mugp,), **kw)


# ------------------------------------------------------------ 2 listening
def crescent(cx, cy, R, a0, a1, bulge=1.7):
    p0 = (cx + R * math.cos(math.radians(a0)), cy + R * math.sin(math.radians(a0)))
    p1 = (cx + R * math.cos(math.radians(a1)), cy + R * math.sin(math.radians(a1)))
    R2 = R * bulge
    return (f"M {f(p0[0])} {f(p0[1])} A {f(R)} {f(R)} 0 0 1 {f(p1[0])} {f(p1[1])} "
            f"A {f(R2)} {f(R2)} 0 0 0 {f(p0[0])} {f(p0[1])} Z")


def sound_motif(P, ex=61, ey=-123):
    a = P["accent"]
    t1 = P["teal"][1]
    o = []
    # three uneven tapered crescents opening toward the ear, staggered like arriving speech
    o.append(path(crescent(ex, ey, 40, -70, 22, 30), fill=a))
    o.append(path(crescent(ex, ey, 60, -58, 18, 30), fill=a))
    o.append(path(crescent(ex, ey, 80, -44, 2, 30), fill=t1))
    o.append(ell(ex + 88 * math.cos(math.radians(-2)), ey + 88 * math.sin(math.radians(-2)), 4.5, 4.5, a))
    o.append(ell(ex + 70 * math.cos(math.radians(-58)), ey + 70 * math.sin(math.radians(-58)), 3, 3, t1))
    return "".join(o)


def pose_listen(P, uid):
    return figure(
        P, uid, body_rot=8, body_dx=2, head_rot=12, head_dx=4, head_dy=4,
        eyes="up", look=(1, -3), brows="raised", mouth="o", feat=(2, -2),
        legL=((-17, 4), (-22, 38), (-28, 70)), legR=((17, 4), (20, 38), (20, 70)),
        shoeL=(-30, 72, 0), shoeR=(21, 72, 0),
        armL=((-42, -74), (-68, -46), (-48, -18)), handL=(-47, -20, 40, "fist", 1),
        armR=((42, -74), (84, -94), (70, -118)), handR=(68, -122, 255, "cup", 1),
        props_top=(sound_motif(P),),
    )


# ------------------------------------------------------------ 3 thinking / working
def pose_think(P, uid):
    return figure(
        P, uid, head_dy=12, head_rot=0, body_dy=3,
        eyes="down", brows="focus", mouth="hmm", feat=(0, 9), tuft=1,
        legL=((-15, 4), (-14, 38), (-13, 70)), legR=((15, 4), (14, 38), (13, 70)),
        shoeL=(-14, 72, 0), shoeR=(14, 72, 0),
        armL=((-42, -74), (-56, -36), (-24, -22)), handL=(-22, -22, 0, "mitt", -1),
        armR=((42, -74), (56, -36), (24, -22)), handR=(22, -24, 200, "mitt", 1),
        props_front=(phone(0, -30, P, rot=0, s=1.1, checks=1),),
        badge=None,
        props_top=("",),
        extras_front=hand(9, -30, 200, P, kind="point", thumb=1, s=0.9) if False else "",
    )


# ------------------------------------------------------------ 4 something for you
def pose_offer(P, uid):
    return figure(
        P, uid, eyes="wide", brows="raised", mouth="smile", head_rot=-3,
        legL=((-17, 4), (-26, 38), (-32, 70)), legR=((17, 4), (26, 38), (32, 70)),
        shoeL=(-34, 72, 0), shoeR=(34, 72, 0),
        armL=((-42, -74), (-54, -40), (-50, -8)), handL=(-50, -8, 95, "mitt", 1),
        armR=((42, -74), (62, -66), (48, -70)),
        props_top=(phone(34, -82, P, rot=6, s=1.55, checks=2),),
        handR=(46, -44, 260, "mitt", -1),
    )


# ------------------------------------------------------------ 5 done
def pop(P, x, y, s=1.0):
    c = P["check"]
    o = []
    for ang in (-150, -110, -70, -30):
        a = math.radians(ang)
        o.append(line([(x + math.cos(a) * 14 * s, y + math.sin(a) * 14 * s),
                       (x + math.cos(a) * 22 * s, y + math.sin(a) * 22 * s)], c, 3.4))
    return "".join(o)


def pose_done(P, uid):
    return figure(
        P, uid, head_rot=8, head_dy=6, head_dx=-2,
        eyes="happy", brows="soft", mouth="grin", feat=(-1, 3),
        legL=((-17, 4), (-19, 38), (-21, 70)), legR=((17, 4), (24, 36), (26, 64)),
        shoeL=(-21, 72, 0), shoeR=(27, 66, -14),
        armL=((-42, -74), (-74, -40), (-52, -22)), handL=(-50, -24, 285, "mitt", 1),
        props_top=(phone(-48, -58, P, rot=-10, s=1.1, checks=3), pop(P, -54, -96)),
        armR=((42, -74), (44, -30), (4, -52)), handR=(2, -54, 192, "point", -1),
    )


# ------------------------------------------------------------ 6 speaking
def pose_speak(P, uid):
    return figure(
        P, uid, body_rot=-4, head_rot=-6, head_dx=-2,
        eyes="open", brows="raised", mouth="open", look=(2, 0), feat=(2, 0),
        legL=((-17, 4), (-14, 36), (-6, 68)), legR=((17, 4), (24, 38), (28, 70)),
        shoeL=(-6, 70, 0), shoeR=(29, 72, 0),
        armL=((-42, -74), (-52, -40), (-48, -8)), handL=(-48, -8, 92, "mitt", 1),
        armR=((42, -74), (72, -44), (96, -62)), handR=(98, -64, 320, "open", -1, 1.3),
        extras_front="",
    )


# ------------------------------------------------------------ 7 payment hold
def pose_pay(P, uid):
    return figure(
        P, uid, body_dy=2, head_dy=2,
        eyes="wide", brows="raised", mouth="tiny", look=(0, 1),
        legL=((-17, 4), (-22, 38), (-24, 70)), legR=((17, 4), (22, 38), (24, 70)),
        shoeL=(-25, 72, 0), shoeR=(25, 72, 0),
        armL=((-42, -74), (-66, -44), (-40, -52)),
        armR=((42, -74), (66, -44), (40, -52)),
        props_top=(takeout(0, -30, P, s=1.42),),
        handL=(-39, -54, 10, "mitt", -1), handR=(39, -54, 170, "mitt", 1),
        bag=False,
    )


# ------------------------------------------------------------ 8 asleep
def stool(P):
    c0, c1, c2 = P["stool"]
    return (path("M -64 14 L 64 14 L 62 72 L -62 72 Z", fill=c1, stroke=P["ink"], sw=3)
            + path("M 40 16 L 62 16 L 60.5 70 L 40 70 Z", fill=c2)
            + path("M -68 2 L 68 2 C 71 2 72 4 72 7 L 72 16 L -72 16 L -72 7 C -72 4 -71 2 -68 2 Z",
                   fill=c0, stroke=P["ink"], sw=3))


def knees(P):
    p0, p1, p2 = P["pants"]
    o = []
    for sx in (-1, 1):
        o.append(ell(sx * 27, 24, 17, 13, p1, stroke=P["ink"], sw=3))
        o.append(ell(sx * 27 - 3, 21, 9, 6, p0))
    return "".join(o)


def moon(P, x, y):
    c = P["shoe"][1]
    return (f'<g transform="translate({f(x)} {f(y)})">'
            + path("M 8 -14 A 16 16 0 1 0 14 10 A 12.5 12.5 0 1 1 8 -14 Z", fill=c) + "</g>")


def pose_sleep(P, uid):
    return figure(
        P, uid, head_rot=10, head_dy=10, head_dx=2, body_dy=4,
        eyes="sleep", brows="soft", mouth="sleep", blush=False, feat=(0, 6),
        extras_back=stool(P) + moon(P, 120, -230), extras_front=knees(P),
        legL=((-17, 8), (-28, 26), (-28, 58)), legR=((17, 8), (28, 26), (28, 58)),
        shoeL=(-29, 64, 0), shoeR=(29, 64, 0),
        armL=((-42, -74), (-50, -34), (6, -8)), handL=(8, -8, 0, "mitt", -1),
        armR=((42, -74), (58, -36), (42, -8)), handR=(42, -8, 170, "mitt", 1),
        props_top=(mug(28, -12, P, rot=0, steam=True),),
        badge=(0, -44, 6),
    )


# ------------------------------------------------------------ 9 offline
def pose_offline(P, uid):
    return figure(
        P, uid, head_rot=-8, head_dx=-2,
        eyes="open", look=(-4, 2), brows="flat", mouth="flat", feat=(-4, 1),
        legL=((-17, 4), (-17, 38), (-17, 70)), legR=((17, 4), (17, 38), (17, 70)),
        shoeL=(-18, 72, 0), shoeR=(18, 72, 0),
        armL=((-42, -74), (-72, -46), (-82, -62)),
        props_top=(phone(-84, -106, P, rot=-6, s=1.35, screen="nosignal"),),
        handL=(-82, -64, 272, "mitt", 1),
        **RELAX_R,
    )


# ------------------------------------------------------------ mini dex (bust)
def mini(P, uid, mood):
    kw = dict(bag=False, legL=((0, 0), (0, 0), (0, 0)), legR=((0, 0), (0, 0), (0, 0)))
    if mood == "neutral":
        fig = figure(P, uid, eyes="open", mouth="smile", brows="neutral", **RELAX_L, **RELAX_R, **kw)
    elif mood == "talk":
        fig = figure(P, uid, eyes="open", mouth="open", brows="raised", head_rot=-4, **RELAX_L, **RELAX_R, **kw)
    else:
        fig = figure(P, uid, eyes="up", look=(2, -2), mouth="hmm", brows="ask", head_rot=9, head_dx=2,
                     **RELAX_L, **RELAX_R, **kw)
    return fig


def mini_tile(P):
    o = []
    sub_h = 149
    for i, mood in enumerate(("neutral", "talk", "ask")):
        y0 = i * sub_h
        uid = f"m{i}"
        o.append(f'<clipPath id="mc{uid}"><rect x="12" y="{y0 + 12}" width="96" height="96" rx="0"/></clipPath>')
        o.append(f'<g clip-path="url(#mc{uid})">'
                 + g(mini(P, uid, mood), f"translate(60 {f(y0 + 12 + 170 * 0.56 + 42)}) scale(0.56)") + "</g>")
        # the open card (abstract, no text)
        o.append(f'<rect x="120" y="{y0 + 14}" width="236" height="{sub_h - 26}" rx="18" fill="#15181B"/>')
        o.append(f'<rect x="138" y="{y0 + 34}" width="120" height="10" rx="5" fill="#3A4046"/>')
        o.append(f'<rect x="138" y="{y0 + 56}" width="180" height="8" rx="4" fill="#262B30"/>')
        o.append(f'<rect x="138" y="{y0 + 72}" width="150" height="8" rx="4" fill="#262B30"/>')
        o.append(f'<rect x="138" y="{y0 + 94}" width="72" height="20" rx="10" fill="{P["teal"][2]}"/>')
        if i < 2:
            o.append(f'<rect x="12" y="{y0 + sub_h - 0.5}" width="344" height="1" fill="#1C1F22"/>')
    return "".join(o)


# ------------------------------------------------------------ tiles
def build_tiles():
    tiles = []
    tiles.append(("01-idle", "Idle", svg(place(pose_idle(P, "t1", 0)))))
    tiles.append(("02-listening", "Listening", svg(place(pose_listen(P, "t2"), x=172))))
    tiles.append(("03-thinking", "Thinking", svg(place(pose_think(P, "t3")))))
    tiles.append(("04-something-for-you", "Something for you", svg(place(pose_offer(P, "t4"), x=180))))
    tiles.append(("05-done", "Done", svg(place(pose_done(P, "t5"), x=192))))
    tiles.append(("06-speaking", "Speaking", svg(place(pose_speak(P, "t6"), x=172))))
    tiles.append(("07-payment-hold", "Payment hold", svg(place(pose_pay(P, "t7")))))
    tiles.append(("08-asleep", "Asleep", svg(place(pose_sleep(N, "t8"), y=HIPY + 24))))
    tiles.append(("09-offline", "Offline", svg(place(pose_offline(P, "t9"), x=200))))
    strip = []
    for i in range(4):
        strip.append(place(pose_idle(P, f"s{i}", [1, 2, 0, 3][i]), x=46 + 92 * i, y=262, s=0.42))
    for i in range(1, 4):
        strip.append(f'<rect x="{92 * i - 0.5}" y="120" width="1" height="200" fill="#1A1D20"/>')
    tiles.append(("10-idle-strip", "Idle strip", svg("".join(strip))))
    tiles.append(("11-mini-dex", "Mini Dex", svg(mini_tile(P))))
    home = place(pose_idle(P, "t12", 1), y=262)
    tiles.append(("12-home", "Home", svg(home)))
    return tiles


STATUS = ('<div style="position: absolute; left: 0; right: 0; top: 380px; text-align: center; '
          f'font-family: {FONT}; font-size: 20px; font-weight: 500; letter-spacing: -0.2px; '
          'line-height: 24px; color: #C7CDD1">Nothing needs you</div>')


def preview(tiles, cols=4, gap=40, pad=40):
    cells = "".join(f'<div class="t">{s}{STATUS if n.startswith("12") else ""}</div>' for n, _, s in tiles)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Dex SM-SHEET</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@500&display=swap" rel="stylesheet">
<style>
html,body{{margin:0;background:#2B2C30}}
.g{{display:grid;grid-template-columns:repeat({cols},{W}px);gap:{gap}px;padding:{pad}px;width:max-content}}
.t{{width:{W}px;height:{H}px;background:#000;position:relative}}
</style></head><body><div class="g">{cells}</div></body></html>"""


if __name__ == "__main__":
    tiles = build_tiles()
    if len(sys.argv) > 1:
        for name, _, sv in tiles:
            if name.startswith(sys.argv[1]):
                open(os.path.join(HERE, "t.svg"), "w").write(sv)
    open(os.path.join(HERE, "preview.html"), "w").write(preview(tiles))
    for name, _, s in tiles:
        open(os.path.join(HERE, "tiles", name + ".svg"), "w").write(s)
