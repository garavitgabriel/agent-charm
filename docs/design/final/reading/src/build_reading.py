"""Dex Charm FINAL — reading mode (R1–R6), extending the locked system.

Imports the final system unchanged from ../../src (build.py, dex.py, sheet.py). Nothing there is
modified. New here: reading glasses (a head overlay), the book in three views, a note card, seven
reading poses, the reading type scale and the scroll view.

Run:  python3 build_reading.py            -> measures (headless Chrome), then writes
      html/*.html (one per screen), ../*.png, ../reading-sheet.png, project/*.dc.html + canvas.json
"""
import os, sys, re, json, subprocess, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, ".."))
FINAL_SRC = os.path.abspath(os.path.join(HERE, "..", "..", "src"))
sys.path.insert(0, FINAL_SRC)
sys.dont_write_bytecode = True   # no __pycache__ inside final/src

import dex                     # locked parts (patched below only in memory, for glasses)
import build as B              # locked tokens, zones, helpers, poses
from build import *            # noqa: F401,F403  (W, H, FG, FG2, LINE, PAD, SEP_Y, place, floor, ...)
from dex import g, path, ell, line, f, dim, INK

# build.py defines its own HERE; re-pin ours AFTER the star import so nothing is written into final/src
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, ".."))

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ACC = ACCENTS["b"]             # the one accent, gold

# ---- reading tokens ----------------------------------------------------------
# The reading type scale is used ONLY by the answer detail. Each step has a line height and a
# viewport of whole lines, so the scroll view rests on a line boundary with no clipped glyphs.
READ = {                        # name: (size px, line height px, visible lines)
    "S": (18, 26, 6),           # 156 px viewport
    "M": (22, 32, 5),           # 160 px viewport (default)
    "L": (26, 38, 4),           # 152 px viewport
}
LEAD = (18, 21)                 # the lead uses the system 18 step and its system line height

# ---- new character colours (props only, never UI) --------------------------
BOOK = ("#7274B8", "#50529A", "#3A3B72")   # indigo cover: clears the gold accent and the teal jacket
FRAME = INK                                 # reading-glasses frame = the one outline ink


def book_cols(P):
    return BOOK if P is PAL else tuple(dim(c) for c in BOOK)


# ---- new parts, same idiom as dex.py (flat tonal steps, one ink weight) -----
def glasses(P):
    """reading glasses in head-local units (eyes at (+-18, -60)). Drawn over the eyes."""
    ink = P["ink"]
    o = []
    for sx in (-1, 1):
        cx = sx * 19
        o.append(f'<rect x="{f(cx - 15)}" y="-71" width="30" height="23" rx="9" fill="none" '
                 f'stroke="{ink}" stroke-width="3.4"/>')
        # a single flat glint, not a glass effect
        o.append(path(f"M {f(cx - 9)} -60 L {f(cx - 4)} -66", stroke=P["eyehi"], sw=2.2))
    o.append(path("M -4 -61 C -2 -64.5 2 -64.5 4 -61", stroke=ink, sw=3.2))           # bridge
    o.append(path("M -34 -63 L -45 -58", stroke=ink, sw=3))                           # temples
    o.append(path("M 34 -63 L 45 -58", stroke=ink, sw=3))
    return "".join(o)


GL = {"on": False}
_orig_head = dex.head


def _head(P, uid, **kw):
    out = _orig_head(P, uid, **kw)
    if GL["on"]:
        fx, fy = kw.get("feat", (0, 0))
        out += g(glasses(P), f"translate({f(fx)} {f(fy)})")
    return out


dex.head = _head               # figure() looks head up in dex's globals at call time


def reading(fn):
    def wrap(*a, **k):
        GL["on"] = True
        try:
            return fn(*a, **k)
        finally:
            GL["on"] = False
    wrap.__name__ = fn.__name__
    return wrap


def book_closed(P, x, y, s=1.0, rot=0):
    """closed book, front cover toward you, spine on the left, page block on the right."""
    c0, c1, c2 = book_cols(P)
    w0, w1, w2 = P["shirt"]
    ink = P["ink"]
    o = []
    o.append(path("M -20 -29 L 23 -29 L 23 29 L -20 29 Z", fill=w1, stroke=ink, sw=3))     # page block
    o.append(path("M 22.5 -24 L 22.5 24", stroke=w2, sw=1.8))
    o.append(path("M -24 -32 L 18 -32 C 20 -32 21 -31 21 -29 L 21 29 C 21 31 20 32 18 32 L -24 32 Z",
                  fill=c1, stroke=ink, sw=3))
    o.append(path("M -24 -32 L -16 -32 L -16 32 L -24 32 Z", fill=c2, stroke=ink, sw=2.6))   # spine
    o.append(path("M -13 -29 L -10 -29 L -10 29 L -13 29 Z", fill=c0))                       # lit edge
    o.append(f'<rect x="-6" y="-19" width="21" height="13" rx="2" fill="{w0}"/>')            # title plate
    o.append(f'<rect x="-3" y="-15" width="15" height="2.4" rx="1.2" fill="{c2}"/>')
    o.append(f'<rect x="-3" y="-10.6" width="10" height="2" rx="1" fill="{P["line"]}"/>')
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


def book_open_front(P, x, y, s=1.0, rot=0):
    """open book, pages toward you (shown to the viewer)."""
    c0, c1, c2 = book_cols(P)
    w0, w1, w2 = P["shirt"]
    ink = P["ink"]
    o = []
    o.append(path("M -46 -27 L 0 -23 L 46 -27 L 46 31 L 0 35 L -46 31 Z", fill=c1, stroke=ink, sw=3))   # cover
    o.append(path("M -42 -28 C -26 -32 -8 -30 0 -24 L 0 30 C -8 25 -26 24 -42 27 Z", fill=w0, stroke=ink, sw=2.6))
    o.append(path("M 42 -28 C 26 -32 8 -30 0 -24 L 0 30 C 8 25 26 24 42 27 Z", fill=w1, stroke=ink, sw=2.6))
    o.append(path("M 0 -24 L 0 30", stroke=w2, sw=3))
    for i in range(5):
        yy = -17 + i * 8
        o.append(f'<rect x="-35" y="{f(yy)}" width="{27 if i != 4 else 16}" height="3" rx="1.5" fill="{P["line"]}"/>')
        o.append(f'<rect x="8" y="{f(yy)}" width="{27 if i != 2 else 19}" height="3" rx="1.5" fill="{P["line"]}"/>')
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


def book_open_back(P, x, y, s=1.0, rot=0):
    """open book seen from behind while Dex reads it: the cover spread faces you."""
    c0, c1, c2 = book_cols(P)
    w0, w1, w2 = P["shirt"]
    ink = P["ink"]
    o = []
    o.append(path("M -44 -30 C -26 -34 -8 -32 0 -27 C 8 -32 26 -34 44 -30 L 44 -24 L -44 -24 Z", fill=w0, stroke=ink, sw=2.6))
    o.append(path("M -46 -26 L -4 -22 L -4 32 L -46 28 Z", fill=c1, stroke=ink, sw=3))
    o.append(path("M 46 -26 L 4 -22 L 4 32 L 46 28 Z", fill=c2, stroke=ink, sw=3))
    o.append(path("M -6 -24 L 6 -24 L 6 34 L -6 34 Z", fill=c2, stroke=ink, sw=2.6))        # spine
    o.append(path("M -41 -20 L -36 -19.6 L -36 24 L -41 23.6 Z", fill=c0))
    o.append(f'<rect x="14" y="-12" width="22" height="13" rx="2" fill="{w1}"/>')           # front cover plate
    o.append(f'<rect x="17" y="-8" width="15" height="2.4" rx="1.2" fill="{c2}"/>')
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


def note_card(P, x, y, s=1.0, rot=0):
    """a small folded note (the saved thought), paper white, two written lines."""
    w0, w1, w2 = P["shirt"]
    ink = P["ink"]
    o = [path("M -12 -16 L 12 -16 L 12 16 L -12 16 Z", fill=w0, stroke=ink, sw=2.6),
         path("M 5 -15 L 11 -15 L 11 15 L 5 15 Z", fill=w1),
         f'<rect x="-8" y="-10" width="14" height="2.6" rx="1.3" fill="{P["line"]}"/>',
         f'<rect x="-8" y="-4" width="10" height="2.6" rx="1.3" fill="{P["line"]}"/>']
    return g("".join(o), f"translate({f(x)} {f(y)}) rotate({f(rot)}) scale({f(s)})")


# ---- reading poses (none repeats a final pose or each other) ------------------
@reading
def pose_book_hug(P, uid, frame=0):
    """R1 reading home: glasses on, the current book held against his chest, finger keeping the place."""
    return figure(
        P, uid, head_rot=-3, eyes="open" if frame != 1 else "blink", brows="neutral", mouth="smile",
        look=(0, 1), feat=(-1, 0),
        legL=((-17, 4), (-19, 38), (-21, 70)), legR=((17, 4), (21, 38), (23, 70)),
        shoeL=(-21, 72, 0), shoeR=(24, 72, 0),
        props_front=(book_closed(P, 10, -50, 1.25, rot=-14),),
        armL=((-42, -74), (-58, -38), (-8, -34)), handL=(-6, -36, 350, "mitt", -1),
        armR=((42, -74), (58, -40), (34, -74)), handR=(32, -76, 205, "mitt", 1),
        badge=None,
    )


@reading
def pose_show_page(P, uid, talking=False):
    """R2 lead: holds the open page out toward you, pushes his glasses up with the other hand.
    Quiet mode = closed smile (nothing is spoken); speak mode swaps in the mouth frames."""
    return figure(
        P, uid, body_rot=-3, head_rot=-5, head_dx=-2,
        eyes="open", look=(-2, 0), brows="raised", mouth="open" if talking else "smile", feat=(-2, 0),
        legL=((-17, 4), (-22, 38), (-26, 70)), legR=((17, 4), (18, 38), (18, 70)),
        shoeL=(-27, 72, 0), shoeR=(19, 72, 0),
        armL=((-42, -74), (-66, -44), (-50, -40)), handL=(-48, -42, 20, "mitt", -1),
        props_top=(book_open_front(P, -44, -58, 0.92, rot=-8),),
        armR=((42, -74), (76, -94), (36, -128)), handR=(30, -134, 205, "mitt", -1),
    )


@reading
def pose_read(P, uid, frame=0):
    """R3/R5 detail: passive reading, cover toward you, eyes down on the page, head tipped."""
    return figure(
        P, uid, head_dy=9, head_rot=5, head_dx=1, body_dy=2,
        eyes="down", brows="soft", mouth="tiny", feat=(1, 6),
        legL=((-17, 4), (-17, 38), (-17, 70)), legR=((17, 4), (19, 38), (21, 70)),
        shoeL=(-18, 72, 0), shoeR=(22, 72, 0),
        armL=((-42, -74), (-64, -40), (-40, -56)), armR=((42, -74), (64, -40), (40, -56)),
        props_top=(book_open_back(P, 0, -54, 0.95, rot=0),),
        handL=(-40, -56, 350, "mitt", -1), handR=(40, -56, 190, "mitt", 1),
    )


@reading
def pose_shh(P, uid):
    """R4 quiet: finger to his lips, book tucked under the other arm."""
    return figure(
        P, uid, head_rot=-6, head_dx=-2, feat=(-2, 0),
        eyes="happy", brows="soft", mouth="tiny",
        legL=((-17, 4), (-20, 38), (-22, 70)), legR=((17, 4), (18, 38), (18, 70)),
        shoeL=(-22, 72, 0), shoeR=(19, 72, 0),
        props_mid=(book_closed(P, -52, -40, 1.05, rot=10),),
        armL=((-42, -74), (-56, -40), (-46, -10)), handL=(-46, -10, 92, "mitt", 1),
        armR=((42, -74), (60, -44), (12, -84)), handR=(8, -92, 270, "point", -1),
    )


@reading
def pose_call(P, uid):
    """R4 voice on: lifts the open book up beside his head like a town crier, chin up, ready to read out."""
    return figure(
        P, uid, head_rot=-6, head_dx=-2, feat=(-2, -2), body_rot=-2,
        eyes="up", brows="raised", mouth="o", look=(-1, -3),
        legL=((-17, 4), (-20, 38), (-22, 70)), legR=((17, 4), (24, 38), (30, 70)),
        shoeL=(-22, 72, 0), shoeR=(31, 72, 0),
        **RELAX_L,
        armR=((42, -74), (80, -96), (84, -134)), handR=(84, -136, 270, "mitt", -1),
        props_top=(book_open_front(P, 84, -160, 0.85, rot=8),),
    )


@reading
def pose_tuck(P, uid):
    """R6 saved: holds the closed book out at his side and presses the note down into it, a satisfied nod."""
    return figure(
        P, uid, head_rot=10, head_dy=6, head_dx=3, feat=(2, 3), body_rot=3,
        eyes="happy", brows="soft", mouth="grin",
        legL=((-17, 4), (-21, 38), (-24, 70)), legR=((17, 4), (21, 38), (24, 70)),
        shoeL=(-25, 72, 0), shoeR=(25, 72, 0),
        props_top=(note_card(P, 57, -88, 1.15, rot=4), book_closed(P, 54, -34, 1.15, rot=4)),
        armL=((-42, -74), (-54, -36), (22, -14)), handL=(24, -16, 350, "mitt", -1),
        armR=((42, -74), (98, -104), (62, -120)), handR=(61, -122, 95, "mitt", 1),
    )


# ---- content ----------------------------------------------------------------
BOOK_T, BOOK_A, BOOK_C = "Piranesi", "Susanna Clarke", "7"

LEAD_TXT = ("He trusts the House because it never fails him: it feeds him through the tides, shelters him "
            "and rewards attention with order. That&#8217;s his claim, not Clarke&#8217;s. Read it as a clue: "
            "his trust is total; she wants you to notice what he never asks.")

DETAIL = [
    ("What the text says.",
     "Through chapter 7 the narrator describes the House as generous. The tides bring fish and seaweed, "
     "the halls give shelter, and the statues repay the time he spends looking at them. He keeps careful "
     "journals and treats the House&#8217;s patterns as a kind of speech."),
    ("Interpretation.",
     "His trust reads as faith more than evidence. He records everything, yet he never asks where the "
     "House came from or why so few people walk its halls. The calm voice is the point; the questions he "
     "steps around are where the tension sits."),
    ("Background.",
     "The title nods to Giovanni Battista Piranesi, the 18th-century artist known for etchings of vast, "
     "impossible prisons. Treat that as context, not as a key to the plot."),
    ("",
     "No spoilers past chapter 7. Give me the passage you&#8217;re on and I&#8217;ll stay with the words on "
     "the page."),
]

THOUGHT = "The House only feels kind because he never stops paying attention to it."


def wrap_txt(x, y, w, size, lh, s, color=FG, weight=500, ls="-0.1px"):
    return (f'<div style="position: absolute; left: {x}px; top: {y}px; width: {w}px; font-size: {size}px; '
            f'line-height: {lh}px; font-weight: {weight}; color: {color}; letter-spacing: {ls}">{s}</div>')


def scroll_view(step, y_off, view_lines=None):
    """the one scroll column (lead, then detail) clipped to the content zone.
    y_off = column offset in px (baked from the measure pass)."""
    size, lh, n = READ[step]
    view = lh * n
    lead = (f'<div data-k="lead" style="min-height: {view}px; font-size: {LEAD[0]}px; line-height: {LEAD[1]}px; '
            f'font-weight: 500; color: {FG}; letter-spacing: -0.1px">{LEAD_TXT}</div>')
    paras = ""
    for i, (h, b) in enumerate(DETAIL):
        head_ = f'<span style="font-weight: 600; color: {FG}">{h}</span> ' if h else ""
        paras += (f'<p data-k="p{i}" style="margin: 0 0 {lh}px 0">{head_}{b}</p>')
    detail = (f'<div data-k="detail" style="font-size: {size}px; line-height: {lh}px; font-weight: 400; '
              f'color: {FG2}; letter-spacing: -0.1px">{paras}</div>')
    return (f'<div style="position: absolute; left: {PAD}px; top: {PAD}px; width: {W - 2 * PAD}px; height: {view}px; '
            f'overflow: hidden"><div data-col="1" style="position: absolute; left: 0; top: 0; width: 100%; '
            f'transform: translateY(-{y_off}px)">{lead}{detail}</div></div>')


def scroll_thumb(y_off, total, view):
    """the scroll-position cue: a FG2 segment riding the separator (not the accent: it is not an action)."""
    track = W - 2 * PAD
    ln = max(24, round(track * view / total))
    pos = 0 if total <= view else round((track - ln) * y_off / (total - view))
    return (f'<line x1="{PAD + pos + 1.5}" y1="{SEP_Y}" x2="{PAD + pos + ln - 1.5}" y2="{SEP_Y}" stroke="{FG2}" '
            f'stroke-width="{SEP_W}" stroke-linecap="round"/>')


def book_block():
    t = txt(PAD, PAD, T32, BOOK_T)
    t += txt(PAD, PAD + 46, T18, f"{BOOK_A} · Chapter {BOOK_C}", FG2, 400)
    return t


def status_line(s):
    return txt(PAD, SEP_Y - 20 - 28, T24, s, FG2, 500)


# ---- screens: (art svg, html layer) ------------------------------------------
M = {}      # measured: {step: {"lead_h":..., "detail_top":..., "total":...}}


def s_r1(u):
    art = floor() + separator() + place(pose_book_hug(P, u + "h"))
    t = book_block() + status_line("Quiet · text only")
    t += act(362, "Turn voice on", ACC, w=164)
    return art, t


def s_r2(u):
    size, lh, n = READ["M"]
    m = M.get("M")
    art = floor() + separator() + place(pose_show_page(P, u + "r"))
    if m:
        art += scroll_thumb(0, m["total"], lh * n)
    t = scroll_view("M", 0)
    t += act(236, "Read more", ACC, w=140)
    t += txt(PAD, 376, T18, BOOK_T, FG, 500) + txt(PAD, 397, T18, f"Clarke · ch {BOOK_C}", FG2, 400)
    return art, t


def detail_screen(u, step, line_k, rail):
    size, lh, n = READ[step]
    m = M.get(step, {"detail_top": 0, "total": 1000})
    y = m["detail_top"] + line_k * lh
    art = floor() + separator() + place(pose_read(P, u + "d"))
    art += scroll_thumb(y, m["total"], lh * n)
    t = scroll_view(step, y)
    if "up" in rail:
        t += act(304, "Larger", ACC, w=120)
    if "down" in rail:
        t += act(362, "Smaller", ACC, w=120)
    return art, t


def s_r3(u):
    return detail_screen(u, "M", 4, ("up", "down"))


def s_r5s(u):
    return detail_screen(u, "S", 4, ("up",))


def s_r5l(u):
    return detail_screen(u, "L", 4, ("down",))


def s_r4q(u):
    art = floor() + separator() + place(pose_shh(P, u + "q"))
    t = book_block() + status_line("Quiet · text only")
    t += act(362, "Turn voice on", ACC, w=164)
    return art, t


def s_r4s(u):
    art = floor() + separator() + place(pose_call(P, u + "s"))
    t = book_block() + status_line("Voice on · lead only")
    t += act(362, "Go quiet", ACC, w=120)
    return art, t


def s_r6(u):
    art = floor() + separator() + place(pose_tuck(P, u + "v"))
    t = txt(PAD, PAD, T32, "Saved.")
    t += wrap_txt(PAD, PAD + 50, W - 2 * PAD, T24, 28, f"&#8220;{THOUGHT}&#8221;", FG, 500)
    t += txt(PAD, 376, T18, BOOK_T, FG2, 400) + txt(PAD, 397, T18, f"Chapter {BOOK_C}", FG2, 400)
    return art, t


SCREENS = [
    ("r1-home", "R1Home", "R1. Reading home", s_r1),
    ("r2-lead", "R2Lead", "R2. Answer, lead", s_r2),
    ("r3-detail", "R3Detail", "R3. Answer, detail scrolled", s_r3),
    ("r4-quiet", "R4Quiet", "R4. Quiet (default)", s_r4q),
    ("r4-speak", "R4Speak", "R4. Voice on", s_r4s),
    ("r5-size-small", "R5Small", "R5. Detail, smallest (18)", s_r5s),
    ("r5-size-large", "R5Large", "R5. Detail, largest (26)", s_r5l),
    ("r6-saved", "R6Saved", "R6. Saved", s_r6),
]


# ---- measure pass: real font metrics from headless Chrome ------------------
MEASURE_JS = """
<script>
document.fonts.ready.then(function(){
  var out = {};
  document.querySelectorAll('[data-step]').forEach(function(el){
    var col = el.querySelector('[data-col]');
    var lead = col.querySelector('[data-k=lead]');
    var det = col.querySelector('[data-k=detail]');
    out[el.dataset.step] = {lead_h: lead.offsetHeight, lead_scroll: lead.scrollHeight,
      detail_top: det.offsetTop, total: col.offsetHeight};
  });
  document.body.setAttribute('data-m', JSON.stringify(out));
});
</script>"""


def measure():
    body = "".join(f'<div data-step="{k}" style="position: relative; width: {W}px; height: {H}px">'
                   f'{scroll_view(k, 0)}</div>' for k in READ)
    html = single(body).replace("</body>", MEASURE_JS + "</body>")
    p = os.path.join(HERE, "html", "_measure.html")
    open(p, "w").write(html)
    dom = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
                          "--virtual-time-budget=5000", "--dump-dom", "file://" + p],
                         capture_output=True, text=True).stdout
    mm = re.search(r'data-m="([^"]+)"', dom)
    data = json.loads(mm.group(1).replace("&quot;", '"'))
    # the column ends with one blank line of paragraph margin: trim it from the total
    for k, v in data.items():
        v["total"] -= READ[k][1]
    return data


def shot(html_path, png, w=W, h=H):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
                    "--virtual-time-budget=4000", f"--window-size={w},{h}", f"--screenshot={png}",
                    "file://" + html_path], capture_output=True)


def sheet_html(boards):
    cells = "".join(
        f'<div class="c"><div class="t">{screen_div(b)}</div><div class="l">{title}</div></div>'
        for _, _, title, b in boards)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Dex Charm reading mode</title>
<link href="{FONT_LINK}" rel="stylesheet">
<style>
html,body{{margin:0;background:#2B2C30}}
.g{{display:flex;gap:40px;padding:40px 40px 24px;width:max-content}}
.t{{width:368px;height:448px}}
.l{{font-family:{FONT};font-size:18px;line-height:24px;color:#D6D3CC;margin-top:12px}}
button{{cursor:pointer}}
</style></head><body><div class="g">{cells}</div></body></html>"""


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "html"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "project"), exist_ok=True)
    M.update(measure())
    print("measured", json.dumps(M))
    boards = []
    for slug, name, title, fn in SCREENS:
        art, t = fn(slug[:3].replace("-", ""))
        boards.append((slug, name, title, svg(art) + t))
    for slug, _, _, b in boards:
        hp = os.path.join(HERE, "html", slug + ".html")
        open(hp, "w").write(single(b))
        shot(hp, os.path.join(OUT, slug + ".png"))
    sp = os.path.join(HERE, "html", "reading-sheet.html")
    open(sp, "w").write(sheet_html(boards))
    shot(sp, os.path.join(OUT, "reading-sheet.png"), 40 + len(boards) * (368 + 40), 40 + 448 + 12 + 24 + 24)
    # Claude Design project files (same format as final/src/build.py)
    bd, order = {}, []
    for i, (slug, name, title, b) in enumerate(boards):
        fn = ("Main" if i == 0 else name) + ".dc.html"
        open(os.path.join(HERE, "project", fn), "w").write(dc(title, b))
        bd[fn] = {"x": i * (368 + 80), "y": 0, "w": 368, "h": 448, "title": title}
        order.append(fn)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    canvas = {"v": 3, "createdOnFiles": {"v": 1, "at": now}, "title": "Dex Charm · Reading mode",
              "launch": {"view": "canvas"}, "pages": [], "boards": bd, "order": order, "notes": {},
              "designSystems": []}
    json.dump(canvas, open(os.path.join(HERE, "project", "canvas.json"), "w"), ensure_ascii=False, indent=1)
    print(len(boards), "boards")
