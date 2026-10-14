"""Fixture architecture reader.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Reads a recovered architecture from a committed fixture.

    This exists so validation can be built and demonstrated at full fidelity
    without depending on recovery having run, or on the ingestion workspace
    still holding a clone. It is the same protocol as the live reader, so
    switching between them is configuration rather than code.

    The fixture it reads is produced by running recovery's own inventory
    against the subject repository and committing the result. That makes it a
    recording of real output rather than an invention - and when recovery
    changes, re-recording it produces a reviewable diff.
"""

import json
from pathlib import Path

from app.domain.recovered_architecture import ArchitectureStyle, RecoveredArchitecture

from .inventory_schema import InventoryContractError
from .translation import manifest_paths, translate


class FixtureArchitectureReader:
    """Reads a recovered architecture from a committed inventory fixture."""

    def __init__(
        self,
        fixture_root: Path,
        style_override: ArchitectureStyle | None = None,
    ) -> None:
        self._root = Path(fixture_root)
        self._style_override = style_override

    def read(self, repository_id: str, release_id: str) -> RecoveredArchitecture:
        path = self._path_for(release_id)
        document = self._load(path)
        return translate(
            document,
            repository_id=repository_id,
            release_id=release_id,
            source_reference=str(path),
            reader="fixture_reader",
            style_override=self._style_override,
        )

    def manifest_paths(self, release_id: str) -> tuple[str, ...]:
        return manifest_paths(self._load(self._path_for(release_id)))

    def _path_for(self, release_id: str) -> Path:
        return self._root / f"inventory_{release_id}.json"

    def _load(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise InventoryContractError(
                f"No inventory fixture at '{path}'."
            ) from error
