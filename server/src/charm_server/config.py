"""Configuration from the environment, with an optional gitignored `.env` file.

Real environment variables always win over `.env` values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = SERVER_DIR.parent


def parse_env_file(text: str) -> dict[str, str]:
    """Parse `KEY=value` lines. Blank lines and `#` comments are skipped; quotes are stripped."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_env_file(path: Path) -> None:
    """Load `path` into os.environ without overriding variables already set."""
    if not path.is_file():
        return
    for key, value in parse_env_file(path.read_text()).items():
        os.environ.setdefault(key, value)


def _path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else (SERVER_DIR / path).resolve()


@dataclass(frozen=True)
class Config:
    token: str
    host: str
    port: int
    hermes_ssh_alias: str
    hermes_container: str
    cards_dir: Path
    schema_path: Path
    action_log: Path
    tz: str
    voice_en: str
    voice_es: str
    whisper_model: str

    @classmethod
    def from_env(cls, env_file: Path | None = SERVER_DIR / ".env") -> Config:
        if env_file is not None:
            load_env_file(env_file)
        env = os.environ
        return cls(
            token=env.get("CHARM_TOKEN", ""),
            host=env.get("CHARM_HOST", "127.0.0.1"),
            port=int(env.get("CHARM_PORT", "8765")),
            hermes_ssh_alias=env.get("HERMES_SSH_ALIAS", "hermes"),
            hermes_container=env.get("HERMES_CONTAINER", "hermes-agent"),
            cards_dir=_path("CHARM_CARDS_DIR", REPO_DIR / "contract" / "examples"),
            schema_path=_path("CHARM_SCHEMA", REPO_DIR / "contract" / "card.schema.json"),
            action_log=_path("CHARM_ACTION_LOG", SERVER_DIR / ".local" / "actions.jsonl"),
            tz=env.get("CHARM_TZ", "America/Chicago"),
            voice_en=env.get("CHARM_VOICE_EN", "en-US-AndrewNeural"),
            voice_es=env.get("CHARM_VOICE_ES", "es-CO-GonzaloNeural"),
            whisper_model=env.get("CHARM_WHISPER_MODEL", "base"),
        )
