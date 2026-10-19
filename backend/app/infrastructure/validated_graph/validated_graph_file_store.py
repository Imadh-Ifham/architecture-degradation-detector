"""The published validated graph, on disk.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    Writes the one artifact the next component reads, and is the only
    implementation of `ValidatedGraphPublisher` that matters.

    Two properties make it the fail-safe the consumer depends on, and both are
    about what a reader sees while a write is happening.

    A run's document is written to a temporary name in the same directory and
    moved with `os.replace`, which is atomic on one filesystem. A reader
    therefore gets the old document whole or the new one whole, and never a
    half-written one - which would parse as a release with no dependencies
    rather than failing.

    And `latest.graph.json` is moved only after the run-specific file has
    landed. A failed run writes nothing, so `latest` still resolves to the
    last document that completed, which is a correct graph of an older release
    rather than an absent graph of this one.
"""

import json
import os
import tempfile
from pathlib import Path

from app.domain.validated_architecture import (
    SizeUnitConflict,
    ValidatedArchitectureGraph,
)

LATEST_FILENAME = "latest.graph.json"


class ValidatedGraphFileStore:
    """Writes a published graph under `<root>/<repository_id>/<release_id>/`."""

    def __init__(self, root: Path) -> None:
        """Bind the store to the directory runs are published under."""

        self._root = Path(root)

    def publish(self, document: ValidatedArchitectureGraph) -> str:
        """Write the document and return the path it landed at.

        Raises rather than warning. This is the contract, and a run that could
        not write it has produced nothing for the next component to read.
        """

        self._refuse_a_mixed_series(document)

        directory = self._directory(document.repository_id, document.release_id)
        directory.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(document.to_node_link(), indent=2, sort_keys=False)
        target = directory / f"{document.stamp.run_id}.graph.json"
        _write_atomically(target, payload)
        _write_atomically(directory / LATEST_FILENAME, payload)

        return str(target)

    def read(self, repository_id: str, release_id: str) -> dict | None:
        """The most recent published document for one release, if any.

        Used by the route that draws the graph and by the rule below. Returns
        `None` rather than raising: a release nobody has validated yet is a
        real state, and it has its own screen.
        """

        latest = self._directory(repository_id, release_id) / LATEST_FILENAME
        if not latest.is_file():
            return None
        return json.loads(latest.read_text(encoding="utf-8"))

    def _refuse_a_mixed_series(self, document: ValidatedArchitectureGraph) -> None:
        """Stop a release whose size unit disagrees with an earlier release.

        The consumer compares an element's size against the same element in
        the next release, so a series measured in lines here and bytes there
        is a graph of nothing - with no error anywhere, because both are
        numbers.

        The check lives here because this is the only part of the chain that
        can see what came before: the component is handed one run, and the
        document refuses a *within*-release conflict in its own constructor.

        A release that reports no size is never a conflict. Most do not report
        one yet.
        """

        unit = document.size_unit
        if unit is None:
            return

        established = self._established_unit(document.repository_id, unit)
        if established is not None and established != unit:
            raise SizeUnitConflict((established, unit), document.release_id)

    def _established_unit(self, repository_id: str, unit: str) -> str | None:
        """The size unit this repository's published releases already use."""

        repository = self._root / repository_id
        if not repository.is_dir():
            return None

        for release in sorted(repository.iterdir()):
            latest = release / LATEST_FILENAME
            if not latest.is_file():
                continue
            document = json.loads(latest.read_text(encoding="utf-8"))
            for node in document.get("nodes", []):
                established = node.get("size_unit")
                if established:
                    return established
        return None

    def _directory(self, repository_id: str, release_id: str) -> Path:
        return self._root / repository_id / release_id


def _write_atomically(target: Path, payload: str) -> None:
    """Write `payload` to `target` so a reader never sees it half-written.

    The temporary file is created in the *same* directory on purpose:
    `os.replace` is atomic within one filesystem and merely a copy across two,
    and a copy is exactly the window this exists to close.
    """

    handle, temporary = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".partial"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
