"""Fonts -> ui/charm_assets_fonts.{h,cpp} through lv_font_conv (pinned, run with npx).

lv_font_conv writes one C file per font, meant to be its own translation unit, with file-static
tables that collide when several share a file, and a `const lv_font_t` that C++ would give internal
linkage. So each font's output goes into its own namespace, and its lv_font_t is defined
`extern "C"` there, which makes it the same global object the header declares.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import cgen
from .manifest import FontFace, FontSpec, ManifestError

# LVGL 8.3 src/font/lv_symbol_def.h: LV_SYMBOL_<name> -> codepoint.
LV_SYMBOLS: dict[str, int] = {
    "BULLET": 0x2022,
    "AUDIO": 0xF001, "VIDEO": 0xF008, "LIST": 0xF00B, "OK": 0xF00C, "CLOSE": 0xF00D,
    "POWER": 0xF011, "SETTINGS": 0xF013, "HOME": 0xF015, "DOWNLOAD": 0xF019, "DRIVE": 0xF01C,
    "REFRESH": 0xF021, "MUTE": 0xF026, "VOLUME_MID": 0xF027, "VOLUME_MAX": 0xF028,
    "IMAGE": 0xF03E, "TINT": 0xF043, "PREV": 0xF048, "PLAY": 0xF04B, "PAUSE": 0xF04C,
    "STOP": 0xF04D, "NEXT": 0xF051, "EJECT": 0xF052, "LEFT": 0xF053, "RIGHT": 0xF054,
    "PLUS": 0xF067, "MINUS": 0xF068, "EYE_OPEN": 0xF06E, "EYE_CLOSE": 0xF070,
    "WARNING": 0xF071, "SHUFFLE": 0xF074, "UP": 0xF077, "DOWN": 0xF078, "LOOP": 0xF079,
    "DIRECTORY": 0xF07B, "UPLOAD": 0xF093, "CALL": 0xF095, "CUT": 0xF0C4, "COPY": 0xF0C5,
    "SAVE": 0xF0C7, "BARS": 0xF0C9, "ENVELOPE": 0xF0E0, "CHARGE": 0xF0E7, "PASTE": 0xF0EA,
    "BELL": 0xF0F3, "KEYBOARD": 0xF11C, "GPS": 0xF124, "FILE": 0xF158, "WIFI": 0xF1EB,
    "BATTERY_FULL": 0xF240, "BATTERY_3": 0xF241, "BATTERY_2": 0xF242, "BATTERY_1": 0xF243,
    "BATTERY_EMPTY": 0xF244, "USB": 0xF287, "BLUETOOTH": 0xF293, "TRASH": 0xF2ED,
    "EDIT": 0xF304, "BACKSPACE": 0xF55A, "SD_CARD": 0xF7C2, "NEW_LINE": 0xF8A2,
}  # fmt: skip

# Every face must render these: ASCII, and the Spanish/Latin-1 the cards use.
REQUIRED_TEXT = "".join(chr(c) for c in range(0x20, 0x7F)) + "ñáéíóúü¿¡°·ÑÁÉÍÓÚÜ"

_SYMBOL_USE = re.compile(r"\bLV_SYMBOL_([A-Z0-9_]+)\b")


def ui_symbols(ui_dir: Path) -> list[str]:
    """LV_SYMBOL_* names the hand-written UI uses (generated charm_assets_* files excluded)."""
    found: set[str] = set()
    for p in sorted(ui_dir.glob("*")):
        if p.suffix in (".cpp", ".h") and not p.name.startswith("charm_assets_"):
            found |= set(_SYMBOL_USE.findall(p.read_text(encoding="utf-8", errors="replace")))
    return sorted(s for s in found if s in LV_SYMBOLS)


def parse_ranges(ranges: tuple[str, ...]) -> set[int]:
    cps: set[int] = set()
    for r in ranges:
        for part in r.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                if "-" in part:
                    lo, hi = (int(x, 0) for x in part.split("-", 1))
                else:
                    lo = hi = int(part, 0)
            except ValueError as e:
                raise ManifestError(f"font range {part!r}: use 0x20-0x7E or 0xB0") from e
            if lo > hi:
                raise ManifestError(f"font range {part!r} is backwards")
            cps.update(range(lo, hi + 1))
    return cps


def symbols_for(face: FontFace, ui_dir: Path | None) -> list[str]:
    names = set(face.symbols) | set(ui_symbols(ui_dir) if ui_dir else [])
    unknown = sorted(n for n in names if n not in LV_SYMBOLS)
    if unknown:
        raise ManifestError(f"font {face.name}: unknown LVGL symbols {', '.join(unknown)}")
    return sorted(names, key=lambda n: LV_SYMBOLS[n])


def check_coverage(face: FontFace) -> None:
    cps = parse_ranges(face.ranges)
    missing = [ch for ch in REQUIRED_TEXT if ord(ch) not in cps]
    if missing:
        raise ManifestError(
            f"font {face.name}: ranges miss required characters {''.join(missing)!r} "
            "(ASCII + Latin-1 is 0x20-0x7E, 0xA0-0xFF)"
        )


def font_symbol(face: str, size: int) -> str:
    return f"charm_font_{face}_{size}"


@dataclass(frozen=True)
class FontJob:
    face: FontFace
    size: int
    symbols: tuple[str, ...]

    @property
    def symbol(self) -> str:
        return font_symbol(self.face.name, self.size)


def lv_font_conv_args(job: FontJob, spec: FontSpec, tmp: Path) -> list[str]:
    args = [
        "--bpp", str(spec.bpp), "--size", str(job.size), "--no-compress",
        "--font", job.face.file.name, "-r", ",".join(job.face.ranges),
    ]  # fmt: skip
    if job.symbols:
        cps = ",".join(f"0x{LV_SYMBOLS[s]:X}" for s in job.symbols)
        args += ["--font", spec.symbols_file.name, "-r", cps]
    args += ["--format", "lvgl", "--lv-font-name", job.symbol, "-o", str(tmp / "out.c")]
    return args


def run_lv_font_conv(job: FontJob, spec: FontSpec) -> str:
    npx = shutil.which("npx")
    if npx is None:
        raise ManifestError("fonts need Node's npx on PATH (lv_font_conv runs through npx)")
    for f in (job.face.file, spec.symbols_file):
        if not f.is_file():
            raise ManifestError(f"font file {f} does not exist")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        # Font paths are passed as bare names from a folder holding both, so the output doesn't
        # carry absolute paths from this machine.
        work = tmp / "fonts"
        work.mkdir()
        shutil.copy(job.face.file, work / job.face.file.name)
        shutil.copy(spec.symbols_file, work / spec.symbols_file.name)
        cmd = [npx, "-y", f"lv_font_conv@{spec.lv_font_conv}", *lv_font_conv_args(job, spec, tmp)]
        proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise ManifestError(
                f"lv_font_conv failed for {job.symbol}:\n{proc.stdout}{proc.stderr}".rstrip()
            )
        return (tmp / "out.c").read_text(encoding="utf-8")


_HEADER = re.compile(r"\A/\*+.*?\*+/\s*", re.S)
_INCLUDE = re.compile(
    r'#ifdef LV_LVGL_H_INCLUDE_SIMPLE\s*#include "lvgl\.h"\s*#else\s*#include "lvgl/lvgl\.h"\s*'
    r"#endif\s*"
)
_GLYPH = re.compile(r"/\* U\+([0-9A-F]{4,6}) ")


def glyphs_in(c_source: str) -> set[int]:
    return {int(m, 16) for m in _GLYPH.findall(c_source)}


def adapt(c_source: str, symbol: str) -> str:
    """Make one lv_font_conv output safe to share a C++ translation unit with others."""
    body, n = _HEADER.subn("", c_source, count=1)
    if n != 1:
        raise ManifestError(f"{symbol}: unexpected lv_font_conv output (no header comment)")
    body, n = _INCLUDE.subn("", body, count=1)
    if n != 1:
        raise ManifestError(f"{symbol}: unexpected lv_font_conv output (include block)")
    decl = f"const lv_font_t {symbol} = {{"
    if body.count(decl) != 1:
        raise ManifestError(f"{symbol}: unexpected lv_font_conv output (font definition)")
    body = body.replace(decl, f'extern "C" const lv_font_t {symbol} = {{')
    body = "\n".join(line.rstrip() for line in body.strip().splitlines())
    return f"namespace {symbol}_data {{\n\n{body}\n\n}}  // namespace {symbol}_data\n"


@dataclass
class FontBuild:
    jobs: list[FontJob]
    sections: list[str]


def build(spec: FontSpec, ui_dir: Path | None) -> FontBuild:
    jobs = []
    for face in spec.faces:
        check_coverage(face)
        syms = tuple(symbols_for(face, ui_dir))
        jobs += [FontJob(face, size, syms) for size in face.sizes]
    sections = []
    for job in jobs:
        src = run_lv_font_conv(job, spec)
        want = {ord(ch) for ch in REQUIRED_TEXT} | {LV_SYMBOLS[s] for s in job.symbols}
        missing = sorted(want - glyphs_in(src) - {0x20, 0xA0})  # spaces have no bitmap
        if missing:
            shown = ", ".join(f"U+{cp:04X}" for cp in missing[:12])
            raise ManifestError(f"{job.symbol}: the font file has no glyph for {shown}")
        sections.append(adapt(src, job.symbol))
    return FontBuild(jobs=jobs, sections=sections)


def render(spec: FontSpec, result: FontBuild, command: str, sources: list[str]) -> tuple[str, str]:
    head = cgen.banner(
        f"Fonts from lv_font_conv {spec.lv_font_conv} (--bpp {spec.bpp} --no-compress).",
        command,
        sources,
    )
    h = [head, "#pragma once", "#include <lvgl.h>", "", 'extern "C" {']
    for job in result.jobs:
        syms = " ".join(job.symbols) or "none"
        h.append(
            f"// {job.face.name} {job.size}px: {job.face.file.name}, ranges "
            f"{','.join(job.face.ranges)}; LV_SYMBOL_: {syms}"
        )
        h.append(f"extern const lv_font_t {job.symbol};")
    h += ["}", ""]
    c = [head, '#include "charm_assets_fonts.h"', ""]
    c += result.sections
    return "\n".join(h), "\n".join(c)
