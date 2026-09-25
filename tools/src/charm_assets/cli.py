"""charm-assets: turn the design sprint's sprite sheets and fonts into ui/charm_assets_*.{h,cpp}."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from . import cgen, dummy, fonts, manifest, palette, sprites

TOOLS_DIR = Path(__file__).resolve().parents[2]
UI_DIR = TOOLS_DIR.parent / "ui"


def _source(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return f"{cgen.rel_to_tools(path, TOOLS_DIR)} (sha256 {digest})"


def _emit(out_dir: Path, stem: str, h: str, c: str, check: bool) -> int:
    targets = [(out_dir / f"{stem}.h", h), (out_dir / f"{stem}.cpp", c)]
    if check:
        stale = [p for p, text in targets if not p.exists() or p.read_text("utf-8") != text]
        for p in stale:
            print(f"stale: {p} (re-run without --check)", file=sys.stderr)
        return 1 if stale else 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for p, text in targets:
        changed = cgen.write_if_changed(p, text)
        print(f"{'wrote' if changed else 'unchanged'} {p} ({len(text.encode()):,} bytes)")
    return 0


def _load(path: str) -> manifest.Manifest:
    return manifest.load(Path(path))


def _command(verb: str, m: manifest.Manifest) -> str:
    return f"{verb} {cgen.rel_to_tools(m.path, TOOLS_DIR)}"


def cmd_sprites(args: argparse.Namespace) -> int:
    m = _load(args.manifest)
    if m.sprites is None:
        raise manifest.ManifestError("the manifest has no sprites section")
    spec = m.sprites
    result = sprites.build(spec)
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    sources = [_source(m.path), *(_source(p) for p in spec.sheets.values())]
    h, c = sprites.render(spec, result, _command("sprites", m), sources)
    print(
        f"{len(result.images)} unique frames as {result.encoding.cf}, "
        f"{result.data_bytes:,} bytes of pixel data"
    )
    return _emit(Path(args.out_dir), "charm_assets_sprites", h, c, args.check)


def cmd_fonts(args: argparse.Namespace) -> int:
    m = _load(args.manifest)
    if m.fonts is None:
        raise manifest.ManifestError("the manifest has no fonts section")
    spec = m.fonts
    ui_dir = None if args.no_ui_scan else UI_DIR
    result = fonts.build(spec, ui_dir)
    files = sorted({f.file for f in spec.faces} | {spec.symbols_file})
    sources = [_source(m.path), *(_source(p) for p in files)]
    h, c = fonts.render(spec, result, _command("fonts", m), sources)
    print(", ".join(j.symbol for j in result.jobs))
    return _emit(Path(args.out_dir), "charm_assets_fonts", h, c, args.check)


def cmd_check(args: argparse.Namespace) -> int:
    m = _load(args.manifest)
    if m.sprites:
        spec = m.sprites
        rep = palette.check(spec.palette)
        print(f"palette: {len(spec.palette)} colors, worst RGB565 shift {rep.max_error}/255")
        for w in rep.warnings():
            print(f"warning: {w}")
        result = sprites.build(spec)
        enc = result.encoding
        fb = sprites.frame_bytes(spec.cell_w, spec.cell_h, enc)
        print(
            f"sprites: cell {spec.cell_w}x{spec.cell_h}, full x{spec.scale_full} "
            f"({spec.cell_w * spec.scale_full}x{spec.cell_h * spec.scale_full}), "
            f"mini x{spec.scale_mini}; {enc.cf}, {fb:,} bytes a frame"
        )
        print(
            f"  {len(result.table) - len(result.fallbacks)} animations drawn, "
            f"{len(result.fallbacks)} borrowed from default; {len(result.images)} unique frames, "
            f"{result.data_bytes:,} bytes"
        )
        est = sprites.estimate_full_set(spec)
        print(f"  a full set (9 poses x 6 outfits x 4 frames): ~{est / 1024:,.0f} KiB of flash")
        missing = [
            f"{p}/{o}" for p in manifest.POSES for o in manifest.OUTFITS
            if (p, o) not in result.table
        ]  # fmt: skip
        if missing:
            print(f"  gray placeholder for {len(missing)} pose/outfits: {', '.join(missing)}")
    if m.fonts:
        for face in m.fonts.faces:
            fonts.check_coverage(face)
            syms = fonts.symbols_for(face, UI_DIR)
            print(
                f"font {face.name}: {face.file.name} at {', '.join(map(str, face.sizes))} px, "
                f"symbols {' '.join(syms) or 'none'}"
            )
    return 0


def cmd_dummy(args: argparse.Namespace) -> int:
    path = Path(args.out)
    dummy.write_sheet(path)
    print(f"wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="charm-assets", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def gen(name: str, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.add_argument("manifest")
        p.add_argument("--out-dir", default=str(UI_DIR), help="default: the repo's ui/")
        p.add_argument(
            "--check", action="store_true", help="exit 1 if the generated files are out of date"
        )
        return p

    gen("sprites", "sheets -> charm_assets_sprites.{h,cpp}").set_defaults(fn=cmd_sprites)
    fp = gen("fonts", "fonts -> charm_assets_fonts.{h,cpp} (needs npx)")
    fp.add_argument("--no-ui-scan", action="store_true", help="don't add the LV_SYMBOL_s ui/ uses")
    fp.set_defaults(fn=cmd_fonts)
    cp = sub.add_parser("check", help="validate a manifest; palette + flash report")
    cp.add_argument("manifest")
    cp.set_defaults(fn=cmd_check)
    dp = sub.add_parser("dummy", help="write the dummy test sheet")
    dp.add_argument("--out", default=str(TOOLS_DIR / "fixtures/dummy/dummy-sheet.png"))
    dp.set_defaults(fn=cmd_dummy)

    args = ap.parse_args(argv)
    try:
        rc: int = args.fn(args)
    except manifest.ManifestError as e:
        print(f"charm-assets: {e}", file=sys.stderr)
        return 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
