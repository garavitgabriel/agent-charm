"""Builds tools/player_check against the sim's libraries and runs it: the real ui/dex_sprite.cpp
playing the committed dummy frames. Skipped until the sim is built (`cmake --build build/sim`)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO, TOOLS

BUILD = REPO / "build/sim"
LIBS = [BUILD / "libsim_core.a", BUILD / "libcharm_ui.a", BUILD / "liblvgl.a"]
LVGL = BUILD / "_deps/lvgl-src"


@pytest.mark.skipif(
    not all(p.exists() for p in [*LIBS, LVGL]) or shutil.which("c++") is None,
    reason="needs the sim built: cmake -S sim -B build/sim && cmake --build build/sim",
)
def test_dex_player_animates(tmp_path: Path) -> None:
    exe = tmp_path / "check_dex_player"
    subprocess.run(
        [
            "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-DLV_CONF_INCLUDE_SIMPLE",
            f"-I{REPO / 'ui'}", f"-I{REPO / 'sim/src'}", f"-isystem{LVGL}",
            str(TOOLS / "player_check/check_dex_player.cpp"),
            *map(str, LIBS), "-lz", "-o", str(exe),
        ],
        check=True,
    )  # fmt: skip
    shots = tmp_path / "shots"
    proc = subprocess.run([str(exe), str(shots)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 failure(s)" in proc.stdout
    assert (shots / "idle-f0.png").exists() and (shots / "mini-f1.png").exists()
