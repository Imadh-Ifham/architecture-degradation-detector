"""Inventory writer.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Serialises an inventory to `repository_inventory.json`. The file is written
    to a temporary name and renamed into place, so a reader (or a crash) never
    observes a partially written inventory.
"""

import json
import os
import uuid
from pathlib import Path

from app.components.architecture_recovery.repository_inventory.errors import (
    InventoryWriteError,
)
from app.components.architecture_recovery.repository_inventory.models import (
    RepositoryInventory,
)


INVENTORY_FILE_NAME = "repository_inventory.json"


def write_inventory(inventory: RepositoryInventory, directory: Path) -> Path:
    """Write `inventory` into `directory` and return the file path.

    Raises `InventoryWriteError` if the file cannot be written.
    """

    directory = Path(directory)

    try:
        directory.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(inventory.to_dict(), indent=2, ensure_ascii=False)
        target = directory / INVENTORY_FILE_NAME
        temporary = directory / f".{INVENTORY_FILE_NAME}.{uuid.uuid4().hex}.tmp"

        temporary.write_text(payload + "\n", encoding="utf-8")

        # Atomic rename within the same directory: the inventory is either the
        # previous version or the new one, never a truncated mix of both.
        os.replace(temporary, target)

        return target
    except OSError as error:
        raise InventoryWriteError(
            f"Could not write the inventory into '{directory}': {error}"
        ) from error


def load_inventory(path: Path) -> dict:
    """Read an inventory document back from disk."""

    return json.loads(Path(path).read_text(encoding="utf-8"))
