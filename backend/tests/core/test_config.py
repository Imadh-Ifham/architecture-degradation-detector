"""Tests for application settings.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Covers the three-source configuration chain: field defaults, the committed
    `config.ini`, and the environment/`.env`. Asserts the precedence between
    them and that a broken or missing INI file degrades to the defaults rather
    than preventing startup.
"""

import tempfile
from pathlib import Path

import pytest

from app.core.config import (
    CONFIG_INI_PATH,
    ConfigIniSettingsSource,
    Settings,
)


#: The required fields have no defaults, so they must be supplied by the
#: environment. They are set through the environment rather than a dotenv file
#: so the tests are independent of the developer's own `.env`.
REQUIRED_ENVIRONMENT = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_DB": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "test",
}


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide the required settings through the environment only."""

    for key, value in REQUIRED_ENVIRONMENT.items():
        monkeypatch.setenv(key, value)


def test_committed_config_ini_exists() -> None:
    """The file is committed, so it must be present in a checkout."""

    assert CONFIG_INI_PATH.is_file()
    assert CONFIG_INI_PATH.name == "config.ini"


def test_settings_load_tuning_values_from_config_ini(environment: None) -> None:
    """Non-sensitive tuning comes from the committed file, not from .env."""

    settings = Settings(_env_file=None)

    assert settings.clone_timeout_seconds == 300
    assert settings.max_files == 20_000
    assert settings.max_file_size_bytes == 5_000_000
    assert settings.max_depth == 32
    assert settings.max_manifest_bytes == 262_144
    assert settings.grouping_depth == 2
    assert settings.manifest_max_bytes == 1_048_576
    assert settings.manifest_max_documents == 64
    assert settings.app_name == "Architecture Degradation Detector"


def test_environment_overrides_config_ini(
    environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anything in config.ini must stay overridable per machine or deployment."""

    monkeypatch.setenv("MAX_FILES", "123")
    monkeypatch.setenv("CLONE_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("MANIFEST_MAX_DOCUMENTS", "4")

    settings = Settings(_env_file=None)

    assert settings.max_files == 123
    assert settings.clone_timeout_seconds == 7
    assert settings.manifest_max_documents == 4


def test_init_arguments_override_everything(environment: None) -> None:
    """Explicit arguments win over both the file and the environment."""

    settings = Settings(_env_file=None, max_files=9)

    assert settings.max_files == 9


def test_secrets_are_not_in_the_committed_file() -> None:
    """A secret must never be reachable through the committed configuration.

    Values are checked, not the comment text, so the file is still free to
    explain that secrets belong elsewhere.
    """

    assignments = []

    for line in CONFIG_INI_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith((";", "#", "[")):
            continue

        if "=" in stripped:
            key, _, value = stripped.partition("=")
            assignments.append((key.strip().lower(), value.strip().lower()))

    assert assignments, "config.ini should assign settings"

    for key, value in assignments:
        for forbidden in ("password", "secret", "token", "api_key", "apikey"):
            assert forbidden not in key, f"{key} looks like a secret"
            assert forbidden not in value, f"{key} has a secret-looking value"


def test_missing_config_ini_falls_back_to_defaults(environment: None) -> None:
    source = ConfigIniSettingsSource(Settings, path=Path("does-not-exist.ini"))

    assert source() == {}


def test_malformed_config_ini_does_not_prevent_startup(environment: None) -> None:
    """A broken INI must degrade to the defaults, not stop the application."""

    with tempfile.TemporaryDirectory() as directory:
        broken = Path(directory) / "config.ini"
        broken.write_text("this is [not valid ini\n====\n", encoding="utf-8")

        source = ConfigIniSettingsSource(Settings, path=broken)

        assert source() == {}


def test_config_ini_holds_only_known_settings(environment: None) -> None:
    """Every key in the file must map to a real setting.

    `extra="forbid"` turns an unknown key into a startup error, so this guards
    the committed file against typos and against drift when a setting is renamed.
    """

    values = ConfigIniSettingsSource(Settings)()

    assert values, "config.ini should define settings"
    assert set(values) <= set(Settings.model_fields)


def test_config_ini_is_found_from_any_working_directory(
    environment: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The path is resolved relative to the module, not the process cwd."""

    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None)

    assert settings.max_files == 20_000
