"""The smooth Dex: design export, the rgb565 manifest, LZ4 frames, budget and strips."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from conftest import DESIGN_SRC, DEX_DIR, DEX_MANIFEST, REPO
from PIL import Image

from charm_assets import cli, dex_export, manifest, smooth
from charm_assets.manifest import ManifestError


def test_export_reproduces_the_committed_frames(tmp_path: Path) -> None:
    """One command re-creates ui/assets-src/dex byte for byte, and writes nothing into docs/."""
    before = sorted(p for p in DESIGN_SRC.parent.rglob("*") if p.is_file())
    out = tmp_path / "dex"
    assert cli.main(["export-dex", "--out", str(out)]) == 0
    assert sorted(p for p in DESIGN_SRC.parent.rglob("*") if p.is_file()) == before
    assert (out / "manifest.json").read_bytes() == DEX_MANIFEST.read_bytes()
    made = sorted(p.name for p in (out / "frames").iterdir())
    assert made == sorted(p.name for p in (DEX_DIR / "frames").iterdir())
    for name in made:
        assert (out / "frames" / name).read_bytes() == (DEX_DIR / "frames" / name).read_bytes(), (
            name
        )


def test_every_pose_has_frames_at_the_design_geometry() -> None:
    m = manifest.load(DEX_MANIFEST)
    spec = m.sprites
    assert isinstance(spec, manifest.SmoothSpec)
    # The hip lands on the design anchor, never scaled; the cell stays out of the content zone.
    assert spec.screen_anchor == (236, 379)
    top = spec.screen_anchor[1] - spec.anchor[1]
    assert top >= 214 and top + spec.cell_h <= 448
    assert spec.cell_w == 192
    drawn = {(a.pose, a.outfit) for a in spec.animations}
    assert {p for p, o in drawn if o == "default"} == set(manifest.POSES)
    assert {("idle", "reading"), ("speaking", "reading"), ("done", "reading")} <= drawn
    # Every frame is an opaque cell-sized PNG, and its points sit inside the cell.
    for f in spec.frames.values():
        with Image.open(f.file) as im:
            assert im.size == (spec.cell_w, spec.cell_h) and im.mode == "RGB", f.name
        assert "hand" in f.points, f.name
    # The bag moves chest -> overhead through the lift.
    lift = next(a for a in spec.animations if a.pose == "lift_bag")
    offer = next(a for a in spec.animations if a.pose == "offer_bag")
    chest = spec.frames[offer.frames[0][0]].points["bag"]
    over = spec.frames[lift.frames[lift.loop_from][0]].points["bag"]
    assert over[1] < chest[1] - 60
    assert lift.exit is not None and lift.exit_to == "offer_bag"


def test_motion_timing_follows_motion_md() -> None:
    spec = manifest.load(DEX_MANIFEST).sprites
    assert isinstance(spec, manifest.SmoothSpec)
    mo = spec.motion
    assert mo.tick_ms == 40
    assert sum(mo.breath["day"]) == 4000 and sum(mo.breath["night"]) == 6000
    assert (mo.blink_half_ms, mo.blink_closed_ms, mo.blink_every_ms) == (60, 90, (3000, 6000))
    assert (mo.blink_double_every, mo.blink_double_gap_ms) == (5, 150)
    anims = {(a.pose, a.outfit): a for a in spec.animations}
    idle = anims[("idle", "default")]
    assert [ms for _, ms in idle.frames] == [250, 250, 250]  # steam
    assert idle.sip and [ms for _, ms in idle.sip.frames] == [400, 1200, 400]
    lift = anims[("lift_bag", "default")]
    assert [ms for _, ms in lift.frames[:3]] == [100, 100, 200] and lift.breath == "none"
    assert [ms for _, ms in anims[("done", "default")].frames] == [120] * 4
    assert anims[("asleep", "default")].breath == "night"
    assert [ms for _, ms in anims[("asleep", "default")].frames] == [400] * 3


def test_lz4_and_rgb565_round_trip() -> None:
    im = Image.new("RGB", (8, 4), (0, 0, 0))
    im.putpixel((1, 1), (0xF2, 0xC1, 0x4E))
    raw = smooth.rgb565(im)
    assert raw[2 * 9 : 2 * 9 + 2] == bytes((0x09, 0xF6))  # 0xF609 little-endian
    z = smooth.lz4_compress(raw)
    assert smooth.lz4_decompress(z, len(raw)) == raw
    back = smooth.from_rgb565(raw, 8, 4)
    assert back.getpixel((1, 1)) == (0xF7, 0xC3, 0x4A)  # what the panel shows
    assert smooth.fnv1a16(b"") == 2166136261


def _unrle16(data: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(data):
        n = (data[i] & 0x7F) + 1
        if data[i] & 0x80:
            out += data[i + 1 : i + 3] * n
            i += 3
        else:
            out += data[i + 1 : i + 1 + 2 * n]
            i += 1 + 2 * n
    return bytes(out)


def test_rle16_measured_in_the_budget_is_lossless() -> None:
    spec = manifest.load(DEX_MANIFEST).sprites
    assert isinstance(spec, manifest.SmoothSpec)
    raw = smooth.rgb565(smooth.load_frame(spec, "idle-s0"))
    assert _unrle16(smooth.rle16(raw)) == raw
    assert len(smooth.lz4_compress(raw)) < len(smooth.rle16(raw))  # why LZ4 was picked


def test_build_dedupes_shares_and_falls_back() -> None:
    spec = manifest.load(DEX_MANIFEST).sprites
    assert isinstance(spec, manifest.SmoothSpec)
    r = smooth.build(spec)
    # attention plays show_phone's frames: stored once.
    assert r.table[("attention", "default")].images() == r.table[("show_phone", "default")].images()
    # A pose the reading design doesn't draw borrows the default frames.
    assert r.table[("working", "reading")] is r.table[("working", "default")]
    assert r.table[("idle", "reading")] is not r.table[("idle", "default")]
    assert "reading-shh" in r.unplayed
    for im in r.images:
        assert smooth.lz4_decompress(im.lz4, len(im.raw)) == im.raw
        assert smooth.fnv1a16(im.raw) == im.fnv
    h, c = smooth.render(spec, r, "sprites x", ["x"])
    assert h.startswith("// GENERATED — do not edit.") and "#define CHARM_SPRITE_SMOOTH 1" in h
    assert smooth.render(spec, smooth.build(spec), "sprites x", ["x"]) == (h, c)


def test_budget_and_strips(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["budget", str(DEX_MANIFEST), "--firmware-bin", str(tmp_path / "none")]) == 0
    text = capsys.readouterr().out
    assert "RLE16" in text and "LZ4-HC" in text and "6.25 MiB" in text
    assert "idle/reading" in text and "total" in text
    assert cli.main(["strips", str(DEX_MANIFEST), "--out", str(tmp_path / "strips")]) == 0
    strips = {p.name for p in (tmp_path / "strips").iterdir()}
    assert {"lift_bag-default.png", "idle-reading.png", "asleep-default.png"} <= strips


# ---------------------------------------------------------------- manifest validation


def _smooth_manifest(tmp_path: Path, **over: Any) -> Path:
    raw = json.loads(DEX_MANIFEST.read_text())
    sp = raw["sprites"]
    shutil.copy(DEX_DIR / "frames/idle-s0.png", tmp_path / "a.png")
    sp["frames"] = {"a": {"file": "a.png", "points": {"hand": [1, 1, 4, 4]}}}
    sp["animations"] = [{"pose": "idle", "frames": [{"frame": "a", "ms": 100}]}]
    sp.update(over)
    p = tmp_path / "m.json"
    p.write_text(json.dumps(raw))
    return p


def test_smooth_manifest_loads_and_builds(tmp_path: Path) -> None:
    spec = manifest.load(_smooth_manifest(tmp_path)).sprites
    assert isinstance(spec, manifest.SmoothSpec)
    r = smooth.build(spec)
    assert len(r.images) == 1 and r.table[("idle", "cat")] is r.table[("idle", "default")]


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"format": "jpeg"}, "sprites.format"),
        ({"scale": {"full": 1, "mini": 1}}, "never scaled"),
        ({"compression": "rle"}, "compression"),
        ({"anchor": [500, 10]}, "anchor"),
        ({"mini_origin": [150, 0]}, "mini crop"),
        ({"animations": [{"pose": "idle", "frames": [{"frame": "zz", "ms": 100}]}]}, "zz"),
        (
            {
                "animations": [
                    {"pose": "idle", "frames": [{"frame": "a", "ms": 100}], "loop_from": 1}
                ]
            },
            "loop_from",
        ),
        (
            {"animations": [{"pose": "idle", "frames": [{"frame": "a", "ms": 100}], "blink": []}]},
            "blink",
        ),
        (
            {
                "animations": [
                    {
                        "pose": "idle",
                        "frames": [{"frame": "a", "ms": 100}],
                        "exit": {"to": "idle", "frames": [{"frame": "a", "ms": 100}]},
                    }
                ]
            },
            "exit",
        ),
        (
            {
                "animations": [
                    {"pose": "idle", "frames": [{"frame": "a", "ms": 100}], "breath": "x"}
                ]
            },
            "breath",
        ),
        ({"frames": {"a": {"file": "a.png", "points": {"hand": [180, 0, 40, 4]}}}}, "inside"),
        ({"frames": {"a": {"file": "a.png", "points": {"elbow": [1, 1, 4, 4]}}}}, "elbow"),
        ({"motion": {"tick_ms": 40}}, "breath"),
    ],
)
def test_bad_smooth_manifests_say_what_is_wrong(
    tmp_path: Path, over: dict[str, Any], message: str
) -> None:
    with pytest.raises(ManifestError, match=message):
        manifest.load(_smooth_manifest(tmp_path, **over))


def test_frames_must_be_opaque_and_cell_sized(tmp_path: Path) -> None:
    p = _smooth_manifest(tmp_path)
    Image.new("RGBA", (192, 224), (0, 0, 0, 0)).save(tmp_path / "a.png")
    spec = manifest.load(p).sprites
    assert isinstance(spec, manifest.SmoothSpec)
    with pytest.raises(ManifestError, match="opaque"):
        smooth.build(spec)
    Image.new("RGB", (100, 100)).save(tmp_path / "a.png")
    with pytest.raises(ManifestError, match="the cell is 192x224"):
        smooth.build(spec)


def test_export_refuses_a_frame_outside_the_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exporter crops nothing: a pixel of Dex outside the cell fails the export."""
    monkeypatch.setattr(dex_export, "CELL_ORIGIN", (160, 230))
    screen = Image.new("RGB", dex_export.SCREEN)
    screen.putpixel((236, 225), (255, 255, 255))
    with pytest.raises(ManifestError, match="outside the cell"):
        dex_export.cell_of(screen, "x")
    assert REPO.exists()
