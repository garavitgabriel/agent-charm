"""The dummy test sheet: plain shapes on a test-card border, deliberately nothing like Dex.

It exists to prove the pipeline end to end before the design sprint hands over the real art.
Layout (32x40 cells, 2 frames a row):
  row 0  idle      default   circle that shrinks a pixel, bar steps right
  row 1  listening default   triangle, then triangle + yellow ripple lines
  row 2  working   default   square steps left -> right
  row 3  idle      gameday   the idle circle with a yellow "hat" bar
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

CELL = (32, 40)
BORDER = (0xFF, 0x00, 0xFF)
TEAL = (0x00, 0xC8, 0xB4)
YELLOW = (0xFF, 0xD0, 0x00)
WHITE = (0xFF, 0xFF, 0xFF)
INK = (0x28, 0x30, 0x50)
PALETTE = (BORDER, TEAL, YELLOW, WHITE, INK)


def _cell(draw: ImageDraw.ImageDraw, col: int, row: int, kind: str, frame: int) -> None:
    w, h = CELL
    x0, y0 = col * w, row * h

    def px(x: int, y: int, c: tuple[int, int, int]) -> None:
        draw.point((x0 + x, y0 + y), fill=(*c, 255))

    def rect(x1: int, y1: int, x2: int, y2: int, c: tuple[int, int, int]) -> None:
        draw.rectangle((x0 + x1, y0 + y1, x0 + x2, y0 + y2), fill=(*c, 255))

    # Dashed test-card border and a 4x4 checker in the bottom-right corner.
    for x in range(0, w, 2):
        px(x, 0, BORDER)
        px(x, h - 1, BORDER)
    for y in range(0, h, 2):
        px(0, y, BORDER)
        px(w - 1, y, BORDER)
    for y in range(4):
        for x in range(4):
            px(w - 6 + x, h - 6 + y, WHITE if (x + y) % 2 else INK)
    # A bar along the bottom that steps with the frame, so animation is obvious at a glance.
    rect(3 + frame * 8, h - 9, 10 + frame * 8, h - 8, INK)

    if kind in ("idle", "gameday"):
        r = 8 - frame
        draw.ellipse((x0 + 16 - r, y0 + 14 - r, x0 + 16 + r, y0 + 14 + r), fill=(*TEAL, 255))
        rect(10, 26, 22, 28, INK)
        if kind == "gameday":
            rect(8, 3, 24, 4, YELLOW)
    elif kind == "listening":
        draw.polygon([(x0 + 16, y0 + 5), (x0 + 7, y0 + 22), (x0 + 25, y0 + 22)], fill=(*TEAL, 255))
        if frame:
            for i in range(3):
                rect(26, 8 + i * 5, 28, 8 + i * 5, YELLOW)
    elif kind == "working":
        x = 5 + frame * 10
        rect(x, 8, x + 11, 19, TEAL)
        rect(x + 3, 11, x + 8, 16, WHITE)


def make_sheet() -> Image.Image:
    rows = ("idle", "listening", "working", "gameday")
    img = Image.new("RGBA", (CELL[0] * 2, CELL[1] * len(rows)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for row, kind in enumerate(rows):
        for col in range(2):
            _cell(draw, col, row, kind, col)
    return img


def write_sheet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    make_sheet().save(path, format="PNG", optimize=False)
