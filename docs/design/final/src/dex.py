"""Dex Charm r2 SM-SHEET generator: hand-built flat-tone SVG character."""
import math

INK = "#1B1412"

PAL = {
    "ink": INK,
    "skin": ("#F6CFAA", "#E7AE84", "#C98A63"),
    "hair": ("#7A4E36", "#553423", "#3A2217"),
    "beard": ("#86573C", "#654030", "#4A2D20"),
    "teal": ("#4CC3CC", "#1F97A6", "#14707D"),
    "shirt": ("#FFFFFF", "#E9EEF0", "#C3CDD2"),
    "pants": ("#565D69", "#3D434D", "#2A2E36"),
    "shoe": ("#F4F6F7", "#C9D0D5", "#8E979E"),
    "bag": ("#B0703F", "#87512C", "#633A1F"),
    "gold": "#F0B541",
    "mug": ("#FFFFFF", "#E6E6E1", "#BDBDB6"),
    "coffee": "#5B3524",
    "logo": "#2A2A2E",
    "phone": ("#4A515C", "#2E333B", "#1E2228"),
    "screen": ("#F3F7F8", "#DCE4E7"),
    "check": "#2FC05C",
    "line": "#A7B1B8",
    "lanyard": "#2A3038",
    "blush": "#EE9A82",
    "mouth": "#3A1712",
    "tongue": "#E0716A",
    "eyehi": "#FFFFFF",
    "kraft": ("#E6C48C", "#CFA466", "#A67C43"),
    "accent": "#7FE0E6",
    "steam": "#CFD6DA",
    "stool": ("#77808E", "#5A6270", "#424955"),
}


def dim(hexc, f=0.6, cap=0xB4):
    h = hexc.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    # night: darken, pull toward blue, cap brightness so nothing reads as white
    r, g, b = r * f * 0.92, g * f * 0.97, b * f * 1.08
    m = max(r, g, b)
    if m > cap:
        k = cap / m
        r, g, b = r * k, g * k, b * k
    return "#%02X%02X%02X" % (int(min(255, r)), int(min(255, g)), int(min(255, b)))


def dim_pal(p):
    out = {}
    for k, v in p.items():
        if isinstance(v, tuple):
            out[k] = tuple(dim(c) for c in v)
        elif k == "ink":
            out[k] = "#0E0B0B"
        elif k == "steam":
            out[k] = "#9DADBB"
        else:
            out[k] = dim(v)
    return out


PAL_NIGHT = dim_pal(PAL)


def f(v):
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def pts(*p):
    return " ".join(f"{f(x)},{f(y)}" for x, y in p)


def ell(cx, cy, rx, ry, fill, rot=0, stroke=None, sw=3, extra=""):
    t = f' transform="rotate({f(rot)} {f(cx)} {f(cy)})"' if rot else ""
    s = f' stroke="{stroke}" stroke-width="{f(sw)}"' if stroke else ""
    return f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(rx)}" ry="{f(ry)}" fill="{fill}"{s}{t}{extra}/>'


def path(d, fill="none", stroke=None, sw=3, cap="round", join="round", extra=""):
    s = f' stroke="{stroke}" stroke-width="{f(sw)}" stroke-linecap="{cap}" stroke-linejoin="{join}"' if stroke else ""
    return f'<path d="{d}" fill="{fill}"{s}{extra}/>'


def line(p, color, w, cap="round"):
    return (f'<polyline points="{pts(*p)}" fill="none" stroke="{color}" stroke-width="{f(w)}" '
            f'stroke-linecap="{cap}" stroke-linejoin="round"/>')


def g(content, tf=""):
    t = f' transform="{tf}"' if tf else ""
    return f"<g{t}>{content}</g>"


def rot_pt(x, y, deg):
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def normal(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1
    nx, ny = -dy / L, dx / L
    if nx + ny < 0:
        nx, ny = -nx, -ny
    return nx, ny


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


# ----------------------------------------------------------------- props
def planet(cx, cy, s, P, color=None):
    c = color or P["logo"]
    return (ell(cx, cy, 3.6 * s, 3.6 * s, c)
            + ell(cx, cy, 7.2 * s, 2.0 * s, "none", rot=-22, stroke=c, sw=1.5 * s))


def mug(x, y, P, rot=0, steam=False, tilt_top=True, s=1.0, lean=0):
    """mug centred at x,y (body centre). handle on +x."""
    m0, m1, m2 = P["mug"]
    o = []
    # handle
    o.append(path("M 13 -8 C 25 -8 25 10 13 10", stroke=P["ink"], sw=10))
    o.append(path("M 13 -8 C 25 -8 25 10 13 10", stroke=m2, sw=4.5))
    # body
    body = "M -15 -17 L 15 -17 L 14 13 C 14 18 10 20 6 20 L -6 20 C -10 20 -14 18 -14 13 Z"
    o.append(path(body, fill=m1, stroke=P["ink"], sw=3))
    o.append(path("M 7 -15.5 L 13.4 -15.5 L 12.6 13 C 12.6 16 10.5 18.4 6 18.4 L 5 18.4 C 8 16 8 13 8 10 Z", fill=m2))
    o.append(path("M -12.5 -12 L -9.5 -12 L -9.5 10 C -9.5 12 -11 13 -12 12 Z", fill=m0))
    # rim + coffee
    if tilt_top:
        o.append(ell(0, -17, 15, 4.2, m0, stroke=P["ink"], sw=3))
        o.append(ell(0, -16.4, 11.5, 2.6, P["coffee"]))
    o.append(planet(-1.5, 2, 1.05, P))
    if steam:
        st = (path("M -5 -26 C -11 -33 1 -38 -5 -46 C -9 -51 -3 -56 -5 -60", stroke=P["steam"], sw=3.2)
              + path("M 6 -28 C 1 -34 11 -39 6 -46", stroke=P["steam"], sw=2.6))
        o.append(g(st, f"rotate({f(lean - rot)} 0 -20)"))
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


def phone(x, y, P, rot=0, s=1.0, screen="list", checks=3, tick_anim=False, face=True):
    p0, p1, p2 = P["phone"]
    sc0, sc1 = P["screen"]
    o = []
    o.append(path("M -17 -30 L 17 -30 C 21 -30 23 -28 23 -24 L 23 24 C 23 28 21 30 17 30 L -17 30 "
                  "C -21 30 -23 28 -23 24 L -23 -24 C -23 -28 -21 -30 -17 -30 Z", fill=p1, stroke=P["ink"], sw=3))
    o.append(path("M 19 -27 L 20 25 C 20 27 19 27.5 17 27.5 L 12 27.5 Z", fill=p2))
    o.append(path("M -19 -26 L -19 -12", stroke=p0, sw=2.2))
    if face:
        o.append(path("M -17.5 -24 L 17.5 -24 L 17.5 24 L -17.5 24 Z", fill=sc0))
        o.append(path("M -17.5 17 L 17.5 17 L 17.5 24 L -17.5 24 Z", fill=sc1))
        if screen == "list":
            for i in range(3):
                yy = -14 + i * 12
                done = i < checks
                if done:
                    o.append(path(f"M -13 {f(yy)} L -9.5 {f(yy + 3.5)} L -3.5 {f(yy - 3.5)}", stroke=P["check"], sw=3.2))
                else:
                    o.append(f'<rect x="-13.5" y="{f(yy - 4)}" width="8" height="8" rx="2" fill="none" stroke="{P["line"]}" stroke-width="2"/>')
                w = 18 if i != 1 else 13
                o.append(f'<rect x="0" y="{f(yy - 2.2)}" width="{w}" height="4.4" rx="2.2" fill="{P["line"]}"/>')
        elif screen == "nosignal":
            # four signal bars: first one filled, the rest empty, one plain slash
            bx = -12
            for i, h in enumerate([7, 12, 17, 22]):
                xx = bx + i * 6.6
                if i == 0:
                    o.append(f'<rect x="{f(xx)}" y="{f(10 - h)}" width="4.6" height="{f(h)}" rx="1.6" fill="#6F7A83"/>')
                else:
                    o.append(f'<rect x="{f(xx + 0.8)}" y="{f(10 - h + 0.8)}" width="3" height="{f(h - 1.6)}" rx="1.2" fill="none" stroke="#9AA5AD" stroke-width="1.6"/>')
            o.append(path("M -14 12 L 15 -15", stroke=sc0, sw=5.5))
            o.append(path("M -14 12 L 15 -15", stroke="#4A545C", sw=2.6))
    else:
        # back of the phone: camera + planet
        o.append(ell(-12, -22, 3, 3, p2))
        o.append(planet(0, 2, 1.1, P, color=p0))
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


def takeout(x, y, P, rot=0, s=1.0):
    k0, k1, k2 = P["kraft"]
    o = []
    # handles
    o.append(path("M -12 -30 C -12 -46 12 -46 12 -30", stroke=P["ink"], sw=8))
    o.append(path("M -12 -30 C -12 -46 12 -46 12 -30", stroke=k2, sw=3.5))
    body = "M -27 -30 L 27 -30 L 29 30 C 29 34 27 36 23 36 L -23 36 C -27 36 -29 34 -29 30 Z"
    o.append(path(body, fill=k1, stroke=P["ink"], sw=3))
    o.append(path("M 17 -28.5 L 25.5 -28.5 L 27.4 30 C 27.4 33 26 34.5 23 34.5 L 18.5 34.5 Z", fill=k2))
    o.append(path("M -25.5 -28.5 L -20 -28.5 L -21 34.5 L -24 34.5 C -26.5 34.5 -27.5 33 -27.5 30 Z", fill=k0))
    # folded top band
    o.append(path("M -27 -30 L 27 -30 L 27.4 -18 L -27.4 -18 Z", fill=k0, stroke=P["ink"], sw=3))
    o.append(path("M -27.4 -18 L -21 -13 L -14 -18 L -7 -13 L 0 -18 L 7 -13 L 14 -18 L 21 -13 L 27.4 -18",
                  fill=k0, stroke=P["ink"], sw=2.5))
    # round sticker seal in brand teal with planet
    t0, t1, t2 = P["teal"]
    o.append(ell(0, 8, 11, 11, t1, stroke=P["ink"], sw=2.5))
    o.append(planet(0, 8, 1.0, P, color=P["mug"][0]))
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


def badge(x, y, P, rot=0):
    m0, m1, m2 = P["shirt"]
    o = [f'<rect x="-9.5" y="-11" width="19" height="23" rx="3.5" fill="{m0}" stroke="{P["ink"]}" stroke-width="2.5"/>',
         f'<rect x="-3.5" y="-8" width="7" height="2.4" rx="1.2" fill="{m2}"/>',
         planet(0, 3, 0.8, P)]
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)})")


# ----------------------------------------------------------------- hands
def hand(x, y, ang, P, kind="mitt", thumb=1, s=1.0):
    """ang: direction wrist->fingers in degrees (0 = +x, 90 = down)."""
    s0, s1, s2 = P["skin"]
    ink = P["ink"]
    o = []
    r = 90 - ang  # rotate local (fingers +y) to world

    def W(px, py):
        a, b = rot_pt(px * s, py * s, -r)
        return x + a, y + b

    if kind == "cup":
        # hand cupped behind ear, palm facing viewer, fingers curled forward
        cx, cy = W(0, 7)
        o.append(ell(cx, cy, 11 * s, 12.5 * s, s2, rot=-r, stroke=ink, sw=3))
        o.append(ell(cx - 1.5, cy - 1.5, 9 * s, 10.5 * s, s1, rot=-r))
        # curled finger ridges
        for k in (-1, 0, 1):
            a0 = W(k * 5.5, 13)
            a1 = W(k * 5.5, 17.5)
            o.append(line([a0, a1], s2, 2.4))
        tx, ty = W(-thumb * 10, 2)
        o.append(ell(tx, ty, 4.2 * s, 7 * s, s1, rot=-r + thumb * 30, stroke=ink, sw=2.6))
        return "".join(o)
    if kind == "point":
        fx, fy = W(0, 22)
        bx, by = W(0, 8)
        o.append(line([(bx, by), (fx, fy)], ink, 10.5 * s))
        o.append(line([(bx, by), (fx, fy)], s1, 5 * s))
    if kind == "open":
        # open palm facing viewer, four fingers fanned
        tips = [(-9.5, 20, -9), (-3.4, 23.5, -3), (3.2, 23.5, 3), (9, 20, 9)]
        for tx_, ty_, _ in tips:
            o.append(line([W(tx_ * 0.55, 8), W(tx_, ty_)], ink, 9.4 * s))
        for tx_, ty_, _ in tips:
            o.append(line([W(tx_ * 0.55, 8), W(tx_, ty_)], s1, 4 * s))
    cx, cy = W(0, 6.5)
    rx, ry = 10.5 * s, 11.5 * s
    if kind == "fist":
        ry = 10 * s
    o.append(ell(cx, cy, rx, ry, s2, rot=-r, stroke=ink, sw=3))
    o.append(ell(cx - 1.7, cy - 1.7, rx - 2.4, ry - 2.4, s1, rot=-r))
    o.append(ell(cx - 4, cy - 4.5, 2.6 * s, 2.2 * s, s0, rot=-r))
    if kind == "open":
        # re-cover finger bases so the palm reads as one volume
        pass
    tx, ty = W(thumb * 9.5, 1.5)
    o.append(ell(tx, ty, 4.3 * s, 6.8 * s, s1, rot=-r - thumb * 32, stroke=ink, sw=2.6))
    return "".join(o)


# ----------------------------------------------------------------- limbs
def arm(S, E, H, P, cuff=True):
    t0, t1, t2 = P["teal"]
    ink = P["ink"]
    Hc = lerp(E, H, 0.86)
    o = [line([S, E, Hc], ink, 29), line([S, E, Hc], t1, 23)]
    # shadow + highlight bands, per segment
    for a, b in ((S, E), (E, Hc)):
        nx, ny = normal(a, b)
        o.append(line([(a[0] + nx * 5.5, a[1] + ny * 5.5), (b[0] + nx * 5.5, b[1] + ny * 5.5)], t2, 7))
    for a, b in ((S, E), (E, Hc)):
        nx, ny = normal(a, b)
        o.append(line([(a[0] - nx * 5.8, a[1] - ny * 5.8), (lerp(a, b, 0.75)[0] - nx * 5.8, lerp(a, b, 0.75)[1] - ny * 5.8)], t0, 3.6))
    if cuff:
        c0 = lerp(E, H, 0.7)
        o.append(line([c0, Hc], ink, 29, cap="butt"))
        o.append(line([c0, Hc], t2, 23, cap="butt"))
        nx, ny = normal(E, H)
        o.append(line([(c0[0] - nx * 5.8, c0[1] - ny * 5.8), (Hc[0] - nx * 5.8, Hc[1] - ny * 5.8)], t1, 3.6, cap="butt"))
    return "".join(o)


def leg(hip, knee, ankle, P):
    p0, p1, p2 = P["pants"]
    ink = P["ink"]
    o = [line([hip, knee, ankle], ink, 34), line([hip, knee, ankle], p1, 28)]
    for a, b in ((hip, knee), (knee, ankle)):
        nx, ny = normal(a, b)
        o.append(line([(a[0] + nx * 7, a[1] + ny * 7), (b[0] + nx * 7, b[1] + ny * 7)], p2, 8))
        o.append(line([(a[0] - nx * 7.5, a[1] - ny * 7.5), (lerp(a, b, 0.7)[0] - nx * 7.5, lerp(a, b, 0.7)[1] - ny * 7.5)], p0, 3.5))
    return "".join(o)


def shoe(x, y, P, side=1, rot=0, s=1.0):
    """x,y = ankle; side: -1 left toe points left, +1 right."""
    w0, w1, w2 = P["shoe"]
    ink = P["ink"]
    o = []
    d = ("M -16 -2 C -16 -10 -8 -12 0 -12 C 10 -12 14 -8 18 -4 C 23 -3 25 1 25 5 L 25 9 "
         "C 25 12 23 13 20 13 L -14 13 C -17 13 -18 11 -18 8 Z")
    o.append(path(d, fill=w1, stroke=ink, sw=3))
    o.append(path("M -14 -3 C -14 -8 -7 -9.5 0 -9.5 C 8 -9.5 12 -6 15 -3 L 3 -1 C -3 -1 -9 -1 -14 -3 Z", fill=w0))
    o.append(path("M -16.5 7 L 23.5 7 L 23.5 9 C 23.5 11 22 11.6 20 11.6 L -14 11.6 C -16 11.6 -16.5 10.5 -16.5 9 Z", fill=w2))
    o.append(path("M 2 -8 L 4 -4 M 7 -8 L 9 -4", stroke=w2, sw=2))
    return g("".join(o), f"translate({f(x)} {f(y)}) scale({f(side * s)} {f(s)}) rotate({f(rot)})")


# ----------------------------------------------------------------- head
def head(P, uid, eyes="open", brows="neutral", mouth="smile", look=(0, 0), blush=True, tuft=0, feat=(0, 0)):
    s0, s1, s2 = P["skin"]
    h0, h1, h2 = P["hair"]
    b0, b1, b2 = P["beard"]
    ink = P["ink"]
    o = []
    face = ("M -47 -70 C -47 -100 -28 -110 0 -110 C 28 -110 47 -100 47 -70 L 47 -44 "
            "C 47 -17 27 -3 0 -3 C -27 -3 -47 -17 -47 -44 Z")
    # ears
    for sx in (-1, 1):
        o.append(ell(sx * 47, -52, 9.5, 12.5, s1 if sx < 0 else s2, stroke=ink, sw=3))
        o.append(ell(sx * 48.5, -52, 4, 6.5, s2 if sx < 0 else "#B7785A"))
    # hair back mass (behind face, visible at sides/top)
    back = ("M -52 -56 C -62 -70 -64 -92 -58 -106 C -66 -122 -54 -142 -36 -140 C -30 -156 -8 -160 2 -150 "
            "C 12 -162 36 -158 40 -142 C 56 -148 68 -130 60 -116 C 68 -104 64 -80 54 -56 Z")
    o.append(path(back, fill=h2, stroke=ink, sw=3))
    o.append(f'<clipPath id="fc{uid}"><path d="{face}"/></clipPath>')
    o.append(path(face, fill=s1, stroke=ink, sw=3))
    # face planes: shadow right side + highlight on left cheek/forehead
    o.append(f'<g clip-path="url(#fc{uid})">'
             + path("M 30 -115 C 44 -100 48 -70 44 -40 C 40 -20 28 -8 10 0 L 60 0 L 60 -115 Z", fill=s2)
             + ell(-28, -86, 9, 6, s0, rot=-20) + "</g>")
    o.append(path(face, fill="none", stroke=ink, sw=3))
    # beard (short, trimmed; mustache joins at the mouth)
    beard = ("M -47 -62 L -47 -44 C -47 -17 -27 -3 0 -3 C 27 -3 47 -17 47 -44 L 47 -62 "
             "C 46 -48 40 -34 30 -31 C 23 -29 17 -35 12 -37 C 7 -39 3 -39 0 -37 "
             "C -3 -39 -7 -39 -12 -37 C -17 -35 -23 -29 -30 -31 C -40 -34 -46 -48 -47 -62 Z")
    o.append(path(beard, fill=b1, stroke=ink, sw=2.6))
    o.append(f'<clipPath id="bc{uid}"><path d="{beard}"/></clipPath>')
    o.append(f'<g clip-path="url(#bc{uid})">'
             + path("M 26 -40 C 40 -40 46 -52 50 -62 L 50 0 L 8 0 C 26 -8 36 -18 40 -30 Z", fill=b2) + "</g>")
    o.append(path("M -40 -40 C -34 -30 -30 -22 -24 -16 C -32 -20 -40 -28 -43 -38 Z", fill=b0))
    # hair front cap with messy fringe
    front = ("M -52 -56 L -52 -76 C -60 -86 -58 -100 -50 -108 C -54 -122 -42 -136 -28 -132 "
             "C -22 -146 -2 -150 6 -140 C 14 -152 34 -150 38 -136 C 52 -140 62 -124 56 -110 "
             "C 64 -100 60 -84 54 -78 L 53 -56 L 46 -58 L 46 -76 "
             "C 40 -82 32 -84 26 -80 C 22 -90 10 -94 2 -88 C -4 -96 -18 -96 -24 -86 "
             "C -30 -92 -40 -90 -44 -80 C -46 -76 -46 -66 -46 -58 Z")
    o.append(path(front, fill=h1, stroke=ink, sw=3))
    # tufts (messy): flicks on the crown
    tufts = [
        "M -30 -132 C -40 -144 -46 -144 -52 -142 C -44 -138 -40 -132 -38 -126 Z",
        "M 4 -140 C 2 -154 8 -162 16 -166 C 14 -158 16 -150 20 -144 Z",
        "M 38 -136 C 46 -146 54 -146 60 -142 C 52 -140 48 -134 48 -128 Z",
    ]
    if tuft:
        tufts.append("M -12 -146 C -16 -156 -12 -164 -6 -168 C -6 -160 -2 -154 2 -150 Z")
    for t in tufts:
        o.append(path(t, fill=h1, stroke=ink, sw=2.6))
    # hair shadow: underside of fringe lobes + right side
    o.append(path("M 26 -80 C 30 -88 42 -90 48 -84 L 54 -80 L 53 -56 L 46 -58 L 46 -76 C 40 -82 32 -84 26 -80 Z", fill=h2))
    o.append(path("M 52 -110 C 60 -104 60 -90 54 -80 C 54 -90 52 -100 46 -106 Z", fill=h2))
    o.append(path("M 2 -88 C 8 -92 18 -92 24 -84 C 20 -90 10 -92 2 -88 Z", fill=h2, stroke=h2, sw=2))
    # hair highlights: lit lobes on top-left
    o.append(path("M -42 -120 C -40 -128 -30 -130 -24 -126 C -30 -124 -36 -120 -38 -114 Z", fill=h0))
    o.append(path("M -16 -134 C -10 -142 2 -142 8 -136 C 0 -136 -8 -134 -12 -128 Z", fill=h0))
    o.append(path("M 18 -138 C 24 -144 32 -142 34 -136 C 28 -137 24 -134 22 -130 Z", fill=h0))
    o.append(path("M -50 -100 C -52 -94 -52 -86 -48 -80 C -46 -88 -46 -94 -44 -100 Z", fill=h0))
    base = len(o)
    o.append(path("M -5 -46 C -4 -40 4 -40 5 -46 C 3 -43 -3 -43 -5 -46 Z", fill=s2))
    o.append(ell(-1.5, -47.5, 3.2, 2.6, s0))
    # blush
    if blush:
        o.append(ell(-31, -50, 6.5, 3.6, P["blush"]))
        o.append(ell(31, -50, 6.5, 3.6, P["blush"]))
    # eyes
    lx, ly = look
    for sx in (-1, 1):
        ex, ey = sx * 18, -60
        if eyes in ("open", "up", "wide"):
            ry = 8.6 if eyes != "wide" else 9.6
            rx = 5.8 if eyes != "wide" else 6.3
            o.append(ell(ex + lx, ey + ly, rx, ry, ink))
            o.append(ell(ex + lx - 1.8, ey + ly - 3.4, 2.1, 2.4, P["eyehi"]))
        elif eyes == "down":
            # looking down: pupil low, heavy upper lid
            o.append(ell(ex, ey + 3, 5.6, 6.4, ink))
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
    # brows
    bmap = {
        "neutral": ((-1, -76, -4), (1, -76, 4)),
        "raised": ((-1, -81, -10), (1, -81, 10)),
        "flat": ((-1, -75, 0), (1, -75, 0)),
        "soft": ((-1, -77, 8), (1, -77, -8)),
        "ask": ((-1, -76, -2), (1, -83, 14)),
        "focus": ((-1, -74, 8), (1, -74, -8)),
    }
    for sx, by, rt in bmap[brows]:
        o.append(f'<rect x="{f(sx * 19 - 9)}" y="{f(by - 2.8)}" width="18" height="5.6" rx="2.8" fill="{h2}" '
                 f'transform="rotate({f(rt)} {f(sx * 19)} {f(by)})"/>')
    # mouth
    my = -28
    if mouth == "smile":
        o.append(path(f"M -8 {my - 1} C -4 {my + 5} 4 {my + 5} 8 {my - 1}", stroke=P["mouth"], sw=3.4))
    elif mouth == "grin":
        o.append(path(f"M -11 {my - 3} C -6 {my + 6} 6 {my + 6} 11 {my - 3} Z", fill=P["mouth"], stroke=P["mouth"], sw=2.4))
        o.append(path(f"M -8 {my - 2.4} L 8 {my - 2.4} L 7 {my} L -7 {my} Z", fill=P["mug"][0]))
    elif mouth == "open":
        o.append(path(f"M -9 {my - 4} C -9 {my + 9} 9 {my + 9} 9 {my - 4} C 4 {my - 6} -4 {my - 6} -9 {my - 4} Z",
                      fill=P["mouth"], stroke=P["mouth"], sw=2))
        o.append(path(f"M -5 {my + 4} C -2 {my + 1} 3 {my + 1} 6 {my + 4} C 3 {my + 7} -3 {my + 7} -5 {my + 4} Z", fill=P["tongue"]))
        o.append(path(f"M -7 {my - 4.2} L 7 {my - 4.2} L 6.2 {my - 1.8} L -6.2 {my - 1.8} Z", fill=P["mug"][0]))
    elif mouth == "o":
        o.append(ell(0, my + 1, 4.2, 5, P["mouth"]))
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
def torso(P, uid, lean=0):
    t0, t1, t2 = P["teal"]
    w0, w1, w2 = P["shirt"]
    s0, s1, s2 = P["skin"]
    ink = P["ink"]
    o = []
    body = ("M -28 -88 C -42 -88 -50 -82 -50 -68 L -48 2 C -48 10 -44 14 -36 14 L 36 14 "
            "C 44 14 48 10 48 2 L 50 -68 C 50 -82 42 -88 28 -88 Z")
    # neck
    o.append(f'<rect x="-10" y="-100" width="20" height="18" fill="{s2}" stroke="{ink}" stroke-width="3"/>')
    o.append(f'<clipPath id="tc{uid}"><path d="{body}"/></clipPath>')
    o.append(path(body, fill=t1, stroke=ink, sw=3))
    inner = []
    # shirt panel
    inner.append(path("M -15 -90 L 15 -90 L 18 16 L -18 16 Z", fill=w0))
    inner.append(path("M 8 -90 L 15 -90 L 18 16 L 11 16 Z", fill=w1))
    # collar V
    inner.append(path("M -12 -89 L 0 -74 L 12 -89 Z", fill=s2))
    inner.append(path("M -14 -90 L 0 -74 L -4 -66 L -18 -86 Z", fill=w0, stroke=ink, sw=2))
    inner.append(path("M 14 -90 L 0 -74 L 4 -66 L 18 -86 Z", fill=w1, stroke=ink, sw=2))
    # jacket panels over shirt edges (open jacket)
    inner.append(path("M -60 -95 L -16 -95 C -18 -70 -20 -30 -20 16 L -60 16 Z", fill=t1))
    inner.append(path("M 60 -95 L 16 -95 C 18 -70 20 -30 20 16 L 60 16 Z", fill=t1))
    # shading: right side plane, lit left edge, hem band
    inner.append(path("M 34 -95 C 40 -60 40 -20 36 16 L 60 16 L 60 -95 Z", fill=t2))
    inner.append(path("M -46 -76 C -44 -60 -44 -30 -42 -4 L -38 -4 C -40 -30 -40 -60 -40 -80 Z", fill=t0))
    inner.append(path("M -60 2 L 60 2 L 60 20 L -60 20 Z", fill=t2))
    # front edges (zip placket lines)
    inner.append(path("M -16 -92 C -18 -70 -20 -30 -20 14", stroke=ink, sw=2.4))
    inner.append(path("M 16 -92 C 18 -70 20 -30 20 14", stroke=ink, sw=2.4))
    inner.append(path("M -60 2 L 60 2", stroke=ink, sw=2.4))
    # hood collar
    inner.append(path("M -30 -90 C -26 -80 -18 -78 -14 -84 L -16 -94 Z", fill=t0))
    # chest patch
    inner.append(f'<rect x="26" y="-62" width="9" height="9" rx="2" fill="{t0}"/>')
    inner.append(f'<rect x="28.5" y="-59.5" width="4" height="4" rx="1" fill="{t1}"/>')
    o.append(f'<g clip-path="url(#tc{uid})">' + "".join(inner) + "</g>")
    o.append(path(body, fill="none", stroke=ink, sw=3))
    # hood rolled behind neck
    o.append(path("M -30 -88 C -22 -98 22 -98 30 -88 C 22 -92 -22 -92 -30 -88 Z", fill=t2, stroke=ink, sw=2.6))
    return "".join(o)


def lanyard(P, bx=0, by=-44, rot=0):
    o = [path(f"M -9 -88 L {f(bx - 2)} {f(by - 10)}", stroke=P["lanyard"], sw=2.6),
         path(f"M 9 -88 L {f(bx + 2)} {f(by - 10)}", stroke=P["lanyard"], sw=2.6),
         badge(bx, by, P, rot)]
    return "".join(o)


def bag(P, x=-50, y=6, strap=True, flip=False):
    c0, c1, c2 = P["bag"]
    ink = P["ink"]
    o = []
    body = "M -22 -16 L 22 -16 C 25 -16 26 -14 26 -11 L 25 18 C 25 22 22 24 18 24 L -18 24 C -22 24 -25 22 -25 18 L -26 -11 C -26 -14 -25 -16 -22 -16 Z"
    o.append(path(body, fill=c1, stroke=ink, sw=3))
    o.append(path("M 12 -14 L 23.5 -14 L 23.5 18 C 23.5 21 21 22.5 18 22.5 L 12 22.5 Z", fill=c2))
    o.append(path("M -24 -15 L 24 -15 L 24 4 C 24 7 22 8 19 8 L -19 8 C -22 8 -24 7 -24 4 Z", fill=c1, stroke=ink, sw=2.6))
    o.append(path("M -20 -12 L -6 -12 L -8 5 L -20 5 Z", fill=c0))
    o.append(path("M 12 -13 L 22 -13 L 22 4 C 22 6 21 6.5 19 6.5 L 12 6.5 Z", fill=c2))
    o.append(f'<rect x="-4" y="2" width="8" height="9" rx="1.6" fill="{P["gold"]}" stroke="{ink}" stroke-width="2"/>')
    tf = f"translate({f(x)} {f(y)})" + (" scale(-1 1)" if flip else "")
    return g("".join(o), tf)


def strap(P, a=(-30, -86), b=(-44, -8)):
    c0, c1, c2 = P["bag"]
    return line([a, b], P["ink"], 10) + line([a, b], c1, 5)


# ----------------------------------------------------------------- figure
DEFAULT = dict(
    body_rot=0, body_dx=0, body_dy=0,
    head_rot=0, head_dx=0, head_dy=0,
    eyes="open", brows="neutral", mouth="smile", look=(0, 0), blush=True, tuft=0, feat=(0, 0),
    legL=((-17, 4), (-18, 38), (-19, 70)), legR=((17, 4), (18, 38), (19, 70)),
    shoeL=(-19, 72, 0), shoeR=(19, 72, 0),
    armL=None, armR=None, handL=None, handR=None,
    props_back=(), props_mid=(), props_front=(), props_top=(),
    bag=True, badge=(0, -44, 0), seated=False, extras_back="", extras_front="",
)


def figure(P, uid, **kw):
    p = dict(DEFAULT)
    p.update(kw)
    o = []
    o.append(p["extras_back"])
    # legs + shoes (in hip frame, not rotated with the torso)
    for L, sh, side in ((p["legL"], p["shoeL"], -1), (p["legR"], p["shoeR"], 1)):
        o.append(leg(L[0], L[1], L[2], P))
    for sh, side in ((p["shoeL"], -1), (p["shoeR"], 1)):
        o.append(shoe(sh[0], sh[1], P, side=side, rot=sh[2], s=1.15))
    up = []
    for pr in p["props_back"]:
        up.append(pr)
    if p["bag"]:
        up.append(bag(P))
    up.append(torso(P, uid))
    if p["bag"]:
        up.append(strap(P))
    if p["badge"]:
        bx, by, br = p["badge"]
        up.append(lanyard(P, bx, by, br))
    for pr in p["props_mid"]:
        up.append(pr)
    hd = head(P, uid, eyes=p["eyes"], brows=p["brows"], mouth=p["mouth"], look=p["look"], blush=p["blush"], tuft=p["tuft"], feat=p["feat"])
    up.append(g(hd, f"translate({f(p['head_dx'])} {f(-86 + p['head_dy'])}) rotate({f(p['head_rot'])})"))
    for pr in p["props_front"]:
        up.append(pr)
    for side in ("armL", "armR"):
        a = p[side]
        if a:
            up.append(arm(a[0], a[1], a[2], P))
    for pr in p["props_top"]:
        up.append(pr)
    for side in ("handL", "handR"):
        h = p[side]
        if h:
            up.append(hand(*h[:3], P, kind=h[3] if len(h) > 3 else "mitt", thumb=h[4] if len(h) > 4 else 1, s=h[5] if len(h) > 5 else 1.0))
    o.append(g("".join(up), f"translate({f(p['body_dx'])} {f(p['body_dy'])}) rotate({f(p['body_rot'])})"))
    o.append(p["extras_front"])
    return "".join(o)
