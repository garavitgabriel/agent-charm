from __future__ import annotations

from pathlib import Path

import pytest

from charm_server.config import SERVER_DIR, Config, parse_env_file


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


def test_defaults_point_at_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CHARM_CARDS_DIR", "CHARM_SCHEMA", "HERMES_SSH_ALIAS"):
        monkeypatch.delenv(key, raising=False)
    config = Config.from_env(None)
    assert config.cards_dir.name == "examples" and config.cards_dir.is_dir()
    assert config.schema_path.is_file()
    assert config.hermes_ssh_alias == "hermes"


def test_env_example_lists_every_variable() -> None:
    text = (SERVER_DIR / ".env.example").read_text()
    for key in ("CHARM_TOKEN", "CHARM_HOST", "CHARM_PORT", "HERMES_SSH_ALIAS", "HERMES_CONTAINER"):
        assert f"{key}=" in text
