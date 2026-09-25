from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from conftest import DUMMY_MANIFEST, TOOLS, UI

from charm_assets import cli, fonts, manifest
from charm_assets.manifest import FontFace, ManifestError

SAMPLE = """/*******************************************************************************
 * Size: 14 px
 * Opts: --font /Users/someone/x.ttf
 ******************************************************************************/

#ifdef LV_LVGL_H_INCLUDE_SIMPLE
#include "lvgl.h"
#else
#include "lvgl/lvgl.h"
#endif

static const uint8_t glyph_bitmap[] = {
    /* U+0041 "A" */
    0x01,
};

#if LVGL_VERSION_MAJOR >= 8
const lv_font_t f14 = {
#else
lv_font_t f14 = {
#endif
    .dsc = 0,
};
"""


def test_ranges_parse() -> None:
    assert fonts.parse_ranges(("0x41-0x43", "0xB0")) == {0x41, 0x42, 0x43, 0xB0}
    with pytest.raises(ManifestError):
        fonts.parse_ranges(("0x43-0x41",))
    with pytest.raises(ManifestError):
        fonts.parse_ranges(("zz",))


def test_coverage_requires_spanish_and_latin1() -> None:
    face = FontFace("body", Path("x.ttf"), (14,), ("0x20-0x7E",), ())
    with pytest.raises(ManifestError, match="ñ"):
        fonts.check_coverage(face)
    fonts.check_coverage(FontFace("body", Path("x.ttf"), (14,), ("0x20-0x7E", "0xA0-0xFF"), ()))


def test_ui_symbols_are_found() -> None:
    assert "OK" in fonts.ui_symbols(UI)  # the ✓ on confirmed cards
    face = FontFace("body", Path("x.ttf"), (14,), (), ("WIFI",))
    assert fonts.symbols_for(face, UI)[:1] == ["OK"]  # sorted by codepoint
    with pytest.raises(ManifestError, match="NOPE"):
        fonts.symbols_for(FontFace("b", Path("x"), (14,), (), ("NOPE",)), None)


def test_adapt_namespaces_output_and_gives_the_font_c_linkage() -> None:
    out = fonts.adapt(SAMPLE, "f14")
    assert out.startswith("namespace f14_data {")
    assert "Opts:" not in out and "/Users/" not in out
    assert "#include" not in out
    assert 'extern "C" const lv_font_t f14 = {' in out
    assert fonts.glyphs_in(SAMPLE) == {0x41}
    with pytest.raises(ManifestError):
        fonts.adapt(SAMPLE, "other")


def test_committed_fonts_cover_the_required_glyphs() -> None:
    m = manifest.load(DUMMY_MANIFEST)
    assert m.fonts
    header = (UI / "charm_assets_fonts.h").read_text()
    source = (UI / "charm_assets_fonts.cpp").read_text()
    assert source.startswith("// GENERATED — do not edit.")
    sections = re.split(r"(?m)^namespace charm_font_", source)[1:]
    assert len(sections) == sum(len(f.sizes) for f in m.fonts.faces)
    for section in sections:
        glyphs = fonts.glyphs_in(section)
        for ch in "ñáéíóúü¿¡°·":
            assert ord(ch) in glyphs, (ch, section[:40])
        assert fonts.LV_SYMBOLS["OK"] in glyphs
    for face in m.fonts.faces:
        for size in face.sizes:
            assert f"extern const lv_font_t {fonts.font_symbol(face.name, size)};" in header


def test_font_licenses_are_committed() -> None:
    for name in ("AtkinsonHyperlegible-OFL.txt", "lvgl-symbols-OFL.txt"):
        text = (TOOLS / "fonts" / name).read_text()
        assert "SIL OPEN FONT LICENSE Version 1.1" in text


@pytest.mark.skipif(shutil.which("npx") is None, reason="lv_font_conv runs through npx")
def test_committed_font_files_are_up_to_date() -> None:
    rc = cli.main(["fonts", str(DUMMY_MANIFEST), "--out-dir", str(UI), "--check"])
    assert rc == 0, "ui/charm_assets_fonts.* are stale: run `uv run charm-assets fonts ...`"
