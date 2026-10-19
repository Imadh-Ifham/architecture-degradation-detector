"""Projections of the upstream recovery artifacts.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Reduces the component-discovery, dependency-resolution and source-code
    reports to the handful of facts graph construction needs, so the builder
    never depends on a stage's full document shape and never reparses anything.

    Both a typed report and the serialised document can be projected, because
    the API flow already holds the reports while `run_for_ingested` has only
    the files on disk.
"""

from dataclasses import dataclass

from app.components.architecture_recovery.component_discovery.models import (
    ComponentDiscoveryReport,
)
from app.components.architecture_recovery.component_discovery.paths import (
    normalize_name,
)
from app.components.architecture_recovery.dependency_resolution.models import (
    DependencyResolutionReport,
)
from app.components.architecture_recovery.source_code_analysis.models import (
    SourceCodeAnalysisReport,
)

DEPENDENCY_STAGE = "dependency_resolution"
SOURCE_STAGE = "source_code_analysis"


@dataclass(frozen=True)
class ComponentRecord:
    """One discovered component, as graph construction needs it."""

    id: str
    name: str
    kind: str
    confidence: str
    file_count: int = 0
    name_keys: tuple[str, ...] = ()

    @property
    def name_key(self) -> str:
        """The normalised name this component would share across releases."""

        return normalize_name(self.name)


@dataclass(frozen=True)
class DependencyRecord:
    """One resolved dependency-resolution relationship."""

    id: str
    source_id: str
    target_id: str
    type: str
    target_class: str = "component"
    infrastructure_kind: str | None = None


@dataclass(frozen=True)
class FindingRecord:
    """One resolved source-code finding."""

    id: str
    source_id: str
    target_id: str
    type: str
    evidence_strength: str = "observed_invocation"


@dataclass(frozen=True)
class UnresolvedRecord:
    """One unresolved or ambiguous reference from an upstream stage."""

    stage: str
    status: str
    reference: str
    reason: str = ""


@dataclass(frozen=True)
class SnapshotInputs:
    """Everything the builder reads from the upstream stages."""

    components: tuple[ComponentRecord, ...] = ()
    dependencies: tuple[DependencyRecord, ...] = ()
    findings: tuple[FindingRecord, ...] = ()
    unresolved: tuple[UnresolvedRecord, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Typed reports
# --------------------------------------------------------------------------- #


def inputs_from_reports(
    discovery: ComponentDiscoveryReport | None,
    dependencies: DependencyResolutionReport | None,
    source: SourceCodeAnalysisReport | None,
) -> SnapshotInputs:
    """Project the in-memory reports the API flow already holds."""

    missing: list[str] = []

    if discovery is None:
        missing.append("component_discovery")

    if dependencies is None:
        missing.append("dependency_resolution")

    if source is None:
        missing.append("source_code_analysis")

    return SnapshotInputs(
        components=components_from_report(discovery) if discovery else (),
        dependencies=dependencies_from_report(dependencies) if dependencies else (),
        findings=findings_from_report(source) if source else (),
        unresolved=(
            (*unresolved_from_report(dependencies), *unresolved_from_report(source))
        ),
        missing_inputs=tuple(missing),
        diagnostics=(
            *_severity_messages(dependencies.diagnostics if dependencies else ()),
            *_severity_messages(source.diagnostics if source else ()),
        ),
    )


def components_from_report(
    report: ComponentDiscoveryReport,
) -> tuple[ComponentRecord, ...]:
    """Project every discovered component."""

    return tuple(
        ComponentRecord(
            id=component.id,
            name=component.name,
            kind=component.type.value,
            confidence=component.confidence.value,
            file_count=component.file_count,
            name_keys=tuple(component.name_keys),
        )
        for component in sorted(report.components, key=lambda item: item.id)
    )


def dependencies_from_report(
    report: DependencyResolutionReport,
) -> tuple[DependencyRecord, ...]:
    """Project every resolved dependency relationship."""

    return tuple(
        DependencyRecord(
            id=relationship.id,
            source_id=relationship.source_component_id,
            target_id=relationship.target_component_id,
            type=relationship.type.value,
            target_class=relationship.target_class.value,
            infrastructure_kind=(
                relationship.target_infrastructure_kind.value
                if relationship.target_infrastructure_kind
                else None
            ),
        )
        for relationship in sorted(report.relationships, key=lambda item: item.id)
    )


def findings_from_report(
    report: SourceCodeAnalysisReport,
) -> tuple[FindingRecord, ...]:
    """Project every resolved source-code finding."""

    return tuple(
        FindingRecord(
            id=finding.id,
            source_id=finding.source_component_id,
            target_id=finding.target_component_id,
            type=finding.finding_type.value,
            evidence_strength=finding.evidence_strength.value,
        )
        for finding in sorted(report.findings, key=lambda item: item.id)
    )


def unresolved_from_report(report) -> tuple[UnresolvedRecord, ...]:
    """Project the unresolved and ambiguous candidates of a stage report."""

    if report is None:
        return ()

    stage = (
        DEPENDENCY_STAGE
        if isinstance(report, DependencyResolutionReport)
        else SOURCE_STAGE
    )

    return tuple(
        UnresolvedRecord(
            stage=stage,
            status=candidate.status.value,
            reference=candidate.target_reference or "",
            reason=candidate.reason or "",
        )
        for candidate in (*report.unresolved, *report.ambiguous)
    )


def _severity_messages(diagnostics) -> tuple[str, ...]:
    """Keep only the diagnostics a snapshot should carry.

    Info-level observations stay in the upstream report. A snapshot carries
    the warnings and errors, because those are what make it incomplete.
    """

    return tuple(
        f"{item.path + ': ' if item.path else ''}{item.message}"
        for item in diagnostics
        if item.severity.value in ("warning", "error")
    )


# --------------------------------------------------------------------------- #
# Serialised documents
# --------------------------------------------------------------------------- #


def components_from_document(document: dict) -> tuple[ComponentRecord, ...]:
    """Project components from a `component_discovery.json` document."""

    records: list[ComponentRecord] = []

    for item in document.get("components") or []:
        if not isinstance(item, dict):
            continue

        records.append(
            ComponentRecord(
                id=str(item["id"]),
                name=str(item["name"]),
                kind=str(item.get("type") or "unknown"),
                confidence=str(item.get("confidence") or "heuristic"),
                file_count=int(item.get("file_count") or 0),
                name_keys=tuple(str(key) for key in item.get("name_keys") or []),
            )
        )

    return tuple(sorted(records, key=lambda record: record.id))


def dependencies_from_document(document: dict) -> tuple[DependencyRecord, ...]:
    """Project relationships from a `dependency_resolution.json` document."""

    records: list[DependencyRecord] = []

    for item in document.get("relationships") or []:
        if not isinstance(item, dict):
            continue

        records.append(
            DependencyRecord(
                id=str(item["id"]),
                source_id=str(item["source_component_id"]),
                target_id=str(item["target_component_id"]),
                type=str(item.get("type") or ""),
                target_class=str(item.get("target_class") or "component"),
                infrastructure_kind=(
                    str(item["target_infrastructure_kind"])
                    if item.get("target_infrastructure_kind")
                    else None
                ),
            )
        )

    return tuple(sorted(records, key=lambda record: record.id))


def findings_from_document(document: dict) -> tuple[FindingRecord, ...]:
    """Project findings from a `source_code_analysis.json` document."""

    records: list[FindingRecord] = []

    for item in document.get("findings") or []:
        if not isinstance(item, dict):
            continue

        records.append(
            FindingRecord(
                id=str(item["id"]),
                source_id=str(item["source_component_id"]),
                target_id=str(item["target_component_id"]),
                type=str(item.get("finding_type") or ""),
                evidence_strength=str(
                    item.get("evidence_strength") or "observed_invocation"
                ),
            )
        )

    return tuple(sorted(records, key=lambda record: record.id))


def inputs_from_documents(
    component_document: dict,
    dependency_document: dict,
    source_document: dict | None,
) -> SnapshotInputs:
    """Project the serialised artifacts `run_for_ingested` reads from disk."""

    missing = [] if source_document is not None else ["source_code_analysis"]
    unresolved = list(
        unresolved_from_document(DEPENDENCY_STAGE, dependency_document)
    )

    if source_document is not None:
        unresolved.extend(unresolved_from_document(SOURCE_STAGE, source_document))

    return SnapshotInputs(
        components=components_from_document(component_document),
        dependencies=dependencies_from_document(dependency_document),
        findings=(
            findings_from_document(source_document) if source_document else ()
        ),
        unresolved=tuple(unresolved),
        missing_inputs=tuple(missing),
        diagnostics=(
            *_document_diagnostics(component_document),
            *_document_diagnostics(dependency_document),
            *(_document_diagnostics(source_document) if source_document else ()),
        ),
    )


def _document_diagnostics(document: dict) -> tuple[str, ...]:
    """Keep the warning and error diagnostics a document carries."""

    return tuple(
        f"{item.get('path') + ': ' if item.get('path') else ''}{item.get('message', '')}"
        for item in document.get("diagnostics") or []
        if isinstance(item, dict) and item.get("severity") in ("warning", "error")
    )


def unresolved_from_document(
    stage: str, document: dict
) -> tuple[UnresolvedRecord, ...]:
    """Project unresolved and ambiguous candidates of a document."""

    records: list[UnresolvedRecord] = []

    for key in ("unresolved", "ambiguous"):
        for item in document.get(key) or []:
            if not isinstance(item, dict):
                continue

            records.append(
                UnresolvedRecord(
                    stage=stage,
                    status=str(item.get("status") or key[:-1]),
                    reference=str(item.get("target_reference") or ""),
                    reason=str(item.get("reason") or ""),
                )
            )

    return tuple(records)


__all__ = [
    "DEPENDENCY_STAGE",
    "SOURCE_STAGE",
    "ComponentRecord",
    "DependencyRecord",
    "FindingRecord",
    "SnapshotInputs",
    "UnresolvedRecord",
    "components_from_document",
    "components_from_report",
    "dependencies_from_document",
    "dependencies_from_report",
    "findings_from_document",
    "findings_from_report",
    "inputs_from_documents",
    "inputs_from_reports",
    "unresolved_from_document",
    "unresolved_from_report",
]
