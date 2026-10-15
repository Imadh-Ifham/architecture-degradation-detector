"""Small CanonicalReleases for the M2 tests, built from an edge list or a golden fixture file."""

import datetime as dt
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from app.domain.canonical_release import (
    CanonicalRelease,
    DatastoreAccess,
    DependencyEdge,
    ElementSnapshot,
    GateStatus,
)
from app.domain.release_package import ArchitectureStyle

HASH = "sha256:" + "0" * 64


def release(
    nodes: Iterable[str],
    edges: Iterable[tuple[str, str]] = (),
    *,
    sizes: Mapping[str, float | None] | None = None,
    size_unit: str | Mapping[str, str] = "loc",
    metrics: Mapping[str, dict[str, float | None]] | None = None,
    counts: Mapping[tuple[str, str], int] | None = None,
    release_id: str = "v1.0.0",
    style: ArchitectureStyle = ArchitectureStyle.MICROSERVICES,
    datastore_access: Iterable[tuple[str, str]] | None = None,
) -> CanonicalRelease:
    """A release with the given elements and edges; elements are kept in the order given.

    ``datastore_access`` is ``(element, datastore)`` pairs; None means C2 did not send the field.
    """
    sizes = sizes or {}
    metrics = metrics or {}
    counts = counts or {}
    elements = tuple(
        ElementSnapshot(
            element_id=node,
            name=node,
            kind="service",
            size=sizes.get(node),
            size_unit=size_unit if isinstance(size_unit, str) else size_unit.get(node),
            metrics=metrics.get(node, {}),
        )
        for node in nodes
    )
    return CanonicalRelease(
        system_id="tiny",
        release_id=release_id,
        released_at=dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
        architecture_style=style,
        granularity="service",
        validation_confidence=0.9,
        gate_status=GateStatus.ACCEPTED,
        package_hash=HASH,
        elements=elements,
        dependencies=tuple(
            DependencyEdge(from_id=a, to_id=b, types=("call",), count=counts.get((a, b), 1))
            for a, b in edges
        ),
        datastore_access=None
        if datastore_access is None
        else tuple(DatastoreAccess(element_id=e, datastore=d) for e, d in datastore_access),
    )


GRAPH_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "graphs"


def graph_fixtures() -> list[Path]:
    """Golden graphs, ``<Detector>__positive_NN.json`` / ``<Detector>__negative_NN.json``."""
    return sorted(GRAPH_FIXTURE_DIR.glob("*.json"))


def load_graph_fixture(path: Path) -> tuple[CanonicalRelease, list[dict[str, Any]]]:
    """The fixture's release and its complete expected detector output."""
    data = json.loads(path.read_text(encoding="utf-8"))
    elements = data["elements"]
    r = release(
        [e["id"] for e in elements],
        [(a, b) for a, b in data["dependencies"]],
        sizes={e["id"]: e.get("size") for e in elements},
        release_id=path.stem,
        datastore_access=[(e, d) for e, d in data["datastore_access"]]
        if "datastore_access" in data
        else None,
    )
    return r, data["expected"]


# Two triangles joined by one bridge (c - d): the textbook two-community graph.
TWO_TRIANGLES = (
    ("a", "b"),
    ("b", "c"),
    ("c", "a"),
    ("d", "e"),
    ("e", "f"),
    ("f", "d"),
    ("c", "d"),
)
