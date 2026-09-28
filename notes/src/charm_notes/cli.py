"""`charm-notes`: save a reading note to the vault inbox, or check the OS knowledge service.

    charm-notes save "text" [--book T] [--author A] [--chapter C] [--language L] [--dry-run]
    charm-notes check [--base URL]

`save --dry-run` prints the exact file it would submit and sends nothing. `check` never writes:
it reports whether config was found (never the token) and hits the unauthenticated /health.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from charm_notes import Book, Note
from charm_notes.osapi import (
    OsApiStore,
    check_health,
    config_search_paths,
    load_config,
    note_content,
    note_filename,
)


def _cmd_save(args: argparse.Namespace) -> int:
    book = Book(args.book, args.author, args.chapter) if args.book else None
    note = Note(args.text, datetime.now().astimezone(), args.language, book)
    if args.dry_run:
        print(f"# dry run: would POST /submit filename={note_filename(note)} agent=charm")
        print(note_content(note), end="")
        return 0
    config = load_config()
    if config is None:
        print("not saved: vault service config not found", file=sys.stderr)
        return 1
    receipt = asyncio.run(OsApiStore(config).save(note))
    if receipt.ok:
        print(f"saved: {receipt.where}")
        return 0
    print(f"not saved: {receipt.error}", file=sys.stderr)
    return 1


def _cmd_check(args: argparse.Namespace) -> int:
    config = load_config()
    if config is None:
        looked = ", ".join(["env OS_API_BASE/OS_API_TOKEN",
                            *(str(p) for p in config_search_paths())])
        print(f"config: not found (looked in: {looked})")
    else:
        print(f"config: found ({config.source}); base {config.base}; token present")
    base = args.base or (config.base if config else None)
    if base is None:
        print("health: skipped (no base URL; pass --base)")
        return 1
    ok, detail = check_health(base)
    print(f"health: {detail} ({base.rstrip('/')}/health)")
    return 0 if ok and config is not None else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="charm-notes", description="Dex Charm reading notes → vault inbox")
    sub = parser.add_subparsers(dest="cmd", required=True)
    save = sub.add_parser("save", help="save a verbatim thought to the vault inbox")
    save.add_argument("text")
    save.add_argument("--book")
    save.add_argument("--author")
    save.add_argument("--chapter")
    save.add_argument("--language", default="en")
    save.add_argument("--dry-run", action="store_true",
                      help="print the exact file that would be submitted; send nothing")
    save.set_defaults(func=_cmd_save)
    check = sub.add_parser("check", help="config found? service healthy? (writes nothing)")
    check.add_argument("--base", help="service URL for /health (default: OS_API_BASE)")
    check.set_defaults(func=_cmd_check)
    args = parser.parse_args(argv)
    if args.cmd == "save" and not args.book and (args.author or args.chapter):
        parser.error("--author/--chapter need --book")
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
