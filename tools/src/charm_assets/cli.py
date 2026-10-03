"""charm-assets: turn the design sprint's sprite sheets and fonts into ui/charm_assets_*.{h,cpp}."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Collection
from pathlib import Path

from . import cgen, coach, dex_export, dummy, fonts, manifest, pack_export, palette, smooth, sprites

TOOLS_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = TOOLS_DIR.parent
UI_DIR = REPO_DIR / "ui"
DEX_DIR = UI_DIR / "assets-src/dex"
COACH_DIR = UI_DIR / "assets-src/coach"
DESIGN_SRC = REPO_DIR / "docs/design/final/src"
FIRMWARE_BIN = REPO_DIR / "firmware/.pio/build/charm/firmware.bin"


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


def _smooth(m: manifest.Manifest) -> manifest.SmoothSpec:
    if not isinstance(m.sprites, manifest.SmoothSpec):
        raise manifest.ManifestError('this needs a "format": "rgb565" sprites manifest')
    return m.sprites


def cmd_sprites(args: argparse.Namespace) -> int:
    m = _load(args.manifest)
    if m.sprites is None:
        raise manifest.ManifestError("the manifest has no sprites section")
    if isinstance(m.sprites, manifest.SmoothSpec):
        sspec = m.sprites
        sres = smooth.build(sspec)
        frames = f"{len(sres.by_name)} frame PNGs (sha256 {smooth.sources_digest(sspec, sres)})"
        sources = [_source(m.path), frames]
        for other in sspec.others:
            n = len(sres.characters[other.name].by_name)
            digest = smooth.sources_digest(sspec, sres, other.name)
            label = f"{other.name}/{other.path.name}"  # beside Dex's: ui/assets-src/<name>/
            sha = hashlib.sha256(other.path.read_bytes()).hexdigest()[:16]
            sources += [f"{label} (sha256 {sha})", f"{n} {other.name} frame PNGs (sha256 {digest})"]
        h, c = smooth.render(sspec, sres, _command("sprites", m), sources)
        print(
            f"{len(sres.images)} unique frames as LZ4 RGB565, {sres.data_bytes:,} bytes compressed"
        )
        for name, cb in sres.characters.items():
            print(f"  {name}: {len(cb.drawn())} pose/outfit animations drawn")
        return _emit(Path(args.out_dir), "charm_assets_sprites", h, c, args.check)
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


def _report_missing(character: str, table: Collection[tuple[str, str]]) -> None:
    missing = [
        f"{p}/{o}" for p in manifest.POSES for o in manifest.OUTFITS if (p, o) not in table
    ]  # fmt: skip
    total = len(manifest.POSES) * len(manifest.OUTFITS)
    if len(missing) == total:
        print(f"  {character}: no frames, every pose is the gray placeholder")
    elif missing:
        print(
            f"  {character}: gray placeholder for {len(missing)} pose/outfits: {', '.join(missing)}"
        )


def cmd_check(args: argparse.Namespace) -> int:
    m = _load(args.manifest)
    if isinstance(m.sprites, manifest.SmoothSpec):
        sres = smooth.build(m.sprites)
        print(
            f"sprites: rgb565 cell {m.sprites.cell_w}x{m.sprites.cell_h}, never scaled; "
            f"{len(sres.images)} unique frames, {sres.data_bytes:,} bytes LZ4"
        )
        for name, cb in sres.characters.items():
            _report_missing(name, cb.table)
    elif m.sprites:
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
        for name, table in result.tables.items():
            _report_missing(name, table)
    if m.fonts:
        for face in m.fonts.faces:
            fonts.check_coverage(face)
            syms = fonts.symbols_for(face, UI_DIR)
            print(
                f"font {face.name}: {face.file.name} at {', '.join(map(str, face.sizes))} px, "
                f"symbols {' '.join(syms) or 'none'}"
            )
    return 0


def cmd_export_dex(args: argparse.Namespace) -> int:
    out = Path(args.out)
    m = dex_export.export(Path(args.design_src), out)
    n = len(m["sprites"]["frames"])
    print(f"exported {n} frames + manifest.json to {out}")
    return 0


def cmd_export_pack(args: argparse.Namespace) -> int:
    out = Path(args.out)
    gen = f"cd tools && uv run charm-assets export-pack --character {args.character} --out <pack>"
    p = pack_export.export(args.character, Path(args.design_src), out, gen)
    n = len(list((out / "frames").glob("*.png")))
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    anims = len(p["animations"])
    print(f"exported {p['id']}: {n} frames, {anims} animations, {size:,} bytes -> {out}")
    return 0


def _compile_with_dex(out: Path, no_compile: bool) -> int:
    dex = manifest.character_manifest(out / "manifest.json", "dex")
    if no_compile:
        print(f"now compile: cd tools && uv run charm-assets sprites {dex}")
        return 0
    return cmd_sprites(argparse.Namespace(manifest=str(dex), out_dir=str(UI_DIR), check=False))


def cmd_export_coach(args: argparse.Namespace) -> int:
    out = Path(args.out)
    m = coach.export(
        Path(args.src), out, f"cd tools && uv run charm-assets export-coach {args.src}"
    )
    n = len(m["sprites"]["frames"])
    print(f"exported {n} Coach frames + manifest.json to {out}")
    return _compile_with_dex(out, args.no_compile)


def cmd_dummy_coach(args: argparse.Namespace) -> int:
    out = Path(args.out)
    m = coach.export_dummy(out)
    n = len(m["sprites"]["frames"])
    print(f"wrote {n} dummy Coach test-card frames (NOT Coach) + manifest.json to {out}")
    return _compile_with_dex(out, args.no_compile)


def cmd_budget(args: argparse.Namespace) -> int:
    m = _load(args.manifest)
    spec = _smooth(m)
    fw = Path(args.firmware_bin) if args.firmware_bin else None
    for line in smooth.budget(spec, smooth.build(spec), fw):
        print(line)
    return 0


def cmd_strips(args: argparse.Namespace) -> int:
    m = _load(args.manifest)
    spec = _smooth(m)
    paths = smooth.strips(spec, smooth.build(spec), Path(args.out))
    print(f"wrote {len(paths)} strips to {args.out}")
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
    ep = sub.add_parser("export-dex", help="render the smooth Dex from the design source")
    ep.add_argument("--design-src", default=str(DESIGN_SRC), help="default: docs/design/final/src")
    ep.add_argument("--out", default=str(DEX_DIR), help="default: ui/assets-src/dex")
    ep.set_defaults(fn=cmd_export_dex)
    kp = sub.add_parser(
        "export-pack", help="a character pack: pack.json + RGBA frames at 2x (format 1)"
    )
    kp.add_argument("--character", required=True, choices=sorted(pack_export.CHARACTERS))
    kp.add_argument("--out", required=True, help="the pack folder, e.g. .../Characters/dex")
    kp.add_argument("--design-src", default=str(DESIGN_SRC), help="default: docs/design/final/src")
    kp.set_defaults(fn=cmd_export_pack)
    bp = sub.add_parser("budget", help="rgb565 sprites: raw/RLE/LZ4 per pose vs the app partition")
    bp.add_argument("manifest")
    bp.add_argument(
        "--firmware-bin", default=str(FIRMWARE_BIN), help="default: firmware/.pio/.../firmware.bin"
    )
    bp.set_defaults(fn=cmd_budget)
    sp = sub.add_parser("strips", help="rgb565 sprites: one PNG strip per pose for review")
    sp.add_argument("manifest")
    sp.add_argument(
        "--out", default=str(REPO_DIR / "out/dex-strips"), help="default: out/dex-strips"
    )
    sp.set_defaults(fn=cmd_strips)
    xp = sub.add_parser(
        "export-coach", help="design renders (<pose>-<n>.png) -> ui/assets-src/coach, then compile"
    )
    xp.add_argument("src", help="the folder of Coach renders, one PNG per frame")
    xp.add_argument("--out", default=str(COACH_DIR), help="default: ui/assets-src/coach")
    xp.add_argument("--no-compile", action="store_true", help="don't regenerate ui/ afterwards")
    xp.set_defaults(fn=cmd_export_coach)
    cq = sub.add_parser("dummy-coach", help="the fake orange/navy Coach test card, then compile")
    cq.add_argument("--out", default=str(COACH_DIR), help="default: ui/assets-src/coach")
    cq.add_argument("--no-compile", action="store_true", help="don't regenerate ui/ afterwards")
    cq.set_defaults(fn=cmd_dummy_coach)
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
