"""C2's published graph -> a ``ReleasePackageV1.1`` payload (pure).

C2 hands on one node-link document per validated release (``latest.graph.json``, written by
``graph_publishing``). C3's only door is a release package, so this turns the first into the
second and nothing more: the payload goes through ``IngestService`` like any file would, and is
validated, hashed and gated there.

What is carried, and why:

- every node that is not a datastore becomes an element, with its size and kind. Datastores
  are not elements of the graph C3 measures (see ``SharedPersistence``); an edge into one becomes
  a ``datastore_access`` row instead, named by the datastore, so SharedPersistence can run;
- every other edge becomes a dependency, **whatever its verdict**. A contradicted dependency is
  one the architecture should not have, and it still exists: dropping it would hide exactly the
  coupling degradation detection is looking for. The verdict is C2's finding, not C3's input;
- ``validation_confidence`` is carried as published, so the M1 gate decides what a weak
  validation means, not this adapter;
- C2's run id and C1's model reference travel as provenance, so an event can be traced back to
  the validation and the recovery it came from.

A release with no date is refused rather than given one (``RELEASE_UNDATED``): the timeline is
ordered by date, and an invented date is an invented position in every series.
"""

from collections.abc import Mapping
from typing import Any

from app.domain.release_package import SCHEMA_VERSION, ArchitectureStyle

RELEASE_UNDATED = "RELEASE_UNDATED"
GRAPH_UNREADABLE = "GRAPH_UNREADABLE"

DATASTORE_KIND = "datastore"
GRANULARITY = "component"

# C2's style names (recovery's enum) -> C3's. Anything else, "unknown" included, is generic:
# the universal detectors still run, and no style-specific one runs on a guess.
_STYLES = {
    "microservices": ArchitectureStyle.MICROSERVICES,
    "monolith": ArchitectureStyle.MONOLITH,
    "layered": ArchitectureStyle.LAYERED,
    "event-driven": ArchitectureStyle.EVENT_DRIVEN,
    "event_driven": ArchitectureStyle.EVENT_DRIVEN,
}


class UnconvertibleGraph(ValueError):
    """A published graph that cannot become a release package; ``reason`` is a reason code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def package_from_validated(document: Mapping[str, Any]) -> dict[str, Any]:
    """The release package payload for one published C2 graph.

    Raises ``UnconvertibleGraph`` when the document is not a node-link graph or has no date.
    Shape errors inside the package (a dangling edge, a duplicate id) are left for ingestion to
    reject with its own reason codes.
    """
    graph = document.get("graph")
    nodes = document.get("nodes")
    links = document.get("links")
    if not isinstance(graph, Mapping) or not isinstance(nodes, list) or not isinstance(links, list):
        raise UnconvertibleGraph(GRAPH_UNREADABLE, "expected a node-link document")

    release_id = str(graph.get("release_id") or "")
    released_at = graph.get("released_at")
    if not released_at:
        raise UnconvertibleGraph(
            RELEASE_UNDATED, f"{release_id or '<release>'} was published without a release date"
        )

    datastores = {
        str(node["id"]): str(node.get("name") or node["id"])
        for node in nodes
        if node.get("kind") == DATASTORE_KIND
    }
    elements = [_element(node) for node in nodes if str(node["id"]) not in datastores]

    dependencies: list[dict[str, Any]] = []
    access: list[dict[str, Any]] = []
    for link in links:
        source, target = str(link["source"]), str(link["target"])
        if source in datastores:
            continue  # a datastore depending on something is not a service using it
        if target in datastores:
            access.append({"element": source, "datastore": datastores[target], "mode": None})
            continue
        dependencies.append({"from": source, "to": target, "types": _types(link), "count": 1})

    run = graph.get("run")
    return {
        "schema_version": SCHEMA_VERSION,
        "system_id": str(graph.get("repository_id") or ""),
        "release_id": release_id,
        "released_at": released_at,
        "architecture_style": _style(graph.get("architecture_style")),
        "granularity": GRANULARITY,
        "elements": elements,
        "dependencies": dependencies,
        # Always a list: C2 reports every datastore recovery found, so none means none were
        # used, which is a statement SharedPersistence can act on (None would skip it).
        "datastore_access": sorted(access, key=lambda a: (a["datastore"], a["element"])),
        "validation_confidence": graph.get("validation_confidence"),
        "provenance": {
            "c1_model_ref": graph.get("c1_model_ref"),
            "c2_validation_ref": run.get("run_id") if isinstance(run, Mapping) else None,
        },
    }


def _element(node: Mapping[str, Any]) -> dict[str, Any]:
    element: dict[str, Any] = {
        "id": str(node["id"]),
        "name": node.get("name"),
        "kind": node.get("kind"),
        "size": node.get("size"),
        "size_unit": node.get("size_unit"),
    }
    if node.get("canonical"):
        element["extra"] = {"canonical": node["canonical"]}
    return element


def _types(link: Mapping[str, Any]) -> list[str]:
    """How the dependency is made (``grpc``, ``http``...), else what C2 calls the relationship."""
    attributes = link.get("attributes")
    observed = attributes.get("observed_as") if isinstance(attributes, Mapping) else None
    kind = observed or link.get("relationship")
    return [str(kind)] if kind else []


def _style(value: object) -> str:
    return _STYLES.get(str(value or "").lower(), ArchitectureStyle.GENERIC).value
