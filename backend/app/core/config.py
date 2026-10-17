"""Application settings.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Loads configuration from three sources, in increasing order of precedence:

      1. the field defaults declared here,
      2. `backend/config.ini`, which is committed and holds non-sensitive
         tuning values shared by every developer and environment,
      3. environment variables and `backend/.env`, which hold secrets and
         environment-specific values and are never committed.

    The split exists so that a committed file documents the tuning knobs, while
    credentials and machine-specific paths stay out of version control. Because
    the environment wins, anything in `config.ini` can still be overridden per
    machine or per deployment.
"""

import configparser
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


#: Committed, non-sensitive configuration. Resolved relative to this file so
#: the configured values are found regardless of the process working directory.
CONFIG_INI_PATH = Path(__file__).resolve().parents[2] / "config.ini"

#: Sections of `config.ini` that map onto settings. A section name is a
#: namespace in the file only; the field names stay flat.
CONFIG_INI_SECTIONS = ("app", "git", "inventory", "manifest_analysis", "validation")


class ConfigIniSettingsSource(PydanticBaseSettingsSource):
    """Reads settings from a committed INI file.

    `pydantic-settings` supports dotenv and secrets files natively but not INI,
    so the file is read through `configparser` and flattened into the mapping
    the settings class expects. Unknown keys are ignored rather than rejected,
    because the file is shared and may be ahead of a given deployment.
    """

    def __init__(
        self, settings_cls: type[BaseSettings], path: Path = CONFIG_INI_PATH
    ) -> None:
        """Store the settings class and the INI path to read."""

        super().__init__(settings_cls)
        self._path = Path(path)

    def __call__(self) -> dict[str, Any]:
        """Return the INI values as a flat mapping, or nothing if absent."""

        if not self._path.is_file():
            return {}

        parser = configparser.ConfigParser()

        try:
            parser.read(self._path, encoding="utf-8")
        except configparser.Error:
            # A malformed INI file must not stop the application from starting;
            # the defaults and the environment still apply.
            return {}

        values: dict[str, Any] = {}

        for section in CONFIG_INI_SECTIONS:
            if not parser.has_section(section):
                continue

            for key, value in parser.items(section):
                values[key] = value

        return values

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        """Unused: `__call__` returns the whole mapping instead."""

        return None, field_name, False

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration for the backend."""

    app_name: str = "Architecture Degradation Detector"
    app_env: str = "development"
    # Published on the generated API documentation, so a client can tell two
    # deployments apart.
    app_version: str = "0.1.0"

    postgres_host: str
    postgres_port: int = 5434
    postgres_db: str
    postgres_user: str
    postgres_password: str

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    # Local workspace holding ingested (cloned) repositories.
    repositories_root: Path = Path(gettempdir()) / "add-repositories"

    # Where the architecture validation component reads its input from; see
    # the [validation] section of config.ini. Never a silent fallback between
    # the two: whichever answered is stamped on the run's provenance, so a
    # result always says which input produced it.
    architecture_source: str = "snapshot"
    # Derived rather than configured, because it is the same relative location
    # on every machine and an absolute path does not belong in a committed file.
    snapshot_root: Path = BACKEND_ROOT / "data" / "snapshots"
    # The decision history the validation component accumulates per
    # repository. Output rather than input, so it lives under the ignored
    # artifacts directory; the demonstration's corpus is a committed fixture.
    decision_log_root: Path = BACKEND_ROOT / "artifacts" / "validation" / "decisions"
    clone_timeout_seconds: int = 300

    # Repository inventory limits.
    max_files: int = 20_000
    max_file_size_bytes: int = 5_000_000
    max_depth: int = 32
    max_manifest_bytes: int = 262_144
    grouping_depth: int = 2
    extra_excluded_directories: str = ""

    # Manifest analysis limits.
    manifest_max_bytes: int = 1_048_576
    manifest_max_documents: int = 64

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # So a key renamed in the environment fails loudly rather than being
        # silently ignored.
        extra="forbid",
        # Read only this class's own fields from the file. `.env` is shared
        # with `AISettings`, which owns the `ai_*` names, so without this
        # `extra="forbid"` rejects the whole file over a key that belongs to
        # another settings class and every consumer of these settings fails.
        # The environment source already ignores names it does not own; this
        # makes the file source consistent with it.
        dotenv_filtering="only_existing",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order the sources: explicit arguments, environment, dotenv, config.ini.

        `config.ini` is last, so a value set in the environment or in `.env`
        always wins over the committed default.
        """

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            ConfigIniSettingsSource(settings_cls),
            file_secret_settings,
        )


settings = Settings()
