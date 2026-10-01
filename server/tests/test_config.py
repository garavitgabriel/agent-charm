from __future__ import annotations

from pathlib import Path

import pytest

from charm_server.config import SERVER_DIR, Config, parse_env_file, system_tz


def test_parse_env_file() -> None:
    text = "# comment\n\nCHARM_TOKEN='abc'\nexport CHARM_PORT=9000\nHERMES_SSH_ALIAS=\"h\"\nnoise\n"
    assert parse_env_file(text) == {
        "CHARM_TOKEN": "abc",
        "CHARM_PORT": "9000",
        "HERMES_SSH_ALIAS": "h",
    }


def test_env_wins_over_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CHARM_TOKEN", "CHARM_PORT", "CHARM_CARDS_DIR", "HERMES_CONTAINER"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text("CHARM_TOKEN=from-file\nCHARM_PORT=9000\nCHARM_CARDS_DIR=cards\n")
    monkeypatch.setenv("CHARM_TOKEN", "from-env")
    config = Config.from_env(env)
    assert config.token == "from-env"
    assert config.port == 9000
    assert config.cards_dir == (SERVER_DIR / "cards").resolve()
    assert config.hermes_container == "hermes-agent"


def test_generic_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "CHARM_AGENT",
        "CHARM_AGENT_BASE_URL",
        "OPENAI_BASE_URL",
        "CHARM_AGENT_MODEL",
        "CHARM_OWNER_NAME",
        "CHARM_MAIN_CHAT",
        "CHARM_NOTES",
        "COACH_ENABLED",
        "COACH_LEDGER_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    config = Config.from_env(None)
    assert config.agent_backend == "openai"
    assert config.agent_base_url == "https://api.openai.com/v1"
    assert config.agent_model == ""
    assert config.notes_backend == "file" and config.notes_dir is not None
    assert not config.coach_enabled and config.coach_ledger_path == ""
    assert config.persona.owner == "" and config.persona.possessive == "a personal agent"


def test_agent_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARM_AGENT", "Hermes")
    monkeypatch.setenv("CHARM_AGENT_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("CHARM_AGENT_MODEL", "llama3.2")
    monkeypatch.setenv("CHARM_OWNER_NAME", "Sam")
    monkeypatch.setenv("CHARM_TZ", "Europe/Madrid")
    monkeypatch.delenv("CHARM_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    config = Config.from_env(None)
    assert config.agent_backend == "hermes"
    assert config.agent_base_url == "http://127.0.0.1:11434/v1"
    assert config.agent_model == "llama3.2" and config.agent_api_key == "k"
    assert config.persona.possessive == "Sam's agent"
    assert config.tz == "Europe/Madrid"


def test_system_tz_is_an_iana_name() -> None:
    from zoneinfo import ZoneInfo

    ZoneInfo(system_tz())  # raises if it isn't a real zone


def test_defaults_point_at_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CHARM_CARDS_DIR", "CHARM_SCHEMA", "HERMES_SSH_ALIAS"):
        monkeypatch.delenv(key, raising=False)
    config = Config.from_env(None)
    assert config.cards_dir.name == "examples" and config.cards_dir.is_dir()
    assert config.schema_path.is_file()
    assert config.hermes_ssh_alias == "hermes"


def test_env_example_lists_every_variable() -> None:
    text = (SERVER_DIR / ".env.example").read_text()
    for key in (
        "CHARM_TOKEN",
        "CHARM_HOST",
        "CHARM_PORT",
        "CHARM_AGENT",
        "CHARM_AGENT_BASE_URL",
        "CHARM_AGENT_API_KEY",
        "CHARM_AGENT_MODEL",
        "CHARM_OWNER_NAME",
        "CHARM_TZ",
        "HERMES_SSH_ALIAS",
        "HERMES_CONTAINER",
    ):
        assert f"{key}=" in text


def test_coach_api_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COACH_API_PATH", raising=False)
    assert Config.from_env(None).coach_api_path == "/v1"
    monkeypatch.setenv("COACH_API_PATH", "/p/coach/v1")
    assert Config.from_env(None).coach_api_path == "/p/coach/v1"
