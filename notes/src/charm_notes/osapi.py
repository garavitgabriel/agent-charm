"""`OsApiStore`: a `NoteStore` that writes to the vault inbox through the OS knowledge service.

The service (`gabe-os-service`) answers `POST {base}/submit` with `{"ok": true, "path": ...}` and
writes a *new* file under `inbox/` every time, so this store never retries: a retry
after a lost reply could duplicate the note. `ok=True` only when the service returned 2xx **and** a
path. The token never appears in logs, errors, receipts or reprs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from charm_notes import Note, SaveReceipt

__all__ = [
    "DEFAULT_TIMEOUT_S",
    "OsApiConfig",
    "OsApiStore",
    "check_health",
    "config_search_paths",
    "load_config",
    "note_content",
    "note_filename",
]

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0
AGENT = "charm"
_FILENAME_WORDS = 6
_TITLE_WORDS = 8


@dataclass(frozen=True)
class OsApiConfig:
    base: str
    token: str = field(repr=False)  # never printed
    source: str  # where the config came from, e.g. "env" or a file path


def config_search_paths(env: Mapping[str, str] | None = None,
                        home: Path | None = None) -> list[Path]:
    """Config files in the order the vault's `os` CLI tries them."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    paths = []
    if env.get("OS_API_CONFIG"):
        paths.append(Path(env["OS_API_CONFIG"]).expanduser())
    paths += [home / ".os-api.env", Path("/etc/os-api.env")]
    return paths


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse the `KEY=value` lines of a shell env file (optionally `export`ed and quoted)."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, raw = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        try:
            parts = shlex.split(raw, comments=True)
        except ValueError:
            continue
        values[key] = parts[0] if parts else ""
    return values


def load_config(env: Mapping[str, str] | None = None,
                search_paths: list[Path] | None = None) -> OsApiConfig | None:
    """Resolve `OS_API_BASE`/`OS_API_TOKEN`: env wins, else the first config file found.

    Returns None when either value can't be found. Never logs the token.
    """
    env = os.environ if env is None else env
    base, token = env.get("OS_API_BASE", ""), env.get("OS_API_TOKEN", "")
    source = "env"
    if not (base and token):
        paths = config_search_paths(env) if search_paths is None else search_paths
        for path in paths:
            if path.is_file():
                values = _parse_env_file(path)
                base = base or values.get("OS_API_BASE", "")
                token = token or values.get("OS_API_TOKEN", "")
                source = str(path)
                break
    if not (base and token):
        return None
    return OsApiConfig(base=base.rstrip("/"), token=token, source=source)


def note_filename(note: Note) -> str:
    """A slug of the thought's first words; the service adds `<date>-charm-` and dedupes."""
    words = re.findall(r"[a-z0-9]+", note.text.lower())[:_FILENAME_WORDS]
    return ("-".join(words) or "note") + ".md"


def _yaml_str(value: str | None) -> str:
    # JSON strings are valid YAML double-quoted scalars, so any text is safe here.
    return "null" if value is None else json.dumps(value, ensure_ascii=False)


def _title(text: str) -> str:
    words = text.split()
    title = " ".join(words[:_TITLE_WORDS])
    return title + "…" if len(words) > _TITLE_WORDS else title


def note_content(note: Note) -> str:
    """The exact markdown submitted: frontmatter, then the verbatim thought as a blockquote."""
    book = note.book
    lines = [
        "---",
        f"title: {_yaml_str(_title(note.text))}",
        "type: reading-note",
        f"created: {note.captured_at.isoformat()}",
        "source: dex-charm",
        f"book: {_yaml_str(book.title if book else None)}",
        f"author: {_yaml_str(book.author if book else None)}",
        f"chapter: {_yaml_str(book.chapter if book else None)}",
        f"language: {_yaml_str(note.language)}",
        "tags: [reading, charm]",
        "---",
        "",
    ]
    lines += [f"> {line}" if line else ">" for line in note.text.split("\n")]
    return "\n".join(lines) + "\n"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx as errors: following one would resend the bearer token somewhere else."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any,
                         newurl: str) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _http_reason(status: int) -> str:
    if status == 401:
        return "vault service rejected the token (401)"
    if status == 403:
        return "vault service refused the write (403)"
    if status >= 500:
        return f"vault service error ({status})"
    return f"vault service returned HTTP {status}"


def _post_submit(config: OsApiConfig, payload: bytes, timeout: float) -> SaveReceipt:
    req = urllib.request.Request(
        f"{config.base}/submit", data=payload, method="POST",
        headers={"Authorization": f"Bearer {config.token}",
                 "Content-Type": "application/json", "X-Agent": AGENT})
    try:
        with _opener.open(req, timeout=timeout) as resp:
            status, body = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        log.warning("vault submit failed: HTTP %d", e.code)
        return SaveReceipt(ok=False, error=_http_reason(e.code))
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        timed_out = isinstance(e, TimeoutError) or isinstance(
            getattr(e, "reason", None), TimeoutError)
        log.warning("vault submit failed: %s", "timeout" if timed_out else type(e).__name__)
        return SaveReceipt(ok=False, error="vault service timed out" if timed_out
                           else "vault service unreachable")
    if not 200 <= status < 300:
        log.warning("vault submit failed: HTTP %d", status)
        return SaveReceipt(ok=False, error=_http_reason(status))
    try:
        reply = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        reply = None
    path = reply.get("path") if isinstance(reply, dict) else None
    if not isinstance(path, str) or not path.strip() or (
            isinstance(reply, dict) and reply.get("ok") is False):
        log.warning("vault submit: malformed reply (HTTP %d)", status)
        return SaveReceipt(ok=False, error="vault service gave a malformed reply")
    log.info("vault submit ok: %s", path)
    return SaveReceipt(ok=True, where=path)


class OsApiStore:
    """`NoteStore` backed by the OS knowledge service's `POST /submit` (inbox-only, new files)."""

    def __init__(self, config: OsApiConfig | None = None, *,
                 timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self._config = load_config() if config is None else config
        self._timeout = timeout

    def __repr__(self) -> str:
        return f"OsApiStore(config={self._config!r}, timeout={self._timeout})"

    @property
    def configured(self) -> bool:
        return self._config is not None

    async def save(self, note: Note) -> SaveReceipt:
        if self._config is None:
            return SaveReceipt(ok=False, error="vault service config not found")
        payload = json.dumps({"filename": note_filename(note), "content": note_content(note),
                              "agent": AGENT}).encode()
        # Exactly one attempt. The service creates a new file per submit, so a retry could
        # duplicate the note.
        return await asyncio.to_thread(_post_submit, self._config, payload, self._timeout)


def check_health(base: str, timeout: float = DEFAULT_TIMEOUT_S) -> tuple[bool, str]:
    """GET {base}/health (no auth). Returns (ok, human-readable detail)."""
    url = f"{base.rstrip('/')}/health"
    try:
        with _opener.open(urllib.request.Request(url), timeout=timeout) as resp:
            status, body = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        timed_out = isinstance(e, TimeoutError) or isinstance(
            getattr(e, "reason", None), TimeoutError)
        return False, "timed out" if timed_out else "unreachable"
    try:
        reply = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        reply = None
    if 200 <= status < 300 and isinstance(reply, dict) and reply.get("ok") is True:
        return True, "ok"
    return False, f"unexpected reply (HTTP {status})"
