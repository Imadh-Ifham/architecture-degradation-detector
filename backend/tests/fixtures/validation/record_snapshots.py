"""Record one architecture snapshot per release.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Produces the recorded recovery output the validation component develops and
    demonstrates against - one `snapshot_<release>.json` per release, written
    beside the inventory recordings it was built from.

    Why this exists. The methodology says that where live recovery output is
    not available for a repository, a recorded recovery output is used, so that
    validation can be evaluated independently of recovery's completion
    schedule. This is the tool that makes that recording.

    What it does, in order: read the inventory document recovery really wrote,
    translate it into the validation component's shape, and - only while
    recovery's own dependency extraction is unfinished - fill in the
    element-to-element dependencies with the stand-in. The stand-in is a no-op
    once recovery supplies them, so re-running this after recovery ships
    changes the output and not this script.

    Run it deliberately, never from a request:

        uv run python tests/fixtures/validation/record_snapshots.py

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

from app.infrastructure.recovery_gateway.c1_dependency_stand_in import (  # noqa: E402
    supply_dependencies,
)
from app.infrastructure.recovery_gateway.fixture_reader import (  # noqa: E402
    FixtureArchitectureReader,
)

RELEASES = ("v0.9.0", "v0.10.0")
SNAPSHOTS = BACKEND / "data" / "snapshots"
REPOSITORY_ID = "online-boutique"
SUBJECT = HERE / "subject"


class SubjectTreeReader:
    """Reads the generated subject working tree for one release.

    The stand-in needs a `SourceArtifactReader`, and for a recording the source
    is the generated subject tree rather than an ingestion workspace - the
    recording has to be reproducible from a fresh clone with nothing cloned.
    """

    def read_text(self, repository_id: str, release_id: str, path: str) -> str:
        return (SUBJECT / release_id / path).read_text(encoding="utf-8")

    def list_paths(self, repository_id: str, release_id: str, pattern: str) -> list[str]:
        root = SUBJECT / release_id
        return sorted(
            str(match.relative_to(root)).replace("\\", "/")
            for match in root.glob(pattern)
            if match.is_file()
        )


def record(release_id: str) -> Path:
    """Write one release's snapshot and return where it went."""

    architecture = FixtureArchitectureReader(HERE).read(REPOSITORY_ID, release_id)
    architecture, warnings = supply_dependencies(architecture, SubjectTreeReader())

    document = architecture.to_dict()
    document["provenance"] = {
        "reader": "snapshot_file_reader",
        "source_schema_version": architecture.provenance.source_schema_version,
        "source_reference": f"recorded from inventory_{release_id}.json",
    }

    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    target = SNAPSHOTS / f"snapshot_{release_id}.json"
    target.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    for warning in warnings:
        print(f"  warning: {warning}")

    print(
        f"  {target.name}: {len(architecture.elements)} elements, "
        f"{len(architecture.relationships)} dependencies, "
        f"style {architecture.style} ({architecture.style_source})"
    )
    return target


def record_all() -> None:
    sys.path.insert(0, str(HERE))
    import build_subject_tree

    build_subject_tree.build_all()

    for release_id in RELEASES:
        record(release_id)


if __name__ == "__main__":
    record_all()
