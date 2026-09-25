from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import DUMMY_MANIFEST, UI, base_sprites

from charm_assets import manifest
from charm_assets.manifest import ManifestError

Writer = Callable[..., Path]


def _enum(header: str, name: str) -> list[str]:
    body = re.search(r"enum " + name + r" \{(.*?)\};", header, re.S)
    assert body, name
    items = re.findall(r"DEX_[A-Z]+_([A-Z]+)", body.group(1))
    return [i.lower() for i in items if i != "COUNT"]


def test_pose_and_outfit_order_matches_dex_sprite_h() -> None:
    header = (UI / "dex_sprite.h").read_text()
    assert _enum(header, "dex_pose_t") == list(manifest.POSES)
    assert _enum(header, "dex_outfit_t") == list(manifest.OUTFITS)


def test_dummy_manifest_loads() -> None:
    m = manifest.load(DUMMY_MANIFEST)
    assert m.sprites and m.fonts
    assert len(m.sprites.animations) == 4
    poses = {a.pose for a in m.sprites.animations}
    assert len(poses) >= 3
    assert all(len(a.frames) >= 2 for a in m.sprites.animations)
    assert any(a.outfit != "default" for a in m.sprites.animations)


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"scale": {"full": 6, "mini": 4}}, "bigger than"),
        ({"palette": ["#FF00FF", "#ff00ff"]}, "twice"),
        ({"palette": ["#FFF"]}, "#RRGGBB"),
        ({"mini_origin": [40, 0]}, "outside the cell"),
        ({"animations": [{"pose": "dancing", "frames": [{"col": 0, "ms": 100}]}]}, "dancing"),
        (
            {"animations": [{"pose": "idle", "outfit": "hat", "frames": [{"col": 0, "ms": 1}]}]},
            "hat",
        ),
        ({"animations": [{"pose": "idle", "frames": []}]}, "1..255"),
        ({"animations": [{"pose": "idle", "frames": [{"col": 0, "ms": 5}]}]}, "ms"),
        (
            {
                "animations": [
                    {"pose": "idle", "frames": [{"col": 0, "ms": 100}]},
                    {"pose": "idle", "outfit": "default", "frames": [{"col": 1, "ms": 100}]},
                ]
            },
            "twice",
        ),
    ],
)
def test_bad_sprite_manifests_say_what_is_wrong(
    write_manifest: Writer, over: dict[str, Any], message: str
) -> None:
    with pytest.raises(ManifestError, match=message):
        manifest.load(write_manifest(sprites=base_sprites(**over)))


def test_version_is_required(tmp_path: Path) -> None:
    p = tmp_path / "m.json"
    p.write_text('{"sprites": {}}')
    with pytest.raises(ManifestError, match="version"):
        manifest.load(p)
