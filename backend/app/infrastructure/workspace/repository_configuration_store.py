"""Configured snapshots, kept beside the ingestion workspace.

Author: Imadh Ifham
Date: 2026-10-20
Description:
    Stores the small list of repository snapshots a person has configured but
    not yet analysed. One JSON file under the workspace root, written
    atomically, because the alternative - a database row per configured
    snapshot - would make setting up a repository require a database that the
    ingestion workspace itself does not.

    Nothing here clones anything. The file says what should be analysed; the
    pipeline decides when.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from app.domain.repository_configuration import RepositoryConfiguration

CONFIGURATIONS_FILE_NAME = "configurations.json"


class ConfigurationStoreError(RuntimeError):
    """The configuration file exists but cannot be read or written."""


class RepositoryConfigurationStore:
    """Reads and writes the configured snapshots for one workspace root."""

    def __init__(self, root: Path) -> None:
        """Bind the store to the workspace root it lives under."""

        self._root = Path(root)

    @property
    def path(self) -> Path:
        """The file the configurations are kept in."""

        return self._root / CONFIGURATIONS_FILE_NAME

    def list(self) -> list[RepositoryConfiguration]:
        """Every configured snapshot, in the order it was configured."""

        if not self.path.is_file():
            return []

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationStoreError(
                f"Could not read the configured snapshots at '{self.path}': {error}"
            ) from error

        if not isinstance(payload, list):
            raise ConfigurationStoreError(
                f"'{self.path}' does not hold a list of configured snapshots."
            )

        configurations = []

        for entry in payload:
            try:
                configurations.append(RepositoryConfiguration.from_dict(entry))
            except (KeyError, TypeError, ValueError) as error:
                raise ConfigurationStoreError(
                    f"'{self.path}' holds a row that cannot be read: {error}"
                ) from error

        return sorted(configurations, key=lambda item: (item.created_at, item.id))

    def save(self, configuration: RepositoryConfiguration) -> RepositoryConfiguration:
        """Add or replace one configured snapshot, and return what was stored.

        Replacing keeps the original position in the stack: configuring the
        same snapshot twice is an edit, and an edit that moved it to the end
        would silently reorder the run. That is why the first `created_at` is
        kept rather than overwritten by the edit.
        """

        existing = self.list()
        previous = next(
            (item for item in existing if item.id == configuration.id), None
        )
        stored = (
            replace(configuration, created_at=previous.created_at)
            if previous is not None
            else configuration
        )
        kept = [
            stored if item.id == configuration.id else item for item in existing
        ]

        self._write(kept if previous is not None else kept + [stored])

        return stored

    def delete(self, configuration_id: str) -> bool:
        """Remove one configured snapshot. False when there was none."""

        existing = self.list()
        kept = [item for item in existing if item.id != configuration_id]

        if len(kept) == len(existing):
            return False

        self._write(kept)
        return True

    def _write(self, configurations: list[RepositoryConfiguration]) -> None:
        """Write the whole list atomically, so a reader never sees half of it."""

        self._root.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(
            [item.to_dict() for item in configurations], indent=2
        )

        handle, temporary = tempfile.mkstemp(
            dir=str(self._root), prefix=".configurations.", suffix=".partial"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            Path(temporary).unlink(missing_ok=True)
            raise ConfigurationStoreError(
                f"Could not write the configured snapshots at '{self.path}': {error}"
            ) from error


__all__ = [
    "CONFIGURATIONS_FILE_NAME",
    "ConfigurationStoreError",
    "RepositoryConfigurationStore",
]
