"""Configuration from the environment, with an optional gitignored `.env` file.

Real environment variables always win over `.env` values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .agent import Persona

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


def _flag(value: str) -> bool:
    return value.strip().lower() not in ("0", "false", "no", "off", "")


def system_tz() -> str:
    """This machine's IANA zone (`TZ`, else the `/etc/localtime` link), else UTC."""
    tz = os.environ.get("TZ", "").lstrip(":")
    if "/" in tz or tz == "UTC":
        return tz
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return "UTC"
    marker = "zoneinfo/"
    return target.split(marker, 1)[1] if marker in target else "UTC"


AGENT_BACKENDS = ("openai", "hermes")


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
    hermes_channel: bool = True
    # The HTTP API (docs/HTTP.md) on the same host: 0 disables it. Idle device sessions expire
    # after `http_session_ttl` seconds.
    http_port: int = 8766
    http_session_ttl: float = 3600.0
    books_path: Path | None = None  # None: reading state in memory only (tests)
    notes_backend: str = "file"
    notes_dir: Path | None = None  # CHARM_NOTES=file: where notes land (None: .local/notes)
    # The agent backend: "openai" (any OpenAI-compatible chat-completions endpoint) or "hermes"
    # (a Hermes container over SSH + docker exec).
    agent_backend: str = "openai"
    agent_base_url: str = "https://api.openai.com/v1"
    agent_api_key: str = ""
    agent_model: str = ""
    # Who the agents work for, and where actions go instead (both optional; see agent.Persona).
    owner_name: str = ""
    main_chat: str = ""
    # Coach Beard, the optional second agent. Disabled (the default, and tests): a Coach
    # question gets an honest notice. With the hermes backend, the env file and ledger are paths
    # INSIDE the container.
    coach_enabled: bool = False
    coach_model: str = ""  # openai backend: his model ("" = the same as Dex's)
    coach_env_path: str = "/opt/data/profiles/coach/.env"
    coach_port: int = 8644
    coach_api_path: str = "/v1"  # Hermes v2026.9.24+ multiplexer: port 8642, "/p/coach/v1"
    coach_ledger_path: str = ""  # hermes backend: his decision ledger ("" = no fast path)
    coach_voice_en: str = "en-US-ChristopherNeural"
    coach_voice_es: str = "es-MX-JorgeNeural"
    coach_jobs_path: Path | None = None  # None: walk-away jobs in memory only (tests)
    # ElevenLabs speech (optional): with a key and a voice id it speaks for that character, and
    # the Edge voices above become the fallback. No key: Edge only.
    elevenlabs_api_key: str = ""
    elevenlabs_model: str = "eleven_flash_v2_5"
    elevenlabs_voice_en: str = ""
    elevenlabs_voice_es: str = ""  # "" = the English voice (Flash v2.5 is multilingual)
    elevenlabs_voice_coach_en: str = ""  # "" = Coach stays on Edge
    elevenlabs_voice_coach_es: str = ""

    @property
    def persona(self) -> Persona:
        return Persona(owner=self.owner_name, main_chat=self.main_chat)

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
            tz=env.get("CHARM_TZ") or system_tz(),
            voice_en=env.get("CHARM_VOICE_EN", "en-US-AndrewNeural"),
            voice_es=env.get("CHARM_VOICE_ES", "es-ES-AlvaroNeural"),
            whisper_model=env.get("CHARM_WHISPER_MODEL", "base"),
            hermes_channel=env.get("HERMES_CHANNEL", "1").strip().lower()
            not in ("0", "false", "no"),
            http_port=int(env.get("CHARM_HTTP_PORT") or "8766"),
            http_session_ttl=float(env.get("CHARM_HTTP_SESSION_TTL") or "3600"),
            books_path=_path("CHARM_BOOKS", SERVER_DIR / ".local" / "books.json"),
            notes_backend=env.get("CHARM_NOTES", "file").strip().lower() or "file",
            notes_dir=_path("CHARM_NOTES_DIR", SERVER_DIR / ".local" / "notes"),
            agent_backend=env.get("CHARM_AGENT", "openai").strip().lower() or "openai",
            agent_base_url=env.get("CHARM_AGENT_BASE_URL")
            or env.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1",
            agent_api_key=env.get("CHARM_AGENT_API_KEY") or env.get("OPENAI_API_KEY") or "",
            agent_model=env.get("CHARM_AGENT_MODEL", "").strip(),
            owner_name=env.get("CHARM_OWNER_NAME", "").strip(),
            main_chat=env.get("CHARM_MAIN_CHAT", "").strip(),
            coach_enabled=_flag(env.get("COACH_ENABLED", "0")),
            coach_model=env.get("COACH_MODEL", "").strip(),
            coach_env_path=env.get("COACH_ENV_PATH") or "/opt/data/profiles/coach/.env",
            coach_port=int(env.get("COACH_PORT") or "8644"),
            coach_api_path=env.get("COACH_API_PATH", "").strip() or "/v1",
            coach_ledger_path=env.get("COACH_LEDGER_PATH", "").strip(),
            coach_voice_en=env.get("CHARM_VOICE_COACH_EN") or "en-US-ChristopherNeural",
            coach_voice_es=env.get("CHARM_VOICE_COACH_ES") or "es-MX-JorgeNeural",
            coach_jobs_path=_path("COACH_JOBS", SERVER_DIR / ".local" / "coach-jobs.json"),
            elevenlabs_api_key=env.get("ELEVENLABS_API_KEY", "").strip(),
            elevenlabs_model=env.get("ELEVENLABS_MODEL", "").strip() or "eleven_flash_v2_5",
            elevenlabs_voice_en=env.get("ELEVENLABS_VOICE_EN", "").strip(),
            elevenlabs_voice_es=env.get("ELEVENLABS_VOICE_ES", "").strip(),
            elevenlabs_voice_coach_en=env.get("ELEVENLABS_VOICE_COACH_EN", "").strip(),
            elevenlabs_voice_coach_es=env.get("ELEVENLABS_VOICE_COACH_ES", "").strip(),
        )
