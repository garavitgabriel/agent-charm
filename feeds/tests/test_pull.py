"""`charm-feeds pull` is read-only, allowlisted, and never asks for spend-pulse."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from charm_feeds import pull
from charm_feeds.sources import FEEDS, FeedSpec


class FakeRunner:
    def __init__(self, replies: dict[str, tuple[int, bytes, str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.replies = replies or {}

    def __call__(self, argv: Sequence[str]) -> tuple[int, bytes, str]:
        self.calls.append(list(argv))
        path = argv[-1]
        for name, reply in self.replies.items():
            if path.endswith(f"/{name}.json"):
                return reply
        return 0, json.dumps({"from": path}).encode(), ""


def test_allowlist_is_the_five_feeds_and_excludes_spend_pulse() -> None:
    assert [s.remote_path for s in FEEDS] == [
        "/opt/data/board/feeds/sports.json",
        "/opt/data/board/feeds/almanac.json",
        "/opt/data/board/feeds/digest.json",
        "/opt/data/board/feeds/radar.json",
        "/opt/data/board/paper-feed.json",
    ]
    assert not any("spend" in s.remote_path for s in FEEDS)


def test_every_remote_command_is_a_plain_cat(tmp_path: Path) -> None:
    runner = FakeRunner()
    pull.pull(tmp_path, runner=runner)
    assert len(runner.calls) == len(FEEDS)
    for argv, spec in zip(runner.calls, FEEDS, strict=True):
        assert argv[:6] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "hermes"]
        assert argv[6:] == ["docker", "exec", "-i", pull.DEFAULT_CONTAINER, "cat",
                            spec.remote_path]
        assert not any(word in " ".join(argv) for word in (">", "rm ", "tee", "spend"))


def test_refuses_spend_pulse_and_unlisted_paths() -> None:
    spend = FeedSpec("spend-pulse", "/opt/data/board/feeds/spend-pulse.json", "spend desk")
    with pytest.raises(ValueError, match="finance data stays on the VPS"):
        pull.remote_argv(spend, "hermes", "c")
    other = FeedSpec("other", "/opt/data/board/feeds/other.json", "other desk")
    with pytest.raises(ValueError, match="allowlist"):
        pull.remote_argv(other, "hermes", "c")


def test_success_writes_the_cache(tmp_path: Path) -> None:
    results = pull.pull(tmp_path, runner=FakeRunner())
    assert all(r.ok for r in results)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f"{s.name}.json" for s in FEEDS)


def test_failed_pull_keeps_the_previous_copy(tmp_path: Path) -> None:
    (tmp_path / "sports.json").write_text('{"old": true}', encoding="utf-8")
    runner = FakeRunner({"sports": (255, b"", "ssh: connect to host hermes: timed out")})
    results = {r.name: r for r in pull.pull(tmp_path, runner=runner)}
    assert not results["sports"].ok
    assert "timed out" in results["sports"].detail
    assert json.loads((tmp_path / "sports.json").read_text(encoding="utf-8")) == {"old": True}
    assert results["almanac"].ok


def test_non_json_reply_is_not_cached(tmp_path: Path) -> None:
    runner = FakeRunner({"digest": (0, b"<html>oops</html>", "")})
    results = {r.name: r for r in pull.pull(tmp_path, runner=runner)}
    assert not results["digest"].ok
    assert not (tmp_path / "digest.json").exists()
    assert not list(tmp_path.glob("*.tmp"))
