"""`charm-feeds pull`: copy the desk feeds from Hermes into the local cache. Read-only.

The only remote command ever run is `docker exec -i <container> cat <path>` for a path in the
`FEEDS` allowlist. Nothing is written on the VPS. `spend-pulse.json` is never requested.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from charm_feeds.sources import FEEDS, FORBIDDEN, FeedSpec

DEFAULT_ALIAS = "hermes"
DEFAULT_CONTAINER = "hermes-agent"
TIMEOUT_S = 30

# Runs argv, returns (exit code, stdout bytes, stderr text). Swapped for a fake in tests.
Runner = Callable[[Sequence[str]], tuple[int, bytes, str]]


def _subprocess_runner(argv: Sequence[str]) -> tuple[int, bytes, str]:
    try:
        done = subprocess.run(list(argv), capture_output=True, timeout=TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return 124, b"", f"timed out after {TIMEOUT_S}s"
    except OSError as exc:
        return 127, b"", str(exc)
    return done.returncode, done.stdout, done.stderr.decode("utf-8", "replace")


def remote_argv(spec: FeedSpec, alias: str, container: str) -> list[str]:
    if any(bad in spec.remote_path for bad in FORBIDDEN) or spec.name in FORBIDDEN:
        raise ValueError(f"refusing to pull {spec.remote_path}: finance data stays on the VPS")
    if spec not in FEEDS:
        raise ValueError(f"{spec.name} is not in the feed allowlist")
    return [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", alias,
        "docker", "exec", "-i", container, "cat", spec.remote_path,
    ]


@dataclass(frozen=True)
class PullResult:
    name: str
    ok: bool
    detail: str


def pull(
    cache: Path,
    alias: str = DEFAULT_ALIAS,
    container: str = DEFAULT_CONTAINER,
    runner: Runner = _subprocess_runner,
) -> list[PullResult]:
    """Pull every allowlisted feed. A failed pull leaves the previous cached copy untouched,
    so the build sees it as the old filing and labels it stale once its deadline passes."""
    cache.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in FEEDS:
        code, out, err = runner(remote_argv(spec, alias, container))
        if code != 0:
            results.append(PullResult(spec.name, False, f"exit {code}: {err.strip()[:200]}"))
            continue
        try:
            json.loads(out)
        except ValueError:
            results.append(PullResult(spec.name, False, "not valid JSON; kept the old copy"))
            continue
        target = cache / f"{spec.name}.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_bytes(out)
        os.replace(tmp, target)
        results.append(PullResult(spec.name, True, f"{len(out)} bytes"))
    return results
