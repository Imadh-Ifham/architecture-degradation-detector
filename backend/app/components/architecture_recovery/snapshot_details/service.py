"""Evidence joined from the artifacts recovery wrote, for one snapshot.

Author: Imadh Ifham
Date: 2026-10-20
Description:
    The snapshot a graph store returns is deliberately small: one element per
    component and one edge per dependency, each with the *shape* of the
    evidence behind it. What it cannot carry is the evidence itself - which
    file declared the endpoint, which line in which source file invoked the
    service, what the deployment manifest called the container.

    That evidence has not been thrown away; it is on disk in the artifacts the
    recovery stages wrote beside the clone. This module reads those artifacts
    and joins them onto the snapshot by identifier, so a screen can answer
    "why is this edge here" without a second analysis.

    **Nothing is inferred here except what a finding type already states.** A
    source finding typed `http_service_call` is a call made over HTTP; that is
    what the type means, not a guess from a port number. A relationship with
    no declared protocol and no typed source finding reports no protocol,
    because a dependency between two components does not prove they speak at
    all, and a port does not prove what runs on it.

    Every artifact is optional. A snapshot whose dependency resolution failed
    still describes its components, and a detail document that refused to be
    built without all four would be one that reported nothing about a release
    it could partly explain.
"""

import json
from pathlib import Path

from app.domain.architecture_snapshot import ArchitectureSnapshot

INVENTORY_FILE = "repository_inventory.json"
MANIFEST_FILE = "manifest_analysis.json"
DISCOVERY_FILE = "component_discovery.json"
DEPENDENCY_FILE = "dependency_resolution.json"
SOURCE_FILE = "source_code_analysis.json"

ARTIFACTS = (
    ("inventory", INVENTORY_FILE),
    ("manifest_analysis", MANIFEST_FILE),
    ("component_discovery", DISCOVERY_FILE),
    ("dependency_resolution", DEPENDENCY_FILE),
    ("source_code_analysis", SOURCE_FILE),
)

#: A source finding's type *is* the protocol it observed. `http_service_call`
#: is a call made over HTTP because that is what the extractor matched, and
#: `grpc_service_call` likewise - so this is a restatement of the finding, not
#: an inference from surrounding evidence.
PROTOCOL_BY_FINDING = {
    "http_service_call": "http",
    "grpc_service_call": "grpc",
}

#: What the protocol rests on, strongest first. Reported beside the value so a
#: reader knows whether it was written down or observed.
PROTOCOL_DECLARED = "declared"
PROTOCOL_SOURCE = "source"
PROTOCOL_UNKNOWN = "unknown"


class SnapshotDetails:
    """Reads the artifacts beside a clone and joins them onto one snapshot."""

    def __init__(self, artifacts_directory: Path | None) -> None:
        """Bind the projection to the directory the stages wrote into.

        `None` means the clone is gone - the artifacts with it. The document
        is still built, and says which artifacts it could not read, because a
        snapshot outlives the working tree it was taken from.
        """

        self._directory = Path(artifacts_directory) if artifacts_directory else None

    def build(self, snapshot: ArchitectureSnapshot) -> dict:
        """Return the evidence document for one snapshot."""

        documents, available = self._load()

        inventory = documents.get("inventory") or {}
        discovery = documents.get("component_discovery") or {}
        dependencies = documents.get("dependency_resolution") or {}
        source = documents.get("source_code_analysis") or {}

        files = _index_by(inventory.get("files") or [], "component_id")
        inventory_components = {
            item["id"]: item for item in inventory.get("components") or []
        }
        discovery_components = {
            item["id"]: item for item in discovery.get("components") or []
        }
        artifacts = {
            item["id"]: item for item in discovery.get("artifacts") or []
        }
        resolved = {
            item["id"]: item for item in dependencies.get("relationships") or []
        }
        findings = {item["id"]: item for item in source.get("findings") or []}

        return {
            "snapshot_id": snapshot.snapshot_id,
            "repository_id": snapshot.repository_id,
            "release_id": snapshot.release.release_id,
            "artifacts": available,
            "elements": [
                self._element(
                    element,
                    discovery_components,
                    artifacts,
                    inventory_components,
                    files,
                )
                for element in snapshot.elements
            ],
            "relationships": [
                self._relationship(edge, resolved, findings)
                for edge in snapshot.relationships
            ],
        }

    # ------------------------------------------------------------------ #

    def _load(self) -> tuple[dict[str, dict], list[dict]]:
        """Read every artifact that is present, and report which were."""

        documents: dict[str, dict] = {}
        available: list[dict] = []

        for name, filename in ARTIFACTS:
            path = self._directory / filename if self._directory else None
            present = path is not None and path.is_file()

            if present:
                try:
                    documents[name] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    # A half-written artifact is an absent one; the document
                    # says so rather than failing the whole request.
                    present = False

            available.append(
                {
                    "name": name,
                    "file": filename,
                    "present": present,
                }
            )

        return documents, available

    def _element(
        self,
        element,
        discovery_components: dict[str, dict],
        artifacts: dict[str, dict],
        inventory_components: dict[str, dict],
        files: dict[str, list[dict]],
    ) -> dict:
        """One element, with what discovery and the inventory said about it."""

        component = discovery_components.get(element.id) or {}
        inventory_component = inventory_components.get(
            component.get("inventory_component_id") or ""
        ) or {}
        inventory_id = component.get("inventory_component_id") or ""

        associated = files.get(inventory_id, []) if inventory_id else []
        source_files = [
            item for item in associated if item.get("category") == "source_code"
        ]

        return {
            "id": element.id,
            "name": element.name,
            "kind": element.kind,
            "logical_id": element.logical_id,
            "identity_basis": element.identity_basis.value,
            "size": element.size,
            "size_unit": element.size_unit,
            "confidence": element.confidence,
            # Extracted: what discovery concluded, and from what.
            "detected": {
                "type": component.get("type"),
                "method": _detection_method(component),
                "confidence": component.get("confidence"),
                "root_path": component.get("root_path"),
                "languages": component.get("languages") or [],
                "file_count": component.get("file_count"),
                "inventory_kind": inventory_component.get("kind"),
                "inventory_confidence": inventory_component.get("confidence"),
            },
            # Extracted: the artifacts that identified it, and what each said.
            "artifacts": [
                _artifact(artifacts.get(artifact_id))
                for artifact_id in component.get("artifact_ids") or []
                if artifact_id in artifacts
            ],
            "discovery_evidence": component.get("evidence") or [],
            "snapshot_evidence": [item.to_dict() for item in element.evidence],
            # Extracted: the files the inventory attributed to the component.
            "files": associated,
            "source_file_count": len(source_files),
            "languages": sorted(
                {
                    item["language"]
                    for item in source_files
                    if item.get("language")
                }
            ),
        }

    def _relationship(
        self,
        edge,
        resolved: dict[str, dict],
        findings: dict[str, dict],
    ) -> dict:
        """One edge, with the resolution and source evidence behind it."""

        referenced = [
            reference
            for item in edge.evidence
            for reference in item.references
        ]
        resolution = next(
            (resolved[item] for item in referenced if item in resolved), None
        )
        sources = [findings[item] for item in referenced if item in findings]

        protocols, protocol_source = _protocol(resolution, sources)

        return {
            "id": edge.id,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "kind": edge.kind,
            "confirmed_by_source": edge.confirmed_by_source,
            "protocols": protocols,
            "protocol_source": protocol_source,
            "endpoints": (resolution or {}).get("endpoints") or [],
            "ports": (resolution or {}).get("ports") or [],
            "resolution": {
                "type": (resolution or {}).get("type"),
                "confidence": (resolution or {}).get("confidence"),
                "status": (resolution or {}).get("status"),
                "method": (resolution or {}).get("resolution_method"),
                "target_class": (resolution or {}).get("target_class"),
                "target_infrastructure_kind": (resolution or {}).get(
                    "target_infrastructure_kind"
                ),
            }
            if resolution
            else None,
            "declared_evidence": (resolution or {}).get("evidence") or [],
            "source_evidence": [
                evidence
                for finding in sources
                for evidence in finding.get("evidence") or []
            ],
            "source_findings": [
                {
                    "id": finding.get("id"),
                    "type": finding.get("finding_type"),
                    "strength": finding.get("evidence_strength"),
                    "language": finding.get("language"),
                    "target_reference": finding.get("target_reference"),
                }
                for finding in sources
            ],
            "snapshot_evidence": [item.to_dict() for item in edge.evidence],
        }


def _index_by(records: list[dict], key: str) -> dict[str, list[dict]]:
    """Group records by one field, keeping the fields a screen shows."""

    grouped: dict[str, list[dict]] = {}

    for record in records:
        value = record.get(key)

        if not value:
            continue

        grouped.setdefault(value, []).append(
            {
                "path": record.get("path"),
                "name": record.get("name"),
                "category": record.get("category"),
                "language": record.get("language"),
                "format": record.get("format"),
                "size_bytes": record.get("size_bytes"),
            }
        )

    return {
        key_: sorted(items, key=lambda item: item["path"] or "")
        for key_, items in grouped.items()
    }


def _artifact(artifact: dict | None) -> dict:
    """One discovery artifact, reduced to what a reader needs."""

    if artifact is None:
        return {}

    return {
        "id": artifact.get("id"),
        "role": artifact.get("role"),
        "kind": artifact.get("kind"),
        "path": artifact.get("path"),
        "name": artifact.get("name"),
        "line": artifact.get("line"),
        "confidence": artifact.get("confidence"),
        "evidence": artifact.get("evidence") or [],
    }


def _detection_method(component: dict) -> str | None:
    """How discovery identified this component, in its own words.

    The rules that fired are recorded per component; they are the method, so
    they are reported as the method rather than paraphrased into a score.
    """

    rules = [
        item.get("rule")
        for item in component.get("evidence") or []
        if item.get("rule")
    ]

    if rules:
        return ", ".join(sorted(set(rules)))

    return (component.get("evidence") or [{}])[0].get("type")


def _protocol(
    resolution: dict | None, findings: list[dict]
) -> tuple[list[str], str]:
    """The protocols this relationship is evidenced to use, and what proves them.

    A declared endpoint protocol is authoritative and wins: a manifest saying
    `tcp` is a statement about the transport, where a source finding saying
    `http_service_call` is a statement about the call. Both are reported when
    they disagree, in that order, and the source is labelled `declared`
    because at least one protocol was written down.
    """

    declared = [item for item in (resolution or {}).get("protocols") or [] if item]

    if declared:
        return sorted(set(declared)), PROTOCOL_DECLARED

    observed = sorted(
        {
            PROTOCOL_BY_FINDING[finding.get("finding_type")]
            for finding in findings
            if finding.get("finding_type") in PROTOCOL_BY_FINDING
        }
    )

    if observed:
        return observed, PROTOCOL_SOURCE

    return [], PROTOCOL_UNKNOWN


__all__ = ["ARTIFACTS", "SnapshotDetails"]
