"""RGB565 survival: the panel shows 16-bit color, so two palette colors can become one."""

from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[int, int, int]


def to_rgb565(c: RGB) -> int:
    r, g, b = c
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def from_rgb565(v: int) -> RGB:
    """What the panel actually shows for a 16-bit value (bit-replicated back to 8 bits)."""
    r5, g6, b5 = (v >> 11) & 0x1F, (v >> 5) & 0x3F, v & 0x1F
    return (r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2)


def hexs(c: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*c)


@dataclass(frozen=True)
class PaletteReport:
    collisions: list[tuple[RGB, RGB, int]]  # two palette colors that quantize to the same value
    max_error: int  # the worst per-channel shift any color takes

    def warnings(self) -> list[str]:
        return [
            f"palette colors {hexs(a)} and {hexs(b)} both become RGB565 0x{v:04X} "
            f"({hexs(from_rgb565(v))}) on the panel: they will look identical"
            for a, b, v in self.collisions
        ]


def check(palette: tuple[RGB, ...] | list[RGB]) -> PaletteReport:
    first: dict[int, RGB] = {}
    collisions: list[tuple[RGB, RGB, int]] = []
    max_error = 0
    for c in palette:
        v = to_rgb565(c)
        shown = from_rgb565(v)
        max_error = max(max_error, *(abs(x - y) for x, y in zip(c, shown, strict=True)))
        if v in first:
            collisions.append((first[v], c, v))
        else:
            first[v] = c
    return PaletteReport(collisions=collisions, max_error=max_error)
