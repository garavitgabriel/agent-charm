"""`charm-feeds`: pull (read-only), build and scrub."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from charm_feeds import build, pull, scrub
from charm_feeds.schema import CardError, CardValidator
from charm_feeds.text import parse_time

FEEDS_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = FEEDS_ROOT / ".cache"
DEFAULT_TZ = "America/Chicago"


def _now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = parse_time(value)
    if parsed is None:
        raise argparse.ArgumentTypeError(f"--now needs an ISO time with an offset: {value!r}")
    return parsed


def cmd_pull(args: argparse.Namespace) -> int:
    results = pull.pull(Path(args.cache), alias=args.ssh_alias, container=args.container)
    for r in results:
        print(f"{'ok  ' if r.ok else 'FAIL'} {r.name}: {r.detail}")
    return 0 if all(r.ok for r in results) else 1


def cmd_build(args: argparse.Namespace) -> int:
    now = _now(args.now)
    cards = build.build_cards(Path(args.src), now, ZoneInfo(args.tz))
    validator = CardValidator(Path(args.schema) if args.schema else None)
    try:
        build.write_cards(cards, Path(args.out), validator)
    except CardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for name, card in cards:
        flag = " (stale)" if card.get("stale") else ""
        print(f"{name}: {card['title']}{flag}")
    return 0


def cmd_scrub(args: argparse.Namespace) -> int:
    for name in scrub.scrub_dir(Path(args.src), Path(args.dst)):
        print(f"scrubbed {name}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="charm-feeds", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    pp = sub.add_parser("pull", help="copy the desk feeds from Hermes (read-only)")
    pp.add_argument("--cache", default=str(DEFAULT_CACHE))
    pp.add_argument("--ssh-alias", default=os.environ.get("HERMES_SSH_ALIAS", pull.DEFAULT_ALIAS))
    pp.add_argument(
        "--container", default=os.environ.get("HERMES_CONTAINER", pull.DEFAULT_CONTAINER)
    )
    pp.set_defaults(func=cmd_pull)

    pb = sub.add_parser("build", help="write NN-<section>.json cards")
    pb.add_argument("--out", required=True, help="output dir (usable as CHARM_CARDS_DIR)")
    pb.add_argument("--src", default=str(DEFAULT_CACHE), help="dir of pulled feeds")
    pb.add_argument("--now", help="ISO time to judge freshness at (default: now)")
    pb.add_argument("--tz", default=DEFAULT_TZ, help="zone for weekday and stamps")
    pb.add_argument("--schema", help="card schema (default: ../contract/card.schema.json)")
    pb.set_defaults(func=cmd_build)

    ps = sub.add_parser("scrub", help="scrub pulled feeds into committable fixtures")
    ps.add_argument("--src", default=str(DEFAULT_CACHE))
    ps.add_argument("--dst", required=True)
    ps.set_defaults(func=cmd_scrub)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.func(args))
    except argparse.ArgumentTypeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
