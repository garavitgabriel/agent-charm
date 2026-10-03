"""`charm-assets export-pack`: character packs (pack.json + RGBA frames at 2x, format 1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import DESIGN_SRC, UI
from PIL import Image

from charm_assets import cli, dex_export, pack_export
from charm_assets.manifest import ManifestError

REQUIRED = ("idle", "listening", "working", "speaking", "attention", "done", "error", "offline")


def _export(tmp: Path, character: str) -> tuple[Path, dict[str, Any]]:
    out = tmp / character
    assert cli.main(["export-pack", "--character", character, "--out", str(out)]) == 0
    return out, json.loads((out / "pack.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dex_pack(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    return _export(tmp_path_factory.mktemp("packs"), "dex")


@pytest.fixture(scope="module")
def coach_pack(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    return _export(tmp_path_factory.mktemp("packs"), "coach")


def _referenced(pack: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for a in pack["animations"]:
        names |= {f["frame"] for f in a["frames"]}
        names |= {x for pair in a.get("blink", []) for x in pair}
        names |= {f["frame"] for f in a.get("sip", [])}
        names |= {f["frame"] for f in a.get("exit", {}).get("frames", [])}
    return names


@pytest.mark.parametrize("which", ["dex_pack", "coach_pack"])
def test_pack_is_format_1_at_2x_rgba_transparent(
    which: str, request: pytest.FixtureRequest
) -> None:
    out, pack = request.getfixturevalue(which)
    assert pack["format"] == 1
    assert pack["id"] == out.name
    assert pack["cell"] == [384, 448]
    assert pack["anchor"] == [dex_export.CELL_ANCHOR[0] * 2, dex_export.CELL_ANCHOR[1] * 2]
    assert pack["producer"] == "svg-export"
    assert "placeholder" not in pack["version"]
    poses = {a["pose"] for a in pack["animations"] if a["outfit"] == "default"}
    assert set(REQUIRED) <= poses
    on_disk = {p.stem for p in (out / "frames").glob("*.png")}
    assert on_disk == _referenced(pack), "no missing frames and no orphans"
    assert len(on_disk) <= 160
    assert sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) <= 6 * 1024 * 1024
    for name in sorted(on_disk):
        with Image.open(out / "frames" / f"{name}.png") as im:
            assert im.mode == "RGBA", name
            assert im.size == (384, 448), name
            alpha = im.getchannel("A")
            # Transparent ground: every corner is empty, and Dex/Coach is there.
            for xy in ((0, 0), (383, 0), (0, 447), (383, 447)):
                assert alpha.getpixel(xy) == 0, (name, xy)
            assert alpha.getbbox() is not None, name
    for a in pack["animations"]:
        if "blink" in a:
            assert len(a["blink"]) == len(a["frames"])
        assert a["breath"] in ("day", "night", "none")


def test_no_ground_shadow_is_baked(dex_pack: tuple[Path, dict[str, Any]]) -> None:
    """The charm's floor ellipse (screen y 433 +/- 7) is the app's to draw: below Dex's shoes the
    cell is empty."""
    out, _ = dex_pack
    with Image.open(out / "frames/idle-s0.png") as im:
        floor_y = (dex_export.SCREEN_ANCHOR[1] + 54 - dex_export.CELL_ORIGIN[1]) * 2
        band = im.getchannel("A").crop((0, floor_y + 16, 384, 448))
        assert band.getbbox() is None


def test_dex_pack_matches_the_charm_manifest(dex_pack: tuple[Path, dict[str, Any]]) -> None:
    """Same poses, frames, blinks, sips, exits and timing as export-dex, minus review-only
    frames."""
    _, pack = dex_pack
    d = dex_export.load_design(DESIGN_SRC)
    fs = dex_export.frame_set(d)
    want = [
        (a.pose, a.outfit, [list(f) for f in a.frames], a.loop_from, a.breath) for a in fs.anims
    ]
    got = [
        (
            a["pose"],
            a["outfit"],
            [[f["frame"], f["ms"]] for f in a["frames"]],
            a.get("loop_from", 0),
            a["breath"],
        )
        for a in pack["animations"]
    ]
    assert got == want
    lift = next(a for a in pack["animations"] if a["pose"] == "lift_bag")
    assert lift["exit"]["to"] == "offer_bag"
    assert not set(fs.unplayed) & _referenced(pack)


def test_dex_pack_frame_is_the_1x_frame_at_2x(dex_pack: tuple[Path, dict[str, Any]]) -> None:
    """Downscaled to 1x and put on #000, a pack frame is the charm's frame minus its ground
    shadow (same framing, same art)."""
    out, _ = dex_pack
    d = dex_export.load_design(DESIGN_SRC)
    fs = dex_export.frame_set(d)
    one_x = dex_export.cell_of(dex_export.render_screen(d, fs.frames["speaking-0"]), "speaking-0")
    with Image.open(out / "frames/speaking-0.png") as im:
        small = im.resize(dex_export.CELL, Image.Resampling.LANCZOS)
    flat = Image.new("RGB", dex_export.CELL, (0, 0, 0))
    flat.paste(small, mask=small.getchannel("A"))
    a, b = one_x.crop((0, 0, 192, 200)), flat.crop((0, 0, 192, 200))  # above the shadow
    diff = sum(
        abs(x - y)
        for p, q in zip(a.getdata(), b.getdata(), strict=True)
        for x, y in zip(p, q, strict=True)
    )
    assert diff / (192 * 200 * 3) < 6  # mean channel error: resampling only


def test_coach_pack_is_vector_with_blinks_and_glance(
    coach_pack: tuple[Path, dict[str, Any]],
) -> None:
    _, pack = coach_pack
    by = {a["pose"]: a for a in pack["animations"]}
    assert set(by) == {
        "idle", "listening", "working", "speaking", "attention", "done", "ask_yes", "asleep",
        "offline", "error",
    }  # fmt: skip
    assert by["idle"]["blink"] == [[f"idle-{i}-half", f"idle-{i}-closed"] for i in range(3)]
    assert by["idle"]["sip"] == [{"frame": "idle-glance", "ms": 1200}]
    assert by["asleep"]["breath"] == "night"
    assert "blink" not in by["working"]  # head down over the tablet: the design doesn't blink it
    assert by["done"]["loop_from"] == 3
    assert [f["ms"] for f in by["speaking"]["frames"]] == [200, 200]  # Dex's timing


def test_coach_blink_differs_only_at_the_eyes(coach_pack: tuple[Path, dict[str, Any]]) -> None:
    from PIL import ImageChops

    out, _ = coach_pack
    with (
        Image.open(out / "frames/idle-1.png") as base,
        Image.open(out / "frames/idle-1-closed.png") as closed,
    ):
        box = ImageChops.difference(base, closed).getbbox(alpha_only=False)
    assert box is not None
    assert box[2] - box[0] < 120 and box[3] - box[1] < 60, box  # a face-sized box, not the body


def test_export_pack_never_writes_ui(tmp_path: Path) -> None:
    before = {p: p.stat().st_mtime_ns for p in (UI / "assets-src").rglob("*") if p.is_file()}
    _export(tmp_path, "coach")
    after = {p: p.stat().st_mtime_ns for p in (UI / "assets-src").rglob("*") if p.is_file()}
    assert before == after


def test_reexport_removes_stale_frames_and_keeps_voice_hint(tmp_path: Path) -> None:
    out = tmp_path / "coach"
    (out / "frames").mkdir(parents=True)
    (out / "frames/old-placeholder.png").write_bytes(b"x")
    (out / "pack.json").write_text(json.dumps({"voice_hint": "voice-123"}))
    _, pack = _export(tmp_path, "coach")
    assert not (out / "frames/old-placeholder.png").exists()
    assert pack["voice_hint"] == "voice-123"


def test_a_render_outside_the_cell_fails() -> None:
    far = '<rect x="0" y="0" width="20" height="20" fill="#fff"/>'
    with pytest.raises(ManifestError, match="outside the 2x cell"):
        pack_export.render_cell(pack_export.svg_doc(far), "far")


def test_unknown_character_fails(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="unknown character"):
        pack_export.export("nobody", DESIGN_SRC, tmp_path / "x", "test")
