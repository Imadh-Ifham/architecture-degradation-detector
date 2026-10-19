"""Record one architecture snapshot per release.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    Produces the recorded recovery output the validation component develops
    and demonstrates against - one `snapshot_<release>.json` per release.

    Why this exists. The methodology says that where live recovery output is
    not available for a repository, a recorded recovery output is used, so
    that validation can be evaluated independently of recovery's completion
    schedule. This is the tool that makes that recording, and the recording is
    what the demonstration falls back to when the graph database, the clone or
    the network is not there on the day.

    **What changed on 2026-10-19, and the cost of it.** Recovery now publishes
    its own element-to-element dependencies, so this script no longer derives
    them: it reads recovery's graph and records what it finds. That makes the
    recording a recording of real output rather than of a substitute - and it
    means the script now needs an ingested repository and a reachable graph
    store, where before it needed neither. A recording of recovery's edges
    cannot be made without recovery, and pretending otherwise is what the
    deleted stand-in did.

    Run it deliberately, never from a request, and after ingesting the
    releases you want recorded:

        uv run python tests/fixtures/validation/record_snapshots.py <repository_id>

    The output is committed. A change on recovery's side then arrives as a
    reviewable diff rather than as a surprise during a run.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.infrastructure.neo4j.architecture_snapshot_store import (  # noqa: E402
    Neo4jArchitectureSnapshotStore,
)
from app.infrastructure.neo4j.database import get_neo4j_session  # noqa: E402
from app.infrastructure.recovery_gateway import (  # noqa: E402
    GraphStoreReader,
    WorkspaceIndex,
)

SNAPSHOTS = BACKEND / "data" / "snapshots"


def releases_of(repository_id: str) -> tuple[str, ...]:
    """Every release of a repository that has been ingested on this machine.

    Read from the workspace rather than listed here. A hard-coded release list
    records one subject system into a script that is supposed to work for any
    repository, and it goes stale the first time a release is added.
    """

    records = WorkspaceIndex(settings.repositories_root).records()

    return tuple(
        dict.fromkeys(
            record.release_id
            for record in records
            if repository_id in (record.id, record.repository_key)
        )
    )


def record(reader: GraphStoreReader, repository_id: str, release_id: str) -> Path:
    """Write one release's snapshot and return where it went."""

    architecture = reader.read(repository_id, release_id)

    document = architecture.to_dict()
    document["provenance"] = {
        "reader": "snapshot_file_reader",
        "source_schema_version": architecture.provenance.source_schema_version,
        "source_reference": (
            f"recorded from {architecture.provenance.source_snapshot_id}"
        ),
        "source_commit": architecture.provenance.source_commit,
        "source_snapshot_id": architecture.provenance.source_snapshot_id,
        "source_status": architecture.provenance.source_status,
    }

    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    target = SNAPSHOTS / f"snapshot_{release_id}.json"
    target.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    for note in reader.notes(repository_id, release_id):
        print(f"  note: {note}")

    print(
        f"  {target.name}: {len(architecture.elements)} elements, "
        f"{len(architecture.relationships)} dependencies, "
        f"status {architecture.provenance.source_status}"
    )
    return target


def record_all(repository_id: str) -> None:
    reader = GraphStoreReader(
        Neo4jArchitectureSnapshotStore(get_neo4j_session), settings.repositories_root
    )

    releases = releases_of(repository_id)

    if not releases:
        raise SystemExit(
            f"No ingested release for '{repository_id}'. Ingest the releases "
            "first; a recording cannot be made of something nobody analysed."
        )

    for release_id in releases:
        record(reader, repository_id, release_id)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: record_snapshots.py <repository_id>\n"
            "The id is recovery's, as `GET /repositories` reports it."
        )

    record_all(sys.argv[1])
