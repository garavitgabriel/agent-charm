"""Dex Charm FINAL — BCKO base + MZCL Listening, fix list F2 applied.

Locked character: dex.py / sheet.py copied verbatim from character/smooth/.
Run: python3 build.py  -> preview.html, screens/*.html (one per screen), project/*.dc.html + canvas.json
"""
import os, sys, re, json, math, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dex import *          # locked character parts
import sheet               # locked poses
from sheet import (pose_idle, pose_think, pose_offer, pose_sleep, pose_offline, RELAX_L, RELAX_R)

W, H = 368, 448
P = PAL
N = PAL_NIGHT

# ---- UI tokens -------------------------------------------------------------
FG = "#F2EFE9"         # primary text
FG2 = "#D6D3CC"        # secondary text (>= #BDBDBD; one step up from BCKO #C4C1BA)
ON_ACC = "#0B0A12"     # text set on an accent fill
LINE = "#3B3A40"       # the separator rule
FLOOR = "#141316"      # Dex's ground shadow
BG = "#000000"
# night (dim) variants
LINE_N = "#1C1B20"
FLOOR_N = "#0A0A0C"
ACC_N = "#5E4A1C"      # dimmed gold: the accent at night (nothing bright)

ACCENTS = {
    # name: (accent, accent side-plane, accent highlight)
    "a": ("#B3A6FF", "#8E7FEA", "#D4CCFF"),   # BCKO purple (candidate, not used)
    "b": ("#F2C14E", "#D19F2B", "#F9DC94"),   # warm gold — CHOSEN, used on all 14 screens
    "c": ("#9FE3C4", "#6CC39D", "#CBF3E0"),   # soft mint
}

FONT = "'Instrument Sans', 'Helvetica Neue', Arial, sans-serif"
FONT_LINK = "https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&display=swap"
T18, T24, T32, T40 = 18, 24, 32, 40     # the only four sizes; <= 3 per screen; 40 = money only

PAD = 24               # outer gutter
SEP_Y = 206            # separator: content zone above, anchor zone below
SEP_W = 3              # separator stroke
DEX_X, DEX_Y = 236, 379   # Dex's hip anchor, every screen
S = 0.62               # Dex's one on-screen scale
FLOOR_Y = 433
RAIL_X, RAIL_W = PAD, 140  # action rail: left of Dex, inside the anchor zone


def place(content, x=DEX_X, y=DEX_Y, s=S):
    return g(content, f"translate({f(x)} {f(y)}) scale({f(s)})")


def floor(night=False):
    return ell(DEX_X, FLOOR_Y, 46, 46 * 0.16, FLOOR_N if night else FLOOR)


def separator(night=False, fuse=None, acc=None):
    x0, x1 = PAD, W - PAD
    col = LINE_N if night else LINE
    o = f'<line x1="{x0}" y1="{SEP_Y}" x2="{x1}" y2="{SEP_Y}" stroke="{col}" stroke-width="{SEP_W}" stroke-linecap="round"/>'
    if fuse is not None:
        xm = x0 + (x1 - x0) * fuse
        o += f'<line x1="{x0}" y1="{SEP_Y}" x2="{f(xm)}" y2="{SEP_Y}" stroke="{acc[0]}" stroke-width="{SEP_W}" stroke-linecap="round"/>'
    return o


def svg(inner):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'style="position: absolute; left: 0; top: 0; display: block">'
            f'<rect width="{W}" height="{H}" fill="{BG}"/>{inner}</svg>')


def txt(x, y, size, s, color=FG, weight=500, extra=""):
    lh = round(size * 1.18)
    return (f'<div style="position: absolute; left: {x}px; top: {y}px; font-size: {size}px; line-height: {lh}px; '
            f'font-weight: {weight}; color: {color}; letter-spacing: {"-0.4px" if size >= 30 else "-0.1px"}; '
            f'white-space: nowrap{extra}">{s}</div>')


def act(y, label, acc, w=RAIL_W, x=RAIL_X, lines=1):
    """text action: accent type on black, 56px+ hit area, no outline."""
    h = max(56, lines * 28 + 16)
    return (f'<button type="button" style="position: absolute; left: {x}px; top: {y}px; width: {w}px; height: {h}px; '
            f'box-sizing: border-box; background: transparent; border: 0; padding: 0; margin: 0; text-align: left; '
            f'color: {acc[0]}; font-family: {FONT}; font-size: {T24}px; line-height: 28px; font-weight: 600; '
            f'letter-spacing: -0.1px; white-space: nowrap">{label}</button>')


def big_act(y, label, acc, w=156, x=RAIL_X):
    """the money hold label: headline step (32), accent, two lines."""
    return (f'<div style="position: absolute; left: {x}px; top: {y}px; width: {w}px; font-size: {T32}px; '
            f'line-height: 36px; font-weight: 600; color: {acc[0]}; letter-spacing: -0.4px; white-space: nowrap">{label}</div>')


def pill(y, label, acc, w=RAIL_W, x=RAIL_X, lines=1, padx=20):
    """filled action: the default / primary, accent fill, no stroke."""
    h = max(56, lines * 28 + 16)
    return (f'<button type="button" style="position: absolute; left: {x}px; top: {y}px; width: {w}px; height: {h}px; '
            f'box-sizing: border-box; background: {acc[0]}; border: 0; border-radius: 28px; padding: 0 {padx}px; margin: 0; '
            f'text-align: left; color: {ON_ACC}; font-family: {FONT}; font-size: {T24}px; line-height: 28px; '
            f'font-weight: 600; letter-spacing: -0.1px; white-space: nowrap">{label}</button>')


# ---- props in the locked style --------------------------------------------
def placard(P, acc, cx, cy, w, h, rot=0):
    """flat sign on a stick (BCKO): accent-owned because it is the default tap target."""
    A, AD, AL = acc
    o = []
    o.append(line([(0, h / 2 - 4), (-18, h / 2 + 44)], P["ink"], 10))
    o.append(line([(0, h / 2 - 4), (-18, h / 2 + 44)], P["bag"][1], 5))
    x0, y0 = -w / 2, -h / 2
    o.append(f'<rect x="{f(x0)}" y="{f(y0)}" width="{f(w)}" height="{f(h)}" rx="14" fill="{A}" stroke="{P["ink"]}" stroke-width="3"/>')
    o.append(f'<path d="M {f(w/2 - 16)} {f(y0 + 3)} L {f(w/2 - 3)} {f(y0 + 3)} L {f(w/2 - 3)} {f(-y0 - 12)} '
             f'C {f(w/2 - 3)} {f(-y0 - 6)} {f(w/2 - 7)} {f(-y0 - 3)} {f(w/2 - 13)} {f(-y0 - 3)} L {f(w/2 - 16)} {f(-y0 - 3)} Z" fill="{AD}"/>')
    o.append(f'<rect x="{f(x0 + 3)}" y="{f(-y0 - 12)}" width="{f(w - 6)}" height="9" rx="4" fill="{AD}"/>')
    o.append(f'<rect x="{f(x0 + 10)}" y="{f(y0 + 9)}" width="7" height="{f(h - 36)}" rx="3.5" fill="{AL}"/>')
    return g("".join(o), f"translate({f(cx)} {f(cy)}) rotate({f(rot)})")


BAG_BODY = "M -27 -30 L 27 -30 L 29 30 C 29 34 27 36 23 36 L -23 36 C -27 36 -29 34 -29 30 Z"


def takeout_fill(P, acc, uid, x, y, s, prog, rot=0):
    """dex.takeout with the hold poured into it from the bottom up (accent)."""
    base = takeout(x, y, P, s=s, rot=rot)
    if prog <= 0:
        return base
    A, AD, AL = acc
    top = 36 - 66 * prog
    o = (f'<clipPath id="bag{uid}"><path d="{BAG_BODY}"/></clipPath>'
         f'<g clip-path="url(#bag{uid})">'
         f'<rect x="-31" y="{f(top)}" width="62" height="{f(40 - top)}" fill="{A}"/>'
         f'<rect x="17" y="{f(top)}" width="14" height="{f(40 - top)}" fill="{AD}"/>'
         f'<rect x="-25" y="{f(top + 4)}" width="5" height="{f(max(0, 30 - top))}" rx="2.5" fill="{AL}"/>'
         + (f'<path d="M -31 {f(top)} L 31 {f(top)}" stroke="{P["ink"]}" stroke-width="3.5"/>' if prog < 1 else "")
         + '</g>'
         + path(BAG_BODY, fill="none", stroke=P["ink"], sw=3))
    if prog >= 1:
        # full: the folded top band is re-drawn over the fill so the bag stays a bag
        o += path("M -27 -30 L 27 -30 L 27.4 -18 L -27.4 -18 Z", fill=A, stroke=P["ink"], sw=3)
        o += path("M -27.4 -18 L -21 -13 L -14 -18 L -7 -13 L 0 -18 L 7 -13 L 14 -18 L 21 -13 L 27.4 -18",
                  fill=A, stroke=P["ink"], sw=2.5)
    o += ell(0, 8, 11, 11, P["teal"][1], stroke=P["ink"], sw=2.5) + planet(0, 8, 1.0, P, color=P["mug"][0])
    return base + g(o, f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


def newspaper(P, x, y, s=1.0, rot=0):
    """the pocket edition, front page toward you: flat tones, ink outline."""
    w0, w1, w2 = P["shirt"]
    ink = P["ink"]
    o = []
    body = "M -50 -36 L 50 -36 L 50 36 L -50 36 Z"
    o.append(path(body, fill=w0, stroke=ink, sw=3))
    o.append(path("M 38 -34.5 L 48.5 -34.5 L 48.5 34.5 L 38 34.5 Z", fill=w2))
    o.append(path("M 0 -34 L 0 34", stroke=w1, sw=2.4))
    o.append(f'<rect x="-40" y="-28" width="80" height="9" rx="2" fill="{P["logo"]}"/>')
    o.append(f'<rect x="-40" y="-14" width="80" height="2.4" rx="1.2" fill="{P["line"]}"/>')
    o.append(f'<rect x="-40" y="-7" width="32" height="24" rx="2" fill="{P["pants"][0]}"/>')
    for i in range(4):
        o.append(f'<rect x="5" y="{-7 + i * 7}" width="{30 if i != 2 else 22}" height="3.4" rx="1.7" fill="{P["line"]}"/>')
    o.append(f'<rect x="-40" y="22" width="{26}" height="3.4" rx="1.7" fill="{P["line"]}"/>')
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


def voice_stream(p0, c1, c2, p1, pieces, color):
    """MZCL voice stream: irregular capsules along a curve — speech, not bars.
    (MZCL used a quadratic; here a cubic so the stream can clear Dex's head.)"""
    o = []
    t = 0.0

    def q(t):
        u = 1 - t
        return (u ** 3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * p1[0],
                u ** 3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * p1[1])
    for ln, gap, w in pieces:
        a, b = t, min(1, t + ln)
        o.append(line([q(a + (b - a) * k / 6) for k in range(7)], color, w))
        t = b + gap
        if t >= 1:
            break
    return "".join(o)


# ---- poses (14, none repeated, no pointing) --------------------------------
def pose_listen_in(P, uid):
    """MZCL: leans in, hand cupped at the ear, other fist tucked."""
    return figure(
        P, uid, body_rot=10, body_dx=4, head_rot=14, head_dx=6, head_dy=4,
        eyes="up", look=(2, -2), brows="raised", mouth="o", feat=(3, -2),
        legL=((-17, 4), (-24, 38), (-32, 70)), legR=((17, 4), (20, 38), (20, 70)),
        shoeL=(-34, 72, 0), shoeR=(21, 72, 0),
        armL=((-42, -74), (-68, -46), (-48, -18)), handL=(-47, -20, 40, "fist", 1),
        armR=((42, -74), (84, -94), (70, -118)), handR=(68, -122, 255, "cup", 1),
    )


def pose_present(P, uid):
    """answer: talking, palm lifted up toward the answer above him."""
    return figure(
        P, uid, body_rot=-3, head_rot=-6, head_dx=-2,
        eyes="open", look=(2, -2), brows="raised", mouth="open", feat=(2, -1),
        legL=((-17, 4), (-16, 38), (-12, 70)), legR=((17, 4), (22, 38), (26, 70)),
        shoeL=(-12, 72, 0), shoeR=(27, 72, 0),
        **RELAX_L,
        armR=((42, -74), (80, -82), (92, -124)), handR=(92, -128, 272, "open", -1, 1.15),
    )


def pose_ask(P, acc, uid):
    """decision (BCKO): holds up the default answer on a placard."""
    sign = placard(P, acc, 114, -190, 112, 92, rot=5)
    return figure(
        P, uid, body_rot=-3, head_rot=6, head_dx=2,
        eyes="up", look=(3, -3), brows="ask", mouth="smile", feat=(2, -1),
        legL=((-17, 4), (-20, 38), (-22, 70)), legR=((17, 4), (20, 38), (23, 70)),
        shoeL=(-23, 72, 0), shoeR=(24, 72, 0),
        **RELAX_L,
        armR=((42, -74), (80, -70), (92, -110)), handR=(92, -112, 262, "fist", -1),
        props_mid=(sign,),
    )


def pose_offer_bag(P, acc, uid):
    """money preview (BCKO): the bag held close at the chest, both hands, eyes on you."""
    return figure(
        P, uid, body_dy=2, head_dy=2,
        eyes="wide", brows="raised", mouth="tiny", look=(0, 1),
        legL=((-17, 4), (-22, 38), (-24, 70)), legR=((17, 4), (22, 38), (24, 70)),
        shoeL=(-25, 72, 0), shoeR=(25, 72, 0),
        armL=((-42, -74), (-72, -44), (-50, -40)), armR=((42, -74), (72, -44), (50, -40)),
        props_top=(takeout_fill(P, acc, uid, 0, -24, 1.72, 0),),
        handL=(-50, -42, 10, "mitt", -1), handR=(50, -42, 170, "mitt", 1),
        bag=False,
    )


def pose_lift(P, acc, uid, prog):
    """money mid-hold: one arm lifts the filling bag up and out to you; up on his toes."""
    return figure(
        P, uid, body_rot=6, body_dy=-4, head_rot=10, head_dx=4, head_dy=2,
        eyes="up", look=(4, -4), brows="focus", mouth="tiny", feat=(3, -2),
        legL=((-17, 4), (-20, 36), (-24, 64)), legR=((17, 4), (22, 38), (26, 70)),
        shoeL=(-26, 66, 18), shoeR=(28, 72, 0),
        armL=((-42, -74), (-74, -48), (-50, -22)), handL=(-48, -24, 30, "fist", 1),
        props_top=(takeout_fill(P, acc, uid, 104, -190, 1.72, prog, rot=8),),
        armR=((42, -74), (82, -100), (98, -140)), handR=(98, -142, 260, "mitt", -1),
        bag=False,
    )


def pose_handoff(P, acc, uid):
    """done: steps forward and hands you the full bag at arm's length, eyes closed in a satisfied nod."""
    return figure(
        P, uid, body_rot=5, head_rot=12, head_dx=3, head_dy=7,
        eyes="happy", brows="soft", mouth="grin", feat=(2, 3),
        legL=((-17, 4), (-26, 38), (-34, 68)), legR=((17, 4), (30, 34), (40, 66)),
        shoeL=(-36, 70, 0), shoeR=(41, 68, -6),
        armL=((-42, -74), (-58, -40), (-46, -8)), handL=(-46, -8, 95, "mitt", 1),
        armR=((42, -74), (86, -66), (122, -62)), handR=(124, -64, 90, "mitt", -1),
        props_front=(),
        props_top=(takeout_fill(P, acc, uid, 124, -10, 1.3, 1.0),),
        bag=False,
    )


def pose_lookout(P, uid):
    """tracker: arms folded, leaning back on one heel, eyes on the door, toe tapping."""
    return figure(
        P, uid, body_rot=-5, head_rot=-8, head_dx=-2,
        eyes="open", look=(5, 0), brows="flat", mouth="hmm", feat=(4, 0),
        legL=((-17, 4), (-26, 38), (-34, 70)), legR=((17, 4), (34, 32), (48, 58)),
        shoeL=(-35, 72, 0), shoeR=(50, 60, -24),
        armL=((-42, -74), (-56, -36), (22, -46)), handL=(24, -48, 350, "fist", -1),
        armR=((42, -74), (54, -34), (-18, -40)), handR=(-20, -42, 190, "fist", 1),
    )


def pose_paper(P, uid):
    """pocket edition: holds tonight's paper open, peeks over the top at you."""
    return figure(
        P, uid, head_rot=-4, head_dy=4,
        eyes="open", look=(0, 2), brows="neutral", mouth="smile", feat=(0, 1),
        legL=((-17, 4), (-19, 38), (-20, 70)), legR=((17, 4), (19, 38), (20, 70)),
        shoeL=(-20, 72, 0), shoeR=(20, 72, 0),
        armL=((-42, -74), (-76, -46), (-62, -46)), armR=((42, -74), (76, -46), (62, -46)),
        props_top=(newspaper(P, 0, -44, 1.25, rot=-3),),
        handL=(-62, -52, 20, "mitt", -1), handR=(62, -52, 160, "mitt", 1),
    )


def pose_shrug(P, uid):
    """needs more: both palms up, one brow up — which one?"""
    return figure(
        P, uid, head_rot=9, head_dx=2, body_dy=-2,
        eyes="up", look=(2, -2), brows="ask", mouth="hmm", feat=(2, -1),
        legL=((-17, 4), (-22, 38), (-26, 70)), legR=((17, 4), (22, 38), (26, 70)),
        shoeL=(-27, 72, 0), shoeR=(27, 72, 0),
        armL=((-42, -74), (-68, -50), (-76, -70)), handL=(-78, -74, 240, "open", 1),
        armR=((42, -74), (68, -50), (76, -70)), handR=(78, -74, 300, "open", -1),
    )


def pose_review(P, uid):
    """job done (sheet: something for you) — phone held up to show you; neutral list, no green."""
    return figure(
        P, uid, eyes="wide", brows="raised", mouth="smile", head_rot=-3,
        legL=((-17, 4), (-26, 38), (-32, 70)), legR=((17, 4), (26, 38), (32, 70)),
        shoeL=(-34, 72, 0), shoeR=(34, 72, 0),
        armL=((-42, -74), (-54, -40), (-50, -8)), handL=(-50, -8, 95, "mitt", 1),
        armR=((42, -74), (62, -66), (48, -70)),
        props_top=(phone(34, -82, P, rot=6, s=1.55, checks=0),),
        handR=(46, -44, 260, "mitt", -1),
    )


def pose_working(P, uid):
    """working (sheet: thinking) — head down over his phone; neutral list, no green."""
    return figure(
        P, uid, head_dy=12, head_rot=0, body_dy=3,
        eyes="down", brows="focus", mouth="hmm", feat=(0, 9), tuft=1,
        legL=((-15, 4), (-14, 38), (-13, 70)), legR=((15, 4), (14, 38), (13, 70)),
        shoeL=(-14, 72, 0), shoeR=(14, 72, 0),
        armL=((-42, -74), (-56, -36), (-24, -22)), handL=(-22, -22, 0, "mitt", -1),
        armR=((42, -74), (56, -36), (24, -22)), handR=(22, -24, 200, "mitt", 1),
        props_front=(phone(0, -30, P, rot=0, s=1.1, checks=0),),
        badge=None,
    )


# ---- screens: each returns (svg art, html layer) ---------------------------
def s_home(acc, u):
    art = floor() + separator() + place(pose_idle(P, u + "h", 0))
    t = txt(PAD, SEP_Y - 20 - 28, T24, "Nothing needs you", FG2, 500)
    return art, t


def s_listen(acc, u):
    art = floor() + separator(fuse=0.36, acc=acc) + place(pose_listen_in(P, u + "l"))
    pieces = [(0.07, 0.03, 10), (0.02, 0.025, 7), (0.12, 0.03, 10), (0.035, 0.04, 6),
              (0.09, 0.02, 9), (0.02, 0.035, 6), (0.06, 0.03, 8), (0.015, 0.03, 5),
              (0.05, 0.025, 7), (0.025, 0.04, 5), (0.03, 0.03, 6), (0.012, 0.03, 5), (0.02, 0.02, 5), (0.01, 0.02, 4)]
    art += voice_stream((-6, 322), (90, 196), (420, 190), (306, 306), pieces, acc[0])
    t = txt(PAD, PAD, T32, "I&#8217;m listening.")
    return art, t


def s_working(acc, u):
    art = floor() + separator() + place(pose_working(P, u + "w"))
    t = txt(PAD, PAD, T32, "Asking Coach Beard&#8230;") + txt(PAD, PAD + 46, T18, "Sunday&#8217;s lineup", FG2, 400)
    t += act(340, "Cancel", acc)
    return art, t


def s_answer(acc, u):
    art = floor() + separator() + place(pose_present(P, u + "a"))
    t = txt(PAD, PAD, T18, "What&#8217;s on tomorrow?", FG2, 400)
    t += txt(PAD, PAD + 28, T32, "Light day.")
    y = 100
    for tm, ev in (("9:30", "Design review"), ("11:00", "Lineup lock"), ("20:00", "Dinner")):
        t += txt(PAD, y + 5, T18, tm, FG2, 400) + txt(PAD + 64, y, T24, ev)
        y += 30
    t += txt(PAD, 396, T18, "Shortened. Ask<br>Dex for the rest.", FG2, 400)
    return art, t


def s_decision(acc, u):
    art = floor() + separator() + place(pose_ask(P, acc, u + "d"))
    # the placard's face is the default action (Yes, Sunday)
    cx, cy = DEX_X + 114 * S, DEX_Y - 190 * S
    t = txt(PAD, PAD, T32, "Pause Side Quest?") + txt(PAD, PAD + 46, T18, "Default: yes, Sunday.", FG2, 400)
    t += (f'<button type="button" aria-label="Yes, pause Sunday" style="position: absolute; left: {f(cx - 34)}px; '
          f'top: {f(cy - 28)}px; width: 68px; height: 56px; background: transparent; border: 0; padding: 0; margin: 0; '
          f'color: {ON_ACC}; font-family: {FONT}; font-size: {T24}px; line-height: 26px; font-weight: 600; '
          f'letter-spacing: -0.1px; transform: rotate(5deg)">Yes</button>')
    t += act(300, "No", acc, w=96) + act(362, "Later", acc, w=96)
    return art, t


def money_head():
    t = txt(PAD, PAD + 3, T18, "Corner Bistro", FG, 500)
    t += (f'<div style="position: absolute; left: {PAD}px; top: 62px; white-space: nowrap; color: {FG}; font-weight: 500">'
          f'<span style="font-size: {T40}px; line-height: 47px; letter-spacing: -0.4px">$18.40</span>'
          f'<span style="font-size: {T32}px; line-height: 47px; letter-spacing: -0.4px; margin-left: 8px">USD</span></div>')
    t += txt(PAD, 120, T18, "2 items · 35 min · Home", FG2, 400)
    return t


def s_money(acc, u):
    art = floor() + separator() + place(pose_offer_bag(P, acc, u + "m"))
    t = money_head() + big_act(300, "Hold Dex<br>to order", acc)
    return art, t


def s_hold(acc, u):
    art = floor() + separator() + place(pose_lift(P, acc, u + "k", 0.6))
    t = money_head() + txt(RAIL_X, 290, T32, "Ordering&#8230;", acc[0], 600)
    return art, t


def s_done(acc, u):
    art = floor() + separator() + place(pose_handoff(P, acc, u + "o"))
    t = txt(PAD, PAD, T32, "Ordered.") + txt(PAD, PAD + 44, T24, "Arriving 20:35.")
    t += txt(PAD, PAD + 82, T18, "Corner Bistro · Home", FG2, 400)
    return art, t


def s_tracker(acc, u):
    art = floor() + separator() + place(pose_lookout(P, u + "t"))
    # progress: a thin rail with four stops; the current stop is the headline
    x = PAD + 6
    stops = [("Preparing", 62), ("Picked up", 88), ("5 min away", 122), ("Arrived", 164)]
    art += f'<line x1="{x}" y1="{stops[0][1]}" x2="{x}" y2="{stops[2][1]}" stroke="{FG2}" stroke-width="3"/>'
    art += f'<line x1="{x}" y1="{stops[2][1]}" x2="{x}" y2="{stops[3][1]}" stroke="{LINE}" stroke-width="3"/>'
    t = txt(PAD, PAD, T18, "Corner Bistro · Delivery", FG2, 400)
    for i, (lab, y) in enumerate(stops):
        if i < 2:
            art += ell(x, y, 5, 5, FG2)
            t += txt(PAD + 24, y - 11, T18, lab, FG2, 400)
        elif i == 2:
            art += ell(x, y, 8, 8, FG)
            t += txt(PAD + 24, y - 19, T32, lab)
        else:
            art += ell(x, y, 5, 5, BG, stroke=LINE, sw=3)
            t += txt(PAD + 24, y - 11, T18, lab, FG2, 400)
    return art, t


def s_pocket(acc, u):
    art = floor() + separator() + place(pose_paper(P, u + "p"))
    t = txt(PAD, PAD, T18, "Edition 212 · Thursday", FG2, 400)
    t += txt(PAD, PAD + 32, T32, "Tonight: quiet day,<br>one thing matters.")
    t += act(340, "Read", acc, w=96)
    return art, t


def s_job(acc, u):
    art = floor() + separator() + place(pose_review(P, u + "j"))
    t = txt(PAD, PAD, T18, "PR #42 · review done", FG2, 400)
    t += txt(PAD, PAD + 28, T32, "1 blocking, 2 nits")
    t += pill(226, "Send to<br>Claude Code", acc, w=170, lines=2, padx=14) + act(318, "Later", acc, w=96)
    return art, t


def s_night(acc, u):
    art = floor(night=True) + separator(night=True) + place(pose_sleep(N, u + "n"))
    return art, ""


def s_offline(acc, u):
    art = floor() + separator() + place(pose_offline(P, u + "f"))
    t = txt(PAD, PAD, T32, "No connection")
    t += txt(PAD, PAD + 46, T18, "Nothing is sent or ordered<br>until it&#8217;s back.", FG2, 400)
    t += act(362, "Try again", acc, w=120)
    return art, t


def s_needs(acc, u):
    art = floor() + separator() + place(pose_shrug(P, u + "q"))
    t = txt(PAD, PAD, T32, "Which Corner<br>Bistro, Downtown<br>or Riverside?")
    t += pill(282, "Downtown", acc, w=148, padx=18) + pill(354, "Riverside", acc, w=148, padx=18)
    return art, t


SCREENS = [
    ("01-home", "Home", "Home / Idle", s_home),
    ("02-listening", "Listening", "Listening", s_listen),
    ("03-working", "Working", "Working", s_working),
    ("04-answer", "Answer", "Answer", s_answer),
    ("05-decision", "Decision", "Decision", s_decision),
    ("06-money-preview", "MoneyPreview", "Money preview", s_money),
    ("07-money-mid-hold", "MoneyHold", "Money mid-hold", s_hold),
    ("08-done", "Done", "Done", s_done),
    ("09-live-tracker", "Tracker", "Live tracker", s_tracker),
    ("10-pocket-edition", "PocketEdition", "Pocket edition", s_pocket),
    ("11-job-done", "JobDone", "Job done", s_job),
    ("12-night", "Night", "Night / dim Home", s_night),
    ("13-offline", "Offline", "Offline", s_offline),
    ("14-needs-more", "NeedsMore", "Needs more", s_needs),
]
ACCENT_ROW = [("accent-a", "AccentA", "Accent A", "a"), ("accent-b", "AccentB", "Accent B", "b"),
              ("accent-c", "AccentC", "Accent C", "c")]


def all_boards():
    out = []
    for slug, name, title, fn in SCREENS:
        art, t = fn(ACCENTS["b"], slug[:2])
        out.append((slug, name, title, svg(art) + t))
    return out


def screen_div(body):
    return (f'<div style="width: 368px; height: 448px; position: relative; overflow: hidden; background: #000000; '
            f'font-family: {FONT}">{body}</div>')


CSS_BASE = "button{cursor:pointer}"


def preview(boards):
    rows = [boards[0:7], boards[7:14]]
    cells = ""
    for r in rows:
        cells += '<div class="r">' + "".join(f'<div class="t">{screen_div(b)}</div>' for *_, b in r) + "</div>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Dex Charm FINAL</title>
<link href="{FONT_LINK}" rel="stylesheet">
<style>
html,body{{margin:0;background:#2B2C30}}
.g{{display:flex;flex-direction:column;gap:40px;padding:40px;width:max-content}}
.r{{display:flex;gap:40px}}
.t{{width:368px;height:448px}}
{CSS_BASE}
</style></head><body><div class="g">{cells}</div></body></html>"""


def single(body):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Dex screen</title>
<link href="{FONT_LINK}" rel="stylesheet">
<style>html,body{{margin:0;background:#000;overflow:hidden}}{CSS_BASE}</style></head>
<body>{screen_div(body)}</body></html>"""


def close_tags(x):
    return re.sub(r'<(\w+)([^<>]*?)/>', r'<\1\2></\1>', x)


def dc(title, body):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dex {title}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<link rel="stylesheet" href="{FONT_LINK.replace('&', '&amp;')}">
<style>
body{{margin:0;background:#000}}
</style>
</helmet>
{close_tags(screen_div(body))}
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{"$preview":{{"width":368,"height":448}}}}'>
class Component extends DCLogic {{
renderVals() {{
return {{}};
}}
}}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    boards = all_boards()
    open(os.path.join(HERE, "preview.html"), "w").write(preview(boards))
    os.makedirs(os.path.join(HERE, "screens"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "project"), exist_ok=True)
    for slug, _, _, b in boards:
        open(os.path.join(HERE, "screens", slug + ".html"), "w").write(single(b))
    bd, order = {}, []
    for i, (slug, name, title, b) in enumerate(boards):
        fn = ("Main" if i == 0 else name) + ".dc.html"
        open(os.path.join(HERE, "project", fn), "w").write(dc(title, b))
        row, col = (0, i) if i < 7 else ((1, i - 7) if i < 14 else (2, i - 14))
        bd[fn] = {"x": col * (368 + 80), "y": row * (448 + 120), "w": 368, "h": 448,
                  "title": (f"{i + 1}. {title}" if i < 14 else title)}
        order.append(fn)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    canvas = {"v": 3, "createdOnFiles": {"v": 1, "at": now}, "title": "Dex Charm · FINAL",
              "launch": {"view": "canvas"}, "pages": [], "boards": bd, "order": order, "notes": {},
              "designSystems": []}
    json.dump(canvas, open(os.path.join(HERE, "project", "canvas.json"), "w"), ensure_ascii=False, indent=1)
    print(len(boards), "boards")
