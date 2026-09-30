"""Coach Beard: the charm's second character (docs/COACH.md, BRIEF § 11.7 character-swap contract).

Drawn in Dex's locked idiom, reusing dex.py's primitives unchanged: flat tonal steps (three per
material), one ink outline weight, no gradients, the same face construction and hands, and the same
figure() skeleton and keyword schema. The export (tools/charm_assets/dex_export.py) can therefore
capture Coach's poses exactly the way it captures Dex's.

Identity, from docs/coach/coach-reference.jpg (pixel reference; identity only, not style):
- an orange pom beanie with a navy ribbed cuff and a small orange tag;
- a black headset over the beanie, with a boom mic;
- a long, full brown beard;
- a steel whistle on a cord;
- an orange jacket with navy collar, hem and sleeve bands, over grey undersleeves;
- brown trousers and dark boots;
- his prop, the wall calendar with one date circled, plus a tablet for "watching film".

Nothing here imports build.py, so it's safe to import from the export as well as from build_coach.py.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FINAL_SRC = os.path.abspath(os.path.join(HERE, "..", "..", "src"))
if FINAL_SRC not in sys.path:
    sys.path.insert(0, FINAL_SRC)

import dex                                   # noqa: E402  locked Dex parts (read-only)
from dex import (INK, dim, f, pts, ell, path, line, g, rot_pt, normal, lerp, hand,  # noqa: E402,F401
                 leg, shoe)

# ----------------------------------------------------------------- palette
# The jacket orange is the one colour that can collide with the gold accent (§ 11.7 rule 5).
# JACKETS holds the candidates tested in accent-compare; JACKET_PICK is the one that ships.
JACKETS = {
    # name: (highlight, base, side plane)
    "ref":   ("#F59A4E", "#E8742C", "#B9561C"),   # the reference's orange, as drawn
    "burnt": ("#E07A45", "#C8551E", "#9A3F14"),   # burnt orange: redder and darker than the ref
    "rust":  ("#C0694A", "#A84E2E", "#7E381F"),   # rust: far below the gold in value
}
NAVY = ("#44557F", "#2B3A60", "#1C2744")
JACKET_PICK = "burnt"  # the orange: beanie, trim, circled date
NAVY_LED = True        # D: navy jacket body, burnt trim. the owner's pick at the fixed point, 2026-09-29
                      # (it replaced the burnt-jacket skin that shipped 2026-09-28; coach.md § Accent)


def make_pal(jacket=JACKET_PICK, navy_led=NAVY_LED):
    """Coach's day palette. navy_led swaps the jacket body to navy and keeps orange as trim."""
    j = JACKETS[jacket]
    body, trim = (NAVY, j) if navy_led else (j, NAVY)
    return {
        "ink": INK,
        "skin": ("#F6CBA4", "#E4A67C", "#C4825C"),      # a shade ruddier than Dex (outdoors)
        "beard": ("#8E5A38", "#6A4029", "#4A2A1B"),
        "brow": "#4A2A1B",
        "jacket": body,
        "trim": trim,                                    # collar, hem, sleeve band, beanie cuff
        "beanie": j,                                     # the beanie is always the orange
        "sleeve": ("#E6E9EC", "#C3C9CF", "#949CA5"),     # grey undersleeve (forearms)
        "pants": ("#B88A5E", "#96693F", "#6E4B2B"),      # brown trousers
        "shoe": ("#5E636C", "#43474F", "#2C2F35"),       # dark boots (dex.shoe reads "shoe")
        "headset": ("#4A4F58", "#30343B", "#1E2126"),
        "led": "#AEB8BF",                                # a plain light-grey LED, never green
        "steel": ("#E4E8EC", "#AEB6BE", "#7D868F"),      # the whistle
        "cord": "#2A3038",
        "page": ("#FFFFFF", "#E9EEF0", "#C3CDD2"),        # calendar page
        "cell": "#A7B1B8",
        "circle": j[2],                                  # the circled date: his own orange, never gold
        "frame": ("#4A515C", "#2E333B", "#1E2228"),       # the tablet
        "screen": ("#F3F7F8", "#DCE4E7"),
        "play": "#6F7A83",
        "blush": "#E88E78",
        "mouth": "#3A1712",
        "tongue": "#E0716A",
        "teeth": "#FFFFFF",
        "eyehi": "#FFFFFF",
        "stool": ("#77808E", "#5A6270", "#424955"),
        "moon": "#C9D0D5",
    }


def night(p):
    """The night palette, made with dex.dim_pal: the same rule that dims Dex."""
    return dex.dim_pal(p)


PAL = make_pal()
PAL_NIGHT = night(PAL)


# ----------------------------------------------------------------- props
def whistle(x, y, P, rot=0, s=1.0):
    """steel whistle, mouthpiece toward +x."""
    s0, s1, s2 = P["steel"]
    ink = P["ink"]
    o = [path("M 6 -4 L 20 -4 C 22 -4 23 -3 23 -1 L 23 2 C 23 4 22 5 20 5 L 6 5 Z", fill=s1, stroke=ink, sw=2.6),
         ell(-2, 1, 11, 9, s1, stroke=ink, sw=2.6),
         path("M -2 5.5 C 4 5.5 8 3 9 -1 L 9 9 L -2 10 Z", fill=s2),
         ell(-5, -2.5, 3.6, 2.4, s0),
         ell(-2, 1, 3, 3, s2),
         path("M 8 -1 L 20 -1", stroke=s0, sw=1.8)]
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


def calendar(x, y, P, rot=0, s=1.0, circled=True):
    """the wall calendar, page toward you: header band in his orange, rings, a dot grid, one date
    circled in his own orange (a character colour, not the accent). No numerals: at 0.62 they'd
    be noise."""
    p0, p1, p2 = P["page"]
    j0, j1, j2 = P["beanie"]
    ink = P["ink"]
    o = []
    page = "M -28 -22 L 28 -22 L 28 26 C 28 30 26 32 22 32 L -22 32 C -26 32 -28 30 -28 26 Z"
    o.append(path(page, fill=p0, stroke=ink, sw=3))
    o.append(path("M 20 -20.5 L 26.5 -20.5 L 26.5 26 C 26.5 29 25 30.5 22 30.5 L 20 30.5 Z", fill=p1))
    o.append(path("M 16 30.5 L 26.5 20 L 26.5 26 C 26.5 29 25 30.5 22 30.5 Z", fill=p2))   # page curl
    o.append(path("M -28 -34 L 28 -34 L 28 -20 L -28 -20 Z", fill=j1, stroke=ink, sw=3))
    o.append(path("M 18 -32.5 L 26.5 -32.5 L 26.5 -21.5 L 18 -21.5 Z", fill=j2))
    for i in range(5):
        rx = -20 + i * 10
        o.append(path(f"M {f(rx)} -30 L {f(rx)} -39", stroke=ink, sw=3.4))
    for r in range(4):
        for c in range(5):
            cx, cy = -18 + c * 9, -12 + r * 10
            o.append(f'<rect x="{f(cx - 2.6)}" y="{f(cy - 1.5)}" width="5.2" height="3" rx="1.5" fill="{P["cell"]}"/>')
    if circled:
        o.append(ell(-9, -2, 6.6, 5.6, "none", rot=-8, stroke=P["circle"], sw=2.8))
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


def tablet(x, y, P, rot=0, s=1.0, frame=0):
    """landscape tablet showing a play diagram: 'watching film'. Neutral greys, no field green.
    frame 1 draws the route one step further (the export's working loop)."""
    f0, f1, f2 = P["frame"]
    sc0, sc1 = P["screen"]
    ink, pl = P["ink"], P["play"]
    o = [path("M -34 -22 L 34 -22 C 37 -22 38 -21 38 -18 L 38 18 C 38 21 37 22 34 22 L -34 22 "
              "C -37 22 -38 21 -38 18 L -38 -18 C -38 -21 -37 -22 -34 -22 Z", fill=f1, stroke=ink, sw=3),
         path("M 32 -20 L 36 -19 L 36 18 C 36 19.5 35 20 33 20 L 28 20 Z", fill=f2),
         path("M -32 -17 L 32 -17 L 32 17 L -32 17 Z", fill=sc0),
         path("M -32 8 L 32 8 L 32 17 L -32 17 Z", fill=sc1),
         path("M -30 0 L 30 0", stroke=sc1, sw=1.6)]            # line of scrimmage
    for ox in (-12, 0, 12):                                      # O's: the line
        o.append(ell(ox, 4, 3.4, 3.4, "none", stroke=pl, sw=1.8))
    for xx, yy in ((-20, -9), (20, -9), (-4, -10)):              # X's: the defence
        o.append(path(f"M {f(xx - 3)} {f(yy - 3)} L {f(xx + 3)} {f(yy + 3)} M {f(xx + 3)} {f(yy - 3)} "
                      f"L {f(xx - 3)} {f(yy + 3)}", stroke=pl, sw=1.8))
    route = [(12, 4), (18, -4), (26, -12)] if frame == 0 else [(12, 4), (18, -4), (22, -13), (28, -14)]
    o.append(line(route, ink, 1.8))
    tip = route[-1]
    o.append(ell(tip[0], tip[1], 2, 2, ink))
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


# ----------------------------------------------------------------- hands (dex.hand + a thumbs-up)
def thumbs_up(x, y, P, s=1.0, side=1):
    """a fist with the thumb straight up. side=1 thumb on +x of the knuckles."""
    s0, s1, s2 = P["skin"]
    ink = P["ink"]
    tx = x + side * 2 * s
    o = [line([(tx, y - 4 * s), (tx, y - 20 * s)], ink, 11 * s),
         line([(tx, y - 4 * s), (tx, y - 20 * s)], s1, 5.4 * s),
         ell(x, y + 3 * s, 11.5 * s, 10 * s, s2, stroke=ink, sw=3),
         ell(x - 1.6, y + 1.6, 9 * s, 7.6 * s, s1),
         path(f"M {f(x - 8 * s)} {f(y + 4 * s)} L {f(x + 6 * s)} {f(y + 4 * s)} M {f(x - 8 * s)} {f(y + 8.5 * s)} "
              f"L {f(x + 6 * s)} {f(y + 8.5 * s)}", stroke=s2, sw=2.2),
         ell(x - 4 * s, y - 1 * s, 2.4 * s, 2 * s, s0)]
    return "".join(o)


def chand(x, y, ang, P, kind="mitt", thumb=1, s=1.0):
    if kind == "thumb":
        return thumbs_up(x, y, P, s=s, side=thumb)
    return hand(x, y, ang, P, kind=kind, thumb=thumb, s=s)


# ----------------------------------------------------------------- limbs
def carm(S, E, H, P):
    """jacket upper arm with a navy band above the elbow; grey undersleeve forearm (the reference's
    two-tone sleeve). The jacket sleeve overlaps the forearm at the elbow."""
    j0, j1, j2 = P["jacket"]
    n0, n1, n2 = P["trim"]
    v0, v1, v2 = P["sleeve"]
    ink = P["ink"]
    Hc = lerp(E, H, 0.86)
    o = [line([S, E, Hc], ink, 29)]
    # forearm (undersleeve)
    o.append(line([E, Hc], v1, 23))
    nx, ny = normal(E, Hc)
    o.append(line([(E[0] + nx * 5.5, E[1] + ny * 5.5), (Hc[0] + nx * 5.5, Hc[1] + ny * 5.5)], v2, 7))
    o.append(line([(E[0] - nx * 5.8, E[1] - ny * 5.8), (lerp(E, Hc, 0.75)[0] - nx * 5.8, lerp(E, Hc, 0.75)[1] - ny * 5.8)], v0, 3.6))
    # upper arm (jacket), drawn over the forearm top
    o.append(line([S, E], j1, 23))
    nx, ny = normal(S, E)
    o.append(line([(S[0] + nx * 5.5, S[1] + ny * 5.5), (E[0] + nx * 5.5, E[1] + ny * 5.5)], j2, 7))
    o.append(line([(S[0] - nx * 5.8, S[1] - ny * 5.8), (lerp(S, E, 0.7)[0] - nx * 5.8, lerp(S, E, 0.7)[1] - ny * 5.8)], j0, 3.6))
    # navy band above the elbow
    b0, b1 = lerp(S, E, 0.5), lerp(S, E, 0.72)
    o.append(line([b0, b1], n1, 23, cap="butt"))
    o.append(line([(b0[0] + nx * 5.5, b0[1] + ny * 5.5), (b1[0] + nx * 5.5, b1[1] + ny * 5.5)], n2, 7, cap="butt"))
    # the sleeve's edge where the jacket meets the undersleeve
    ex, ey = normal(S, E)
    e0 = (E[0] + ex * 11.5, E[1] + ey * 11.5)
    e1 = (E[0] - ex * 11.5, E[1] - ey * 11.5)
    o.append(line([e0, e1], ink, 2.4))
    return "".join(o)


# ----------------------------------------------------------------- head
FACE = ("M -47 -70 C -47 -100 -28 -110 0 -110 C 28 -110 47 -100 47 -70 L 47 -44 "
        "C 47 -17 27 -3 0 -3 C -27 -3 -47 -17 -47 -44 Z")
BEARD = ("M -48 -66 L -48 -42 C -48 -12 -36 12 -16 22 C -6 27 6 27 16 22 C 36 12 48 -12 48 -42 L 48 -66 "
         "C 46 -52 40 -40 30 -37 C 22 -35 16 -39 10 -40 C 5 -41 -5 -41 -10 -40 "
         "C -16 -39 -22 -35 -30 -37 C -40 -40 -46 -52 -48 -66 Z")
BROWS = {   # (side, y, rotation): heavier and lower than Dex's, under the beanie cuff
    "neutral": ((-1, -71, -4), (1, -71, 4)),
    "raised": ((-1, -75, -10), (1, -75, 10)),
    "flat": ((-1, -70, 0), (1, -70, 0)),
    "soft": ((-1, -72, 8), (1, -72, -8)),
    "ask": ((-1, -71, -2), (1, -77, 14)),
    "focus": ((-1, -69, 10), (1, -69, -10)),
}


def beanie(P, uid, dy=0):
    """pom beanie in head-local units. dy pulls the whole hat down over the eyes (asleep)."""
    b0, b1, b2 = P["beanie"]
    n0, n1, n2 = P["trim"]
    ink = P["ink"]
    o = []
    dome = ("M -53 -86 C -56 -118 -34 -144 0 -144 C 34 -144 56 -118 53 -86 Z")
    o.append(f'<clipPath id="bn{uid}"><path d="{dome}"/></clipPath>')
    o.append(path(dome, fill=b1, stroke=ink, sw=3))
    o.append(f'<g clip-path="url(#bn{uid})">'
             + path("M 26 -150 C 44 -128 50 -106 48 -86 L 60 -86 L 60 -150 Z", fill=b2)
             + path("M -40 -122 C -36 -132 -26 -138 -16 -140 C -26 -132 -32 -124 -34 -114 Z", fill=b0)
             + "".join(path(f"M {x} -86 C {x * 0.9} -110 {x * 0.6} -130 {x * 0.3} -144", stroke=b2, sw=2.2)
                       for x in (-30, -10, 10, 30))
             + "</g>")
    o.append(path(dome, fill="none", stroke=ink, sw=3))
    # pom-pom, off to the left like the reference
    o.append(ell(-14, -150, 12, 11, b1, stroke=ink, sw=3))
    o.append(ell(-17, -153, 6, 5, b0))
    o.append(path("M -6 -144 C -4 -150 -6 -156 -10 -160", stroke=b2, sw=2.2))
    # ribbed cuff
    cuff = "M -55 -96 C -30 -103 30 -103 55 -96 L 55 -75 C 30 -81 -30 -81 -55 -75 Z"
    o.append(path(cuff, fill=n1, stroke=ink, sw=3))
    o.append(path("M 36 -99 C 44 -98 50 -97 53.5 -96 L 53.5 -76.5 C 48 -78 42 -79 36 -79.5 Z", fill=n2))
    for x in range(-44, 44, 9):
        o.append(path(f"M {x} -98 L {x} -81", stroke=n2, sw=1.8))
    o.append(path("M 8 -95 L 24 -94 L 24 -84 L 8 -85 Z", fill=b1, stroke=ink, sw=2))   # the tag
    return g("".join(o), f"translate(0 {f(dy)})")


def headset(P, led=True, droop=False, band=True):
    """band over the beanie, ear cups over the ears, boom mic from the left cup."""
    h0, h1, h2 = P["headset"]
    ink = P["ink"]
    o = []
    if band:
        arc = "M -54 -70 C -60 -118 -34 -148 0 -148 C 34 -148 60 -118 54 -70"
        o.append(path(arc, stroke=ink, sw=10))
        o.append(path(arc, stroke=h1, sw=5))
    for sx in (-1, 1):
        cx = sx * 52
        o.append(f'<rect x="{f(cx - 10)}" y="-74" width="20" height="32" rx="9" fill="{h1}" stroke="{ink}" stroke-width="3"/>')
        o.append(f'<rect x="{f(cx + (2 if sx > 0 else -8))}" y="-71" width="6" height="26" rx="3" fill="{h2}"/>')
        o.append(f'<rect x="{f(cx - (6 if sx > 0 else -2))}" y="-70" width="3" height="12" rx="1.5" fill="{h0}"/>')
    if led:
        o.append(ell(-52, -52, 2.4, 2.4, P["led"]))
    boom = "M -50 -46 C -48 -34 -38 -30 -24 -30" if not droop else "M -50 -46 C -50 -34 -50 -26 -46 -14"
    o.append(path(boom, stroke=ink, sw=7))
    o.append(path(boom, stroke=h1, sw=3))
    tip = (-22, -30) if not droop else (-45, -12)
    o.append(ell(tip[0], tip[1], 5, 4.2, h1, stroke=ink, sw=2.4))
    return "".join(o)


def chead(P, uid, eyes="open", brows="neutral", mouth="smile", look=(0, 0), blush=True, feat=(0, 0),
          beanie_dy=0, led=True, droop=False, whistle_mouth=False):
    s0, s1, s2 = P["skin"]
    d0, d1, d2 = P["beard"]
    ink = P["ink"]
    o = []
    o.append(f'<clipPath id="fc{uid}"><path d="{FACE}"/></clipPath>')
    o.append(path(FACE, fill=s1, stroke=ink, sw=3))
    o.append(f'<g clip-path="url(#fc{uid})">'
             + path("M 30 -115 C 44 -100 48 -70 44 -40 C 40 -20 28 -8 10 0 L 60 0 L 60 -115 Z", fill=s2)
             + ell(-28, -80, 8, 5, s0, rot=-20) + "</g>")
    o.append(path(FACE, fill="none", stroke=ink, sw=3))
    # the long beard, over the jaw and down onto the chest
    o.append(path(BEARD, fill=d1, stroke=ink, sw=2.8))
    o.append(f'<clipPath id="bd{uid}"><path d="{BEARD}"/></clipPath>')
    o.append(f'<g clip-path="url(#bd{uid})">'
             + path("M 24 -40 C 40 -40 46 -54 52 -66 L 52 30 L 4 30 C 24 18 34 2 38 -18 Z", fill=d2)
             + path("M -40 -34 C -36 -16 -30 -2 -18 10 C -30 4 -40 -10 -44 -30 Z", fill=d0)
             + path("M -14 2 C -12 10 -8 16 -4 20", stroke=d2, sw=2.4)
             + path("M 6 4 C 8 12 10 16 12 19", stroke=d2, sw=2.4)
             + path("M -26 -8 C -24 2 -20 8 -16 12", stroke=d2, sw=2.2)
             + "</g>")
    o.append(beanie(P, uid, beanie_dy))
    o.append(headset(P, led=led, droop=droop))
    base = len(o)
    # nose
    o.append(path("M -6 -50 C -6 -42 6 -42 6 -50 C 6 -46 -6 -46 -6 -50 Z", fill=s2))
    o.append(ell(0, -48, 6.4, 5.4, s1, stroke=ink, sw=2.4))
    o.append(ell(-2, -49.5, 2.4, 2, s0))
    if blush:
        o.append(ell(-30, -48, 6, 3.2, P["blush"]))
        o.append(ell(30, -48, 6, 3.2, P["blush"]))
    lx, ly = look
    if beanie_dy < 14:   # the eyes are hidden when the beanie is pulled down
        for sx in (-1, 1):
            ex, ey = sx * 18, -60
            if eyes in ("open", "up", "wide"):
                ry = 7.4 if eyes != "wide" else 8.6
                rx = 5.2 if eyes != "wide" else 5.8
                o.append(ell(ex + lx, ey + ly, rx, ry, ink))
                o.append(ell(ex + lx - 1.6, ey + ly - 3, 1.9, 2.1, P["eyehi"]))
            elif eyes == "down":
                o.append(ell(ex, ey + 3, 5.2, 5.8, ink))
                o.append(path(f"M {f(ex - 8)} {f(ey - 8)} L {f(ex + 8)} {f(ey - 8)} L {f(ex + 8)} {f(ey + 2)} "
                              f"C {f(ex + 4)} {f(ey + 0.5)} {f(ex - 4)} {f(ey + 0.5)} {f(ex - 8)} {f(ey + 2)} Z", fill=s1))
                o.append(path(f"M {f(ex - 7.5)} {f(ey + 2)} C {f(ex - 4)} {f(ey + 0.2)} {f(ex + 4)} {f(ey + 0.2)} {f(ex + 7.5)} {f(ey + 2)}",
                              stroke=ink, sw=3.2))
            elif eyes == "happy":
                o.append(path(f"M {f(ex - 6.5)} {f(ey + 3)} C {f(ex - 3)} {f(ey - 4)} {f(ex + 3)} {f(ey - 4)} {f(ex + 6.5)} {f(ey + 3)}",
                              stroke=ink, sw=3.8))
            elif eyes == "sleep":
                o.append(path(f"M {f(ex - 6.5)} {f(ey + 2)} C {f(ex - 3)} {f(ey + 6)} {f(ex + 3)} {f(ey + 6)} {f(ex + 6.5)} {f(ey + 2)}",
                              stroke=ink, sw=3.2))
            elif eyes == "blink":
                o.append(path(f"M {f(ex - 6)} {f(ey + 1)} L {f(ex + 6)} {f(ey + 1)}", stroke=ink, sw=3.6))
        for sx, by, rt in BROWS[brows]:
            o.append(f'<rect x="{f(sx * 19 - 10)}" y="{f(by - 3.4)}" width="20" height="6.8" rx="3.4" fill="{P["brow"]}" '
                     f'transform="rotate({f(rt)} {f(sx * 19)} {f(by)})"/>')
    # mustache, then the mouth inside it
    o.append(path("M -18 -35 C -12 -42 -4 -41 0 -37 C 4 -41 12 -42 18 -35 C 14 -30 6 -31 0 -33 "
                  "C -6 -31 -14 -30 -18 -35 Z", fill=d1, stroke=ink, sw=2.2))
    o.append(path("M 2 -37 C 6 -40 12 -40 16 -35.5 C 12 -33 7 -33 2 -35 Z", fill=d2))
    my = -27
    if whistle_mouth:
        o.append(whistle(10, my + 1, P, rot=-8, s=0.95))
    elif mouth == "smile":
        o.append(path(f"M -7 {my - 1} C -3 {my + 4} 3 {my + 4} 7 {my - 1}", stroke=P["mouth"], sw=3.4))
    elif mouth == "grin":
        o.append(path(f"M -10 {my - 3} C -6 {my + 6} 6 {my + 6} 10 {my - 3} Z", fill=P["mouth"], stroke=P["mouth"], sw=2.4))
        o.append(path(f"M -7 {my - 2.4} L 7 {my - 2.4} L 6 {my} L -6 {my} Z", fill=P["teeth"]))
    elif mouth == "open":
        o.append(path(f"M -8 {my - 4} C -8 {my + 8} 8 {my + 8} 8 {my - 4} C 4 {my - 6} -4 {my - 6} -8 {my - 4} Z",
                      fill=P["mouth"], stroke=P["mouth"], sw=2))
        o.append(path(f"M -4.5 {my + 3.5} C -2 {my + 1} 3 {my + 1} 5.5 {my + 3.5} C 3 {my + 6} -3 {my + 6} -4.5 {my + 3.5} Z", fill=P["tongue"]))
    elif mouth == "o":
        o.append(ell(0, my + 1, 4, 4.8, P["mouth"]))
    elif mouth == "flat":
        o.append(path(f"M -6 {my + 1} L 6 {my + 1}", stroke=P["mouth"], sw=3.2))
    elif mouth == "hmm":
        o.append(path(f"M -6 {my + 2} C -2 {my} 3 {my} 6 {my + 1}", stroke=P["mouth"], sw=3.2))
    elif mouth == "sleep":
        o.append(ell(0, my + 1, 3, 2.6, P["mouth"]))
    elif mouth == "tiny":
        o.append(path(f"M -5 {my} C -2 {my + 3} 2 {my + 3} 5 {my}", stroke=P["mouth"], sw=3))
    feats = "".join(o[base:])
    return "".join(o[:base]) + g(feats, f"translate({f(feat[0])} {f(feat[1])})")


# ----------------------------------------------------------------- torso
BODY = ("M -28 -88 C -42 -88 -50 -82 -50 -68 L -48 2 C -48 10 -44 14 -36 14 L 36 14 "
        "C 44 14 48 10 48 2 L 50 -68 C 50 -82 42 -88 28 -88 Z")


def ctorso(P, uid):
    j0, j1, j2 = P["jacket"]
    n0, n1, n2 = P["trim"]
    s0, s1, s2 = P["skin"]
    t0, t1, t2 = P["steel"]
    ink = P["ink"]
    o = [f'<rect x="-10" y="-100" width="20" height="18" fill="{s2}" stroke="{ink}" stroke-width="3"/>',
         f'<clipPath id="tc{uid}"><path d="{BODY}"/></clipPath>',
         path(BODY, fill=j1, stroke=ink, sw=3)]
    inner = [
        path("M 32 -95 C 38 -60 38 -20 34 16 L 60 16 L 60 -95 Z", fill=j2),                  # side plane
        path("M -46 -76 C -44 -60 -44 -30 -42 -4 L -38 -4 C -40 -30 -40 -60 -40 -80 Z", fill=j0),
        path("M -60 -2 L 60 -2 L 60 20 L -60 20 Z", fill=n1),                                  # navy hem
        path("M 34 -2 L 60 -2 L 60 20 L 34 20 Z", fill=n2),
        path("M -60 -2 L 60 -2", stroke=ink, sw=2.4),
        path("M 2 -90 C 2 -60 2 -30 2 16", stroke=ink, sw=2.4),                               # zip
        path("M 5 -88 C 5 -60 5 -30 5 -3", stroke=j2, sw=2.4),
        path("M -34 -40 L -14 -38", stroke=j2, sw=2.4),                                       # pocket flaps
        path("M 16 -38 L 34 -40", stroke=j2, sw=2.4),
        # navy collar
        path("M -34 -90 C -28 -76 -16 -72 -8 -80 L -6 -94 Z", fill=n1),
        path("M 34 -90 C 28 -76 16 -72 8 -80 L 6 -94 Z", fill=n2),
    ]
    o.append(f'<g clip-path="url(#tc{uid})">' + "".join(inner) + "</g>")
    o.append(path(BODY, fill="none", stroke=ink, sw=3))
    o.append(path("M -30 -88 C -22 -98 22 -98 30 -88 C 22 -92 -22 -92 -30 -88 Z", fill=n2, stroke=ink, sw=2.6))
    o.append(f'<rect x="-1" y="2" width="6" height="9" rx="1.5" fill="{t1}" stroke="{ink}" stroke-width="1.8"/>')  # zip pull
    return "".join(o)


def cord_whistle(P, wx, wy, wr):
    """the cord from the collar down to a hanging whistle (drawn under the beard)."""
    return (path(f"M -12 -88 L {f(wx - 3)} {f(wy - 4)}", stroke=P["cord"], sw=2.6)
            + path(f"M 12 -88 L {f(wx + 1)} {f(wy - 5)}", stroke=P["cord"], sw=2.6)
            + whistle(wx, wy, P, rot=wr, s=0.9))


# ----------------------------------------------------------------- figure
# Dex's keyword schema (dex.DEFAULT), so dex_export's capture works unchanged. `bag` and `badge`
# are ignored (Coach carries neither). Coach adds: whistle (x, y, rot) hanging on its cord, or
# whistle_mouth; beanie_dy (pulled down); led / droop (the headset's state).
DEFAULT = dict(dex.DEFAULT)
DEFAULT.update(bag=False, badge=None, tuft=0,
               whistle=(6, -50, 12), whistle_mouth=False, beanie_dy=0, led=True, droop=False)


def figure(P, uid, **kw):
    p = dict(DEFAULT)
    p.update(kw)
    o = [p["extras_back"]]
    for L in (p["legL"], p["legR"]):
        o.append(leg(L[0], L[1], L[2], P))
    for sh, side in ((p["shoeL"], -1), (p["shoeR"], 1)):
        o.append(shoe(sh[0], sh[1], P, side=side, rot=sh[2], s=1.15))
    up = list(p["props_back"])
    up.append(ctorso(P, uid))
    if p["whistle"] and not p["whistle_mouth"]:
        up.append(cord_whistle(P, *p["whistle"]))
    elif p["whistle_mouth"]:
        up.append(path("M -12 -88 C -8 -70 4 -66 10 -72", stroke=P["cord"], sw=2.6))
    up.extend(p["props_mid"])
    hd = chead(P, uid, eyes=p["eyes"], brows=p["brows"], mouth=p["mouth"], look=p["look"], blush=p["blush"],
               feat=p["feat"], beanie_dy=p["beanie_dy"], led=p["led"], droop=p["droop"],
               whistle_mouth=p["whistle_mouth"])
    up.append(g(hd, f"translate({f(p['head_dx'])} {f(-86 + p['head_dy'])}) rotate({f(p['head_rot'])})"))
    up.extend(p["props_front"])
    for side in ("armL", "armR"):
        a = p[side]
        if a:
            up.append(carm(a[0], a[1], a[2], P))
    up.extend(p["props_top"])
    for side in ("handL", "handR"):
        h = p[side]
        if h:
            up.append(chand(*h[:3], P, kind=h[3] if len(h) > 3 else "mitt", thumb=h[4] if len(h) > 4 else 1,
                            s=h[5] if len(h) > 5 else 1.0))
    o.append(g("".join(up), f"translate({f(p['body_dx'])} {f(p['body_dy'])}) rotate({f(p['body_rot'])})"))
    o.append(p["extras_front"])
    return "".join(o)


# ----------------------------------------------------------------- poses
# Body units, hip at (0, 0); placed at the anchor (236, 379) at scale 0.62 by build.place().
# Names follow dex_sprite.h dex_pose_t. Coach has no money, tracker, paper or show-phone poses.
RELAX_R = dict(armR=((42, -74), (52, -38), (50, -6)), handR=(50, -6, 88, "mitt", -1))
TUCK_L = dict(armL=((-42, -74), (-58, -40), (-46, -12)), handL=(-45, -12, 80, "mitt", 1))


def tucked_calendar(P):
    return calendar(-60, -38, P, rot=-12, s=0.78)


def pose_idle(P, uid, frame=0, sway=0, eyes=None):
    """calendar tucked under his arm, whistle on its cord, steady. frame 1 breathe, 2 blink,
    3 the beat: a glance down at the calendar (Coach's 'sip'). `sway` swings the whistle a few
    degrees (the 3-frame idle loop, where Dex has steam). `eyes` overrides for the blink frames."""
    kw = dict(TUCK_L, **RELAX_R)
    ey, brows, look, head_dy, head_rot, body_dy, feat = "open", "neutral", (0, 0), 0, 0, 0, (0, 0)
    if frame == 1:
        body_dy = -3
    elif frame == 2:
        ey = "blink"
    elif frame == 3:
        ey, look, head_rot, head_dy, feat = "down", (-3, 0), -8, 3, (-3, 2)
    return figure(P, uid, eyes=eyes or ey, brows=brows, look=look, mouth="smile", head_dy=head_dy,
                  head_rot=head_rot, body_dy=body_dy, feat=feat, whistle=(6 + sway / 4, -50, 12 + sway),
                  props_mid=(tucked_calendar(P),), **kw)


def pose_listen(P, uid, bob=0, eyes="up"):
    """leans in, one hand pressed to the headset's ear cup. `bob` is the 2-frame head bob."""
    return figure(
        P, uid, body_rot=8, body_dx=2, head_rot=12, head_dx=4, head_dy=4 + bob,
        eyes=eyes, look=(2, -2), brows="focus", mouth="hmm", feat=(2, -1),
        legL=((-17, 4), (-22, 38), (-28, 70)), legR=((17, 4), (20, 38), (20, 70)),
        shoeL=(-30, 72, 0), shoeR=(21, 72, 0),
        armL=((-42, -74), (-68, -46), (-48, -18)), handL=(-47, -20, 40, "fist", 1),
        armR=((42, -74), (86, -96), (70, -124)), handR=(68, -128, 250, "mitt", 1),
    )


def pose_working(P, uid, frame=0):
    """watching film: head down over the tablet, both hands on it."""
    return figure(
        P, uid, head_dy=12, body_dy=3,
        eyes="down", brows="focus", mouth="hmm", feat=(0, 9),
        legL=((-15, 4), (-14, 38), (-13, 70)), legR=((15, 4), (14, 38), (13, 70)),
        shoeL=(-14, 72, 0), shoeR=(14, 72, 0),
        armL=((-42, -74), (-58, -36), (-36, -22)), handL=(-34, -22, 0, "mitt", -1),
        armR=((42, -74), (58, -36), (36, -22)), handR=(34, -24, 200, "mitt", 1),
        props_front=(tablet(0, -26, P, s=1.1, frame=frame),),
        whistle=None,
    )


def pose_speak(P, uid, mouth="open", eyes="open"):
    """talking, palm lifted toward the answer above him; calendar still tucked."""
    return figure(
        P, uid, body_rot=-3, head_rot=-6, head_dx=-2,
        eyes=eyes, look=(2, -2), brows="raised", mouth=mouth, feat=(2, -1),
        legL=((-17, 4), (-16, 38), (-12, 70)), legR=((17, 4), (22, 38), (26, 70)),
        shoeL=(-12, 72, 0), shoeR=(27, 72, 0),
        props_mid=(tucked_calendar(P),), **TUCK_L,
        armR=((42, -74), (80, -82), (92, -124)), handR=(92, -128, 272, "open", -1, 1.15),
    )


def pose_call(P, uid, eyes="open"):
    """Coach's call (DEX_POSE_ASK_YES): he holds the calendar up high beside his head, the circled
    date toward you, like Dex's Yes sign; the other hand points up at it. Eyes on you. The
    calendar is his prop, not accent-owned: the call's action is the gold 'Hear it' pill."""
    return figure(
        P, uid, body_rot=-3, head_rot=4, head_dx=2,
        eyes=eyes, look=(3, -1), brows="focus", mouth="smile", feat=(2, 0),
        legL=((-17, 4), (-20, 38), (-22, 70)), legR=((17, 4), (20, 38), (23, 70)),
        shoeL=(-23, 72, 0), shoeR=(24, 72, 0),
        props_mid=(calendar(104, -168, P, rot=6, s=1.25),),
        armR=((42, -74), (84, -80), (98, -118)), handR=(98, -122, 262, "fist", -1),
        armL=((-42, -74), (-58, -40), (-46, -8)), handL=(-46, -8, 95, "mitt", 1),
    )


def pose_attention(P, uid, eyes=None):
    """something for you: holds the calendar up to you with both hands, the date circled, quiet."""
    return figure(
        P, uid, head_rot=-4, head_dy=2,
        eyes=eyes or "wide", look=(0, 1), brows="raised", mouth="smile", feat=(0, 1),
        legL=((-17, 4), (-19, 38), (-20, 70)), legR=((17, 4), (19, 38), (20, 70)),
        shoeL=(-20, 72, 0), shoeR=(20, 72, 0),
        armL=((-42, -74), (-66, -44), (-44, -36)), armR=((42, -74), (66, -44), (44, -36)),
        props_top=(calendar(0, -48, P, rot=-3, s=1.3),),
        handL=(-44, -38, 20, "mitt", -1), handR=(44, -38, 160, "mitt", 1),
    )


def pose_done(P, uid, head_dy=6):
    """thumbs-up with the whistle in his teeth, eyes creased. The calendar stays tucked."""
    return figure(
        P, uid, head_rot=6, head_dy=head_dy, head_dx=-2,
        eyes="happy", brows="soft", mouth="smile", feat=(-1, 2), whistle_mouth=True,
        legL=((-17, 4), (-19, 38), (-21, 70)), legR=((17, 4), (22, 38), (24, 70)),
        shoeL=(-21, 72, 0), shoeR=(25, 72, 0),
        props_mid=(tucked_calendar(P),), **TUCK_L,
        armR=((42, -74), (84, -70), (82, -112)), handR=(82, -112, 270, "thumb", 1, 1.1),
    )


def stool(P):
    c0, c1, c2 = P["stool"]
    return (path("M -64 14 L 64 14 L 62 72 L -62 72 Z", fill=c1, stroke=P["ink"], sw=3)
            + path("M 40 16 L 62 16 L 60.5 70 L 40 70 Z", fill=c2)
            + path("M -68 2 L 68 2 C 71 2 72 4 72 7 L 72 16 L -72 16 L -72 7 C -72 4 -71 2 -68 2 Z",
                   fill=c0, stroke=P["ink"], sw=3))


def knees(P):
    p0, p1, p2 = P["pants"]
    return "".join(ell(sx * 27, 24, 17, 13, p1, stroke=P["ink"], sw=3) + ell(sx * 27 - 3, 21, 9, 6, p0)
                   for sx in (-1, 1))


def moon(P, x, y):
    return (f'<g transform="translate({f(x)} {f(y)})">'
            + path("M 8 -14 A 16 16 0 1 0 14 10 A 12.5 12.5 0 1 1 8 -14 Z", fill=P["moon"]) + "</g>")


def pose_sleep(P, uid, lean=0):
    """asleep on the stool, beanie pulled down over his eyes, arms folded on his lap, headset LED
    off. Pass PAL_NIGHT. `lean` sways the head a unit for the slow night loop."""
    return figure(
        P, uid, head_rot=8 + lean, head_dy=10, head_dx=2, body_dy=4,
        eyes="sleep", brows="soft", mouth="sleep", blush=False, feat=(0, 4), beanie_dy=20, led=False,
        extras_back=stool(P) + moon(P, 120, -230), extras_front=knees(P),
        legL=((-17, 8), (-28, 26), (-28, 58)), legR=((17, 8), (28, 26), (28, 58)),
        shoeL=(-29, 64, 0), shoeR=(29, 64, 0),
        armL=((-42, -74), (-50, -34), (14, -18)), handL=(16, -18, 0, "mitt", -1),
        armR=((42, -74), (50, -34), (-14, -12)), handR=(-16, -12, 180, "mitt", 1),
        whistle=(6, -48, 4),
    )


def pose_offline(P, uid, eyes=None):
    """taps the dead headset: LED off, the boom mic drooped. Honest and plain, no joke."""
    return figure(
        P, uid, head_rot=-8, head_dx=-2,
        eyes=eyes or "open", look=(-4, -2), brows="flat", mouth="flat", feat=(-4, 0), led=False, droop=True,
        legL=((-17, 4), (-17, 38), (-17, 70)), legR=((17, 4), (17, 38), (17, 70)),
        shoeL=(-18, 72, 0), shoeR=(18, 72, 0),
        armL=((-42, -74), (-86, -84), (-78, -122)), handL=(-76, -126, 300, "point", 1),
        **RELAX_R,
    )


def pose_error(P, uid, eyes=None):
    """needs more: both palms up, one brow up."""
    return figure(
        P, uid, head_rot=9, head_dx=2, body_dy=-2,
        eyes=eyes or "up", look=(2, -2), brows="ask", mouth="hmm", feat=(2, -1),
        legL=((-17, 4), (-22, 38), (-26, 70)), legR=((17, 4), (22, 38), (26, 70)),
        shoeL=(-27, 72, 0), shoeR=(27, 72, 0),
        armL=((-42, -74), (-68, -50), (-76, -70)), handL=(-78, -74, 240, "open", 1),
        armR=((42, -74), (68, -50), (76, -70)), handR=(78, -74, 300, "open", -1),
    )


# dex_pose_t name -> (pose fn, palette is night). The poses Coach does not have are absent on
# purpose; the player shows the gray placeholder for them, never Dex's frames (dex_sprite.h).
POSES = {
    "idle": pose_idle,
    "listening": pose_listen,
    "working": pose_working,
    "attention": pose_attention,
    "done": pose_done,
    "speaking": pose_speak,
    "asleep": pose_sleep,
    "offline": pose_offline,
    "error": pose_error,
    "ask_yes": pose_call,
}
NOT_COACH = ("offer_bag", "lift_bag", "lookout", "paper", "show_phone")
