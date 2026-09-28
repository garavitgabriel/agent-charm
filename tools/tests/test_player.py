"""Builds tools/player_check against the sim's libraries and runs it: the real ui/dex_sprite.cpp
playing (1) the dummy pixel-art frames, generated into a temp dir, and (2) the committed smooth Dex.
Skipped until the sim is built (`cmake --build build/sim`)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import DUMMY_MANIFEST, REPO, TOOLS

from charm_assets import cli

BUILD = REPO / "build/sim"
LIBS = [BUILD / "libsim_core.a", BUILD / "libcharm_ui.a", BUILD / "liblvgl.a"]
LVGL = BUILD / "_deps/lvgl-src"

needs_sim = pytest.mark.skipif(
    not all(p.exists() for p in [*LIBS, LVGL]) or shutil.which("c++") is None,
    reason="needs the sim built: cmake -S sim -B build/sim && cmake --build build/sim",
)


def _build(exe: Path, sources: list[Path], include_first: list[Path]) -> None:
    subprocess.run(
        [
            "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-DLV_CONF_INCLUDE_SIMPLE",
            *(f"-I{p}" for p in include_first),
            f"-I{REPO / 'ui'}", f"-I{REPO / 'sim/src'}", f"-isystem{LVGL}",
            *map(str, sources), *map(str, LIBS), "-lz", "-o", str(exe),
        ],
        check=True,
    )  # fmt: skip


@needs_sim
def test_dex_player_animates(tmp_path: Path) -> None:
    # The committed table is the smooth Dex, so the pixel-art player is checked against the dummy
    # sheet: its table is generated into tmp_path, next to a copy of the real ui/dex_sprite.cpp
    # (so the quoted include resolves to the dummy header). These objects come first on the link
    # line; the linker then never pulls the committed ones out of libcharm_ui.a.
    gen = tmp_path / "dummy_ui"
    assert cli.main(["sprites", str(DUMMY_MANIFEST), "--out-dir", str(gen)]) == 0
    for name in ("dex_sprite.cpp", "dex_sprite.h"):
        shutil.copy(REPO / "ui" / name, gen / name)
    exe = tmp_path / "check_dex_player"
    _build(
        exe,
        [
            TOOLS / "player_check/check_dex_player.cpp",
            gen / "dex_sprite.cpp",
            gen / "charm_assets_sprites.cpp",
        ],
        [gen],
    )
    shots = tmp_path / "shots"
    proc = subprocess.run([str(exe), str(shots)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 failure(s)" in proc.stdout
    assert (shots / "idle-f0.png").exists() and (shots / "mini-f1.png").exists()
    assert (shots / "coach-placeholder.png").exists()


@needs_sim
def test_smooth_dex_player(tmp_path: Path) -> None:
    exe = tmp_path / "check_dex_smooth"
    _build(exe, [TOOLS / "player_check/check_dex_smooth.cpp"], [])
    shots = tmp_path / "shots"
    proc = subprocess.run([str(exe), str(shots)], capture_output=True, text=True, check=False)
    print(proc.stdout)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 failure(s)" in proc.stdout
    assert (shots / "lift-held.png").exists() and (shots / "reading-idle.png").exists()
    for name in ("idle", "listening", "working", "speaking", "placeholder"):
        assert (shots / f"coach-{name}.png").exists(), name
