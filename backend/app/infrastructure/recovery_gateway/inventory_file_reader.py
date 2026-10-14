"""Repository inventory file reader.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Reads the inventory document recovery writes for an ingested repository,
    and translates it for one release.

    The release is named by the caller, not discovered here. One inventory
    describes one working tree at one commit, so which release that commit
    represents is knowledge the caller has and this reader does not.
"""

import json
from pathlib import Path

from app.domain.recovered_architecture import RecoveredArchitecture

from .inventory_schema import InventoryContractError
from .translation import manifest_paths, translate

INVENTORY_FILE_NAME = "repository_inventory.json"


class InventoryFileArchitectureReader:
    """Reads a recovered architecture from an inventory document on disk."""

    def __init__(self, inventory_root: Path) -> None:
        """Bind the reader to the directory holding inventory documents."""

        self._root = Path(inventory_root)

    def read(self, repository_id: str, release_id: str) -> RecoveredArchitecture:
        """Return the recovered architecture for one release."""

        path = self._path_for(repository_id)
        document = self._load(path)
        return translate(
            document,
            repository_id=repository_id,
            release_id=release_id,
            source_reference=str(path),
            reader="inventory_file_reader",
        )

    def manifest_paths(self, repository_id: str) -> tuple[str, ...]:
        """Every manifest path the inventory recorded, for the derivation."""

        return manifest_paths(self._load(self._path_for(repository_id)))

    def _path_for(self, repository_id: str) -> Path:
        return self._root / repository_id / INVENTORY_FILE_NAME

    def _load(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            # Raised rather than returned as an empty architecture: a missing
            # inventory means recovery has not run, which is a different
            # situation from a repository that genuinely has no components, and
            # the two must not look the same to a caller.
            raise InventoryContractError(
                f"No repository inventory at '{path}'. Run the inventory first."
            ) from error
        except json.JSONDecodeError as error:
            raise InventoryContractError(
                f"Repository inventory at '{path}' is not valid JSON: {error}"
            ) from error
