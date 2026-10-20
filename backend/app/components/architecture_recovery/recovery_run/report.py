"""One release's recovery, as the page that explains it needs it.

Author: Imadh Ifham
Date: 2026-10-20
Description:
    Two documents answer "how was this recovered". The run record says what
    each stage did and how long it took; the artifacts say what came out. They
    are read together here, and the result is one answer keyed to the release
    the caller asked about - not to the moment somebody happened to run it.

    **What the architecture summary counts is recovery's output.** It is read
    from the artifacts recovery wrote, never from the published validated
    graph, so a release that was later judged still reports the architecture
    that was recovered rather than a version another stage has since touched.
"""

import json
from pathlib import Path

from app.domain.architecture_snapshot import ArchitectureSnapshot

from .models import RECOVERY_RUN_FILE, artifact_present, read_run
from .pipeline import (
    ARTIFACT_DEPENDENCY,
    ARTIFACT_DISCOVERY,
    ARTIFACT_INVENTORY,
    RECOVERY_STAGES,
)

ARTIFACTS = (
    ("repository_inventory", ARTIFACT_INVENTORY),
    ("manifest_analysis", "manifest_analysis.json"),
    ("component_discovery", ARTIFACT_DISCOVERY),
    ("dependency_resolution", ARTIFACT_DEPENDENCY),
    ("source_code_analysis", "source_code_analysis.json"),
    ("graph_construction", "architecture_graph_construction.json"),
    ("recovery_run", RECOVERY_RUN_FILE),
)


def build_report(snapshot: ArchitectureSnapshot, directory: Path | None) -> dict:
    """Return the recovery report for one snapshot."""

    run = read_run(directory)
    artifacts = _artifacts(directory)
    documents = _load(directory)

    return {
        "repository_id": snapshot.repository_id,
        "release_id": snapshot.release.release_id,
        "snapshot_id": snapshot.snapshot_id,
        "commit_sha": snapshot.release.commit_sha,
        "branch": snapshot.release.branch_name,
        "repository_url": snapshot.release.repository_url,
        "released_at": snapshot.release.to_dict().get("release_date"),
        "snapshot_status": snapshot.status.value,
        "recorded": run is not None,
        "run": run,
        # The pipeline as the backend describes it, so the page renders the
        # order, purpose and artifact of each stage rather than keeping a copy
        # that goes stale the first time a stage changes.
        "pipeline": [stage.to_dict() for stage in RECOVERY_STAGES],
        "artifacts": artifacts,
        "architecture": _architecture(snapshot, documents),
        "summary": _summary(run, artifacts, snapshot),
    }


def _load(directory: Path | None) -> dict[str, dict]:
    """Read the artifacts a summary is computed from, skipping what is absent."""

    documents: dict[str, dict] = {}

    if directory is None:
        return documents

    for name, filename in (
        ("inventory", ARTIFACT_INVENTORY),
        ("discovery", ARTIFACT_DISCOVERY),
        ("dependency", ARTIFACT_DEPENDENCY),
        ("source", "source_code_analysis.json"),
    ):
        path = directory / filename

        if not path.is_file():
            continue

        try:
            documents[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

    return documents


def _artifacts(directory: Path | None) -> list[dict]:
    """Which artifacts this release's recovery left on disk."""

    return [
        {
            "name": name,
            "file": filename,
            "present": artifact_present(directory, filename),
        }
        for name, filename in ARTIFACTS
    ]


def _architecture(snapshot: ArchitectureSnapshot, documents: dict[str, dict]) -> dict:
    """What the recovered architecture contains, from recovery's own output."""

    inventory = documents.get("inventory") or {}
    discovery = documents.get("discovery") or {}
    dependency = documents.get("dependency") or {}
    source = documents.get("source") or {}

    by_component_type = (discovery.get("summary") or {}).get("by_type") or {}
    by_language = (inventory.get("summary") or {}).get("by_language") or {}
    by_relationship_type = (dependency.get("summary") or {}).get("by_type") or {}
    dependency_summary = dependency.get("summary") or {}
    source_summary = source.get("summary") or {}

    return {
        "element_count": snapshot.element_count,
        "relationship_count": snapshot.relationship_count,
        "confirmed_by_source": sum(
            1 for edge in snapshot.relationships if edge.confirmed_by_source
        ),
        "by_component_type": by_component_type,
        "by_language": by_language,
        "by_relationship_type": by_relationship_type,
        "resolved_dependencies": dependency_summary.get("resolved_relationship_count", 0),
        "unresolved_dependencies": dependency_summary.get("unresolved_count", 0),
        "ambiguous_dependencies": dependency_summary.get("ambiguous_count", 0),
        "by_finding_type": source_summary.get("by_finding_type") or {},
        "source_file_count": source_summary.get("source_file_count", 0),
        "unresolved_references": [item.to_dict() for item in snapshot.unresolved],
        "diagnostics": list(snapshot.diagnostics),
        "missing_inputs": list(snapshot.missing_inputs),
        "notes": list(snapshot.notes),
    }


def _summary(
    run: dict | None, artifacts: list[dict], snapshot: ArchitectureSnapshot
) -> dict:
    """The one-line numbers at the top of the page.

    Read from the run record when there is one. When there is not - a release
    analysed before records existed, or one whose clone is gone - the stage
    counts are null rather than zero, because zero completed stages and an
    unknown number of them are different facts.
    """

    stages = (run or {}).get("stages") or []

    return {
        "stage_count": (run or {}).get("stage_count"),
        "completed": _count(stages, "completed") if run else None,
        "skipped": _count(stages, "skipped") if run else None,
        "failed": _count(stages, "failed") if run else None,
        "duration_ms": (run or {}).get("duration_ms"),
        "element_count": snapshot.element_count,
        "relationship_count": snapshot.relationship_count,
        "artifact_count": sum(1 for item in artifacts if item["present"]),
        "warning_count": (
            sum(len(stage.get("warnings") or []) for stage in stages) if run else None
        ),
        "unresolved_count": len(snapshot.unresolved),
    }


def _count(stages: list[dict], status: str) -> int:
    return sum(1 for stage in stages if stage.get("status") == status)


__all__ = ["ARTIFACTS", "build_report"]
