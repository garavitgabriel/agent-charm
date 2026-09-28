"""The character dimension (dex, coach): manifests, tables, the Coach export and the dummy card."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import DEX_DIR, DEX_MANIFEST, UI, base_sprites
from PIL import Image

from charm_assets import cli, coach, manifest, smooth, sprites
from charm_assets.manifest import ManifestError

Writer = Callable[..., Path]
COACH_DIR = UI / "assets-src/coach"
COACH_MANIFEST = COACH_DIR / "manifest.json"


def test_character_order_matches_dex_sprite_h() -> None:
    header = (UI / "dex_sprite.h").read_text()
    body = re.search(r"enum dex_character_t \{(.*?)\};", header, re.S)
    assert body
    text = re.sub(r"//[^\n]*", "", body.group(1))
    items = [i.lower() for i in re.findall(r"\bDEX_CHARACTER_([A-Z_]+)\b", text) if i != "COUNT"]
    assert items == list(manifest.CHARACTERS)
    # The player's names match too (dex_character_name / dex_character_from_agent).
    player = (UI / "dex_sprite.cpp").read_text()
    names = re.search(r"CHARACTER_NAMES\[DEX_CHARACTER_COUNT\] = \{(.*?)\};", player, re.S)
    assert names and re.findall(r'"(\w+)"', names.group(1)) == list(manifest.CHARACTERS)


# ---------------------------------------------------------------- indexed sheets


def test_indexed_character_never_borrows_another_characters_frames(write_manifest: Writer) -> None:
    anims = [
        {"pose": "idle", "row": 0, "frames": [{"col": 0, "ms": 100}]},
        {"pose": "working", "row": 1, "frames": [{"col": 0, "ms": 100}]},
        {"character": "coach", "pose": "idle", "row": 2, "frames": [{"col": 1, "ms": 100}]},
    ]
    m = manifest.load(write_manifest(sprites=base_sprites(animations=anims)))
    assert isinstance(m.sprites, manifest.SpriteSpec)
    r = sprites.build(m.sprites)
    assert ("idle", "default") in r.tables["coach"]
    assert r.tables["coach"][("idle", "default")] != r.table[("idle", "default")]
    assert r.tables["coach"][("idle", "food")] is r.tables["coach"][("idle", "default")]
    assert ("working", "default") not in r.tables["coach"]  # Dex has it; Coach gets the placeholder
    h, c = sprites.render(m.sprites, r, "sprites x", ["x"])
    assert "#define CHARM_SPRITE_CHARACTERS 2" in h
    assert "[CHARM_SPRITE_CHARACTERS][CHARM_SPRITE_POSES][CHARM_SPRITE_OUTFITS]" in h
    coach_block = c[c.index("/* coach */") :]
    assert "coach_idle_default" in coach_block and "working_default" not in coach_block


@pytest.mark.parametrize(
    ("anims", "message"),
    [
        ([{"character": "beard", "pose": "idle", "frames": [{"col": 0, "ms": 100}]}], "beard"),
        (
            [
                {"character": "coach", "pose": "idle", "frames": [{"col": 0, "ms": 100}]},
                {"character": "coach", "pose": "idle", "frames": [{"col": 1, "ms": 100}]},
            ],
            "coach idle/default is listed twice",
        ),
    ],
)
def test_bad_characters_say_what_is_wrong(
    write_manifest: Writer, anims: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(ManifestError, match=message):
        manifest.load(write_manifest(sprites=base_sprites(animations=anims)))


# ---------------------------------------------------------------- smooth: character manifests


def _pair_of_manifests(tmp_path: Path, **coach_over: Any) -> Path:
    """tmp/dex/manifest.json (one Dex frame) + tmp/coach/manifest.json (one Coach frame)."""
    dex = tmp_path / "dex"
    dex.mkdir()
    raw = json.loads(DEX_MANIFEST.read_text())
    sp = raw["sprites"]
    shutil.copy(DEX_DIR / "frames/idle-s0.png", dex / "a.png")
    sp["frames"] = {"a": {"file": "a.png", "points": {"hand": [1, 1, 4, 4]}}}
    sp["animations"] = [
        {"pose": "idle", "frames": [{"frame": "a", "ms": 100}]},
        {"pose": "working", "frames": [{"frame": "a", "ms": 100}]},
    ]
    (dex / "manifest.json").write_text(json.dumps(raw))
    c = tmp_path / "coach"
    c.mkdir()
    coach.dummy_frame("idle", 0).save(c / "b.png")
    csp: dict[str, Any] = {
        "format": "rgb565",
        "character": "coach",
        "cell": [192, 224],
        "anchor": list(sp["anchor"]),
        "frames": {"b": {"file": "b.png"}},
        "animations": [{"pose": "idle", "frames": [{"frame": "b", "ms": 250}]}],
    }
    csp.update(coach_over)
    (c / "manifest.json").write_text(json.dumps({"version": 1, "sprites": csp}))
    return dex / "manifest.json"


def test_coach_manifest_next_to_dex_is_compiled_without_borrowing(tmp_path: Path) -> None:
    spec = manifest.load(_pair_of_manifests(tmp_path)).sprites
    assert isinstance(spec, manifest.SmoothSpec)
    assert [o.name for o in spec.others] == ["coach"]
    r = smooth.build(spec)
    ct = r.characters["coach"].table
    assert ct[("idle", "default")].images() != r.table[("idle", "default")].images()
    assert ct[("idle", "reading")] is ct[("idle", "default")]  # Coach's own default outfit
    assert ("working", "default") in r.table and ("working", "default") not in ct
    h, c = smooth.render(spec, r, "sprites x", ["x"])
    assert "#define CHARM_SPRITE_CHARACTERS 2  // dex, coach" in h
    assert "// Coach: 1 pose/outfit animations drawn" in h
    coach_block = c[c.index("  /* coach */") :]
    assert "coach_idle_default" in coach_block
    assert "working_default" not in coach_block  # a placeholder entry, never Dex's working
    assert coach_block.count("// default: placeholder") == len(manifest.POSES) - 1
    assert smooth.render(spec, smooth.build(spec), "sprites x", ["x"]) == (h, c)


def test_no_coach_manifest_means_every_coach_pose_is_the_placeholder(tmp_path: Path) -> None:
    p = _pair_of_manifests(tmp_path)
    shutil.rmtree(tmp_path / "coach")
    spec = manifest.load(p).sprites
    assert isinstance(spec, manifest.SmoothSpec) and spec.others == ()
    r = smooth.build(spec)
    assert r.characters["coach"].table == {}
    _, c = smooth.render(spec, r, "sprites x", ["x"])
    assert "coach_" not in c


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"anchor": [70, 161]}, "same anchor"),
        ({"cell": [192, 192]}, "same anchor"),
        ({"motion": {}}, "sprites.motion comes from Dex"),
        ({"character": "dex"}, '"character": "coach"'),
        ({"animations": [{"pose": "idle", "frames": [{"frame": "zz", "ms": 250}]}]}, "zz"),
    ],
)
def test_bad_character_manifests_say_what_is_wrong(
    tmp_path: Path, over: dict[str, Any], message: str
) -> None:
    with pytest.raises(ManifestError, match=message):
        manifest.load(_pair_of_manifests(tmp_path, **over))


def test_a_character_manifest_is_compiled_through_dexs(tmp_path: Path) -> None:
    _pair_of_manifests(tmp_path)
    with pytest.raises(ManifestError, match="compile it through Dex's"):
        manifest.load(tmp_path / "coach/manifest.json")


# ---------------------------------------------------------------- the committed Coach (real)

DESIGN_COACH = UI.parent / "docs/design/final/coach"
# The poses the design draws (coach.md § Poses and frames); the rest stay on the placeholder.
COACH_POSES = {
    "idle": 3,
    "listening": 2,
    "working": 2,
    "speaking": 2,
    "attention": 1,
    "done": 4,
    "ask_yes": 1,
    "asleep": 3,
    "offline": 1,
    "error": 1,
}


def test_committed_coach_is_the_real_export(tmp_path: Path) -> None:
    """ui/assets-src/coach is exactly `charm-assets export-coach docs/design/final/coach/frames`
    (+ frames-extra): the design's Coach, not the dummy, covering every pose the design draws, with
    his blinks and the idle glance."""
    shutil.copytree(DEX_DIR, tmp_path / "dex", ignore=shutil.ignore_patterns("frames"))
    out = tmp_path / "coach"
    src = DESIGN_COACH / "frames"
    assert cli.main(["export-coach", str(src), "--out", str(out), "--no-compile"]) == 0
    made = json.loads((out / "manifest.json").read_text())
    committed = json.loads(COACH_MANIFEST.read_text())
    made.pop("_generated")
    committed.pop("_generated")
    assert made == committed
    names = sorted(p.name for p in (out / "frames").iterdir())
    assert names == sorted(p.name for p in (COACH_DIR / "frames").iterdir())
    for name in names:
        assert (out / "frames" / name).read_bytes() == (COACH_DIR / "frames" / name).read_bytes()
    # The design's pixels, untouched: every frame is the design's render (cells on #000).
    for p in src.glob("*.png"):
        with Image.open(p) as a, Image.open(COACH_DIR / "frames" / p.name) as b:
            assert a.convert("RGB").tobytes() == b.convert("RGB").tobytes()
    spec = manifest.load(DEX_MANIFEST).sprites
    assert isinstance(spec, manifest.SmoothSpec)
    (c,) = spec.others
    got = {a.pose: len(a.frames) for a in c.animations if a.outfit == "default"}
    assert got == COACH_POSES
    anims = {a.pose: a for a in c.animations}
    for pose in ("idle", "listening", "speaking", "attention", "ask_yes", "offline", "error"):
        assert anims[pose].blink, pose  # every open-eyed pose blinks
    for pose in ("working", "done", "asleep"):
        assert anims[pose].blink is None, pose  # eyes down, creased or shut: no blink art
    assert anims["idle"].sip is not None  # the glance, in Dex's sip slot
    # Nothing of the dummy is left.
    assert all("dummy" not in n for n in names)
    for p in (COACH_DIR / "frames").glob("*.png"):
        with Image.open(p) as im:
            colors = {col for _, col in im.convert("RGB").getcolors(1 << 18) or []}
        assert coach.NAVY not in colors or coach.ORANGE not in colors


def test_export_coach_takes_blinks_and_the_glance(tmp_path: Path) -> None:
    """frames-extra/ naming: <frame>-half|closed.png and idle-glance[-n].png, next to SRC or in it.
    A frame without its own pair borrows a sibling's eyelids only when the faces match."""
    src, out = _export_env(tmp_path)
    base = coach.dummy_frame("idle", 0)
    base.save(src / "idle-0.png")
    swing = base.copy()
    swing.paste((200, 200, 200), (70, 180, 80, 190))  # differs away from the eyes
    swing.save(src / "idle-1.png")
    half, closed = base.copy(), base.copy()
    half.paste((1, 2, 3), (60, 60, 90, 66))
    closed.paste((4, 5, 6), (60, 60, 90, 70))
    extra = tmp_path / "frames-extra"
    extra.mkdir()
    half.save(extra / "idle-0-half.png")
    closed.save(extra / "idle-0-closed.png")
    coach.dummy_frame("idle", 1).save(extra / "idle-glance.png")
    coach.dummy_frame("speaking", 0).save(src / "speaking-0.png")
    coach.dummy_frame("speaking", 1).save(src / "speaking-1.png")
    coach.dummy_frame("speaking", 0).save(src / "speaking-0-half.png")  # only frame 0: no blink
    coach.dummy_frame("speaking", 0).save(src / "speaking-0-closed.png")
    assert cli.main(["export-coach", str(src), "--out", str(out), "--no-compile"]) == 0
    raw = json.loads((out / "manifest.json").read_text())["sprites"]
    anims = {a["pose"]: a for a in raw["animations"]}
    assert anims["idle"]["blink"] == [
        ["idle-0-half", "idle-0-closed"],
        ["idle-1-half", "idle-1-closed"],
    ]
    assert [f["frame"] for f in anims["idle"]["sip"]] == ["idle-glance-0"]
    assert "blink" not in anims["speaking"]  # speaking-1 has no pair and a different face
    with Image.open(out / "frames/idle-1-half.png") as im:
        want = swing.copy()
        want.paste(half.crop((60, 60, 90, 70)), (60, 60))
        assert im.tobytes() == want.tobytes()


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("idle-3-half.png", "has no idle-3.png"),
        ("working-glance.png", "only idle has a glance"),
    ],
)
def test_export_coach_refuses_bad_extras(tmp_path: Path, name: str, message: str) -> None:
    src, out = _export_env(tmp_path)
    coach.dummy_frame("idle", 0).save(src / "idle-0.png")
    coach.dummy_frame("idle", 0).save(src / name)
    with pytest.raises(ManifestError, match=message):
        coach.export(src, out, "x")


def test_export_coach_wants_both_lids(tmp_path: Path) -> None:
    src, out = _export_env(tmp_path)
    coach.dummy_frame("idle", 0).save(src / "idle-0.png")
    coach.dummy_frame("idle", 0).save(src / "idle-0-half.png")
    with pytest.raises(ManifestError, match=r"both -half\.png and -closed\.png"):
        coach.export(src, out, "x")


def test_dummy_coach_is_clearly_not_coach() -> None:
    """Orange/navy test card on black, standing on Dex's anchor inside the cell."""
    for pose in coach.DUMMY_POSES:
        im = coach.dummy_frame(pose, 0)
        colors = {c for _, c in im.getcolors(1 << 16) or []}
        assert coach.ORANGE in colors and coach.NAVY in colors and (0, 0, 0) in colors
        assert im.getpixel((0, 0)) == (0, 0, 0)  # pre-composited on #000
    assert coach.dummy_frame("working", 0).tobytes() != coach.dummy_frame("working", 1).tobytes()
    assert coach.dummy_frame("idle", 0).tobytes() != coach.dummy_frame("speaking", 0).tobytes()


def test_coach_moves_with_dexs_timing() -> None:
    spec = manifest.load(DEX_MANIFEST).sprites
    assert isinstance(spec, manifest.SmoothSpec)
    dex = {(a.pose, a.outfit): a for a in spec.animations}
    for a in spec.others[0].animations:
        d = dex[(a.pose, a.outfit)]
        assert [ms for _, ms in a.frames] == [
            d.frames[min(i, len(d.frames) - 1)][1] for i in range(len(a.frames))
        ]
        assert a.breath == d.breath


# ---------------------------------------------------------------- export-coach


def _export_env(tmp_path: Path) -> tuple[Path, Path]:
    shutil.copytree(DEX_DIR, tmp_path / "dex", ignore=shutil.ignore_patterns("frames"))
    src = tmp_path / "renders"
    src.mkdir()
    return src, tmp_path / "coach"


def test_export_coach_takes_cells_screens_and_transparent_renders(tmp_path: Path) -> None:
    src, out = _export_env(tmp_path)
    coach.dummy_frame("idle", 0).save(src / "idle-0.png")
    screen = Image.new("RGBA", (368, 448), (0, 0, 0, 0))  # a transparent full-screen render
    screen.paste(coach.dummy_frame("idle", 1), (160, 218))
    screen.save(src / "idle-1.png")
    coach.dummy_frame("paper", 0).save(src / "paper-reading-0.png")
    assert cli.main(["export-coach", str(src), "--out", str(out), "--no-compile"]) == 0
    raw = json.loads((out / "manifest.json").read_text())["sprites"]
    assert sorted(raw["frames"]) == ["idle-0", "idle-1", "paper-reading-0"]
    with Image.open(out / "frames/idle-1.png") as im:
        assert im.mode == "RGB" and im.tobytes() == coach.dummy_frame("idle", 1).tobytes()
    assert [(a["pose"], a["outfit"]) for a in raw["animations"]] == [
        ("idle", "default"),
        ("paper", "reading"),
    ]
    # It loads as Coach's character manifest next to Dex's.
    dex_raw = json.loads(DEX_MANIFEST.read_text())
    (tmp_path / "dex/manifest.json").write_text(json.dumps(dex_raw))
    for f in dex_raw["sprites"]["frames"].values():
        dst = tmp_path / "dex" / f["file"]
        dst.parent.mkdir(exist_ok=True)
        shutil.copy(DEX_DIR / f["file"], dst)
    spec = manifest.load(tmp_path / "dex/manifest.json").sprites
    assert isinstance(spec, manifest.SmoothSpec) and spec.others[0].name == "coach"
    # A re-export with fewer renders drops the stale frames.
    (src / "paper-reading-0.png").unlink()
    assert cli.main(["export-coach", str(src), "--out", str(out), "--no-compile"]) == 0
    assert sorted(p.name for p in (out / "frames").iterdir()) == ["idle-0.png", "idle-1.png"]


@pytest.mark.parametrize(
    ("name", "size", "message"),
    [
        ("dancing-0.png", (192, 224), "dex_sprite.h names"),
        ("idle-hat-0.png", (192, 224), "dex_sprite.h names"),
        ("idle-1.png", (192, 224), "numbered 0..n-1"),
        ("idle-0.png", (100, 100), "renders are the 192x224 cell"),
    ],
)
def test_export_coach_refuses_bad_renders(
    tmp_path: Path, name: str, size: tuple[int, int], message: str
) -> None:
    src, out = _export_env(tmp_path)
    Image.new("RGB", size).save(src / name)
    assert cli.main(["export-coach", str(src), "--out", str(out), "--no-compile"]) == 2
    with pytest.raises(ManifestError, match=message):
        coach.export(src, out, "x")


def test_export_coach_refuses_a_render_outside_the_cell(tmp_path: Path) -> None:
    src, out = _export_env(tmp_path)
    screen = Image.new("RGB", (368, 448))
    screen.putpixel((10, 10), (255, 122, 26))
    screen.save(src / "idle-0.png")
    with pytest.raises(ManifestError, match="outside the cell"):
        coach.export(src, out, "x")


# ---------------------------------------------------------------- budget and strips


def test_budget_covers_both_characters_and_coachs_full_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["budget", str(DEX_MANIFEST), "--firmware-bin", str(tmp_path / "none")]) == 0
    text = capsys.readouterr().out
    assert "\nDex:\n" in text and "\nCoach:\n" in text
    coach_part = text[text.index("\nCoach:\n") :]
    assert "idle/default" in coach_part and "speaking/default" in coach_part
    assert "flash now (both characters)" in text
    assert f"Coach's full set, estimated: {smooth.COACH_FULL_SET} frames" in text
    assert "flash with Coach's full set" in text


def test_strips_include_the_dummy_coach(tmp_path: Path) -> None:
    assert cli.main(["strips", str(DEX_MANIFEST), "--out", str(tmp_path)]) == 0
    names = {p.name for p in tmp_path.iterdir()}
    for pose in ("idle", "listening", "working", "speaking"):
        assert f"coach-{pose}-default.png" in names
    assert "idle-default.png" in names  # Dex's strips keep their names


def test_check_reports_each_characters_placeholders(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["check", str(DEX_MANIFEST)]) == 0
    text = capsys.readouterr().out
    assert "coach: gray placeholder for" in text
    coach_line = text[text.index("coach: gray placeholder for") :].splitlines()[0]
    assert "offer_bag/default" in coach_line and "show_phone/default" in coach_line  # Dex's alone
    assert "done/default" not in coach_line  # the design's Coach draws his nod
