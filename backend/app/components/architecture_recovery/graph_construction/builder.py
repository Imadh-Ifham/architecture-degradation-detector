"""Snapshot builder.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Turns the recovery stages' evidence into one version-scoped architecture
    snapshot for one analyzed revision.

    The builder is where the three identities are decided:

      * the snapshot id is a hash of the repository, the resolved commit and the
        analysis configuration, so one revision has one snapshot and a rerun
        does not create a second one;
      * an element's `logical_id` is its name key, and only when that key is
        unique inside the release - two components called `paymentservice`
        would otherwise share a history nobody can justify;
      * a logical identity reached from heuristic component evidence is marked
        as such, so a consumer can prefer a direct one.

    It also decides what an edge means. A source-level call that corroborates a
    configured dependency adds evidence to that edge; it does not create a
    second logical dependency between the same pair. A source-level call with
    no configured counterpart becomes a `service_dependency` in its own right,
    because the code observed something the configuration did not.
"""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime

from app.components.architecture_recovery.graph_construction.inputs import (
    DEPENDENCY_STAGE,
    SOURCE_STAGE,
    ComponentRecord,
    DependencyRecord,
    FindingRecord,
    SnapshotInputs,
)
from app.domain.architecture_snapshot import (
    AnalysisRun,
    ArchitectureSnapshot,
    IdentityBasis,
    OrderSource,
    ReleaseMetadata,
    SnapshotElement,
    SnapshotEvidence,
    SnapshotRelationship,
    SnapshotStatus,
    SnapshotUnresolved,
)

GENERATOR_NAME = "graph_construction"
GENERATOR_VERSION = "0.1.0"

#: The analysis configuration that affects what a snapshot contains. Changing
#: any of these changes the snapshot id, because two snapshots built under
#: different rules are not the same historical observation.
CONFIGURATION: dict[str, object] = {
    "model": "evidence-aggregation-v1",
    "size_unit": "files",
    "identity": "normalised-name-v1",
    "edge_aggregation": "logical-dependency-v1",
    "includes_source_code_evidence": True,
}
CONFIGURATION_KEY = hashlib.sha1(
    json.dumps(CONFIGURATION, sort_keys=True).encode("utf-8")
).hexdigest()[:12]

#: What a dependency-resolution relationship type means in the graph.
_DEPENDENCY_KIND: dict[str, str] = {
    "configured_endpoint": "service_dependency",
    "infrastructure_dependency": "infrastructure_dependency",
    "declared_dependency": "declared_dependency",
    "resource_selection": "resource_selection",
}

#: What a source-level finding type means in the graph.
_FINDING_KIND: dict[str, str] = {
    "grpc_service_call": "service_dependency",
    "http_service_call": "service_dependency",
    "cache_client_usage": "infrastructure_dependency",
    "database_client_usage": "infrastructure_dependency",
}

_REQUIRED_INPUTS = ("component_discovery", "dependency_resolution")
"""Inputs whose absence leaves nothing to compare across releases."""


class SnapshotBuilder:
    """Builds one architecture snapshot from the upstream evidence."""

    def build(
        self,
        *,
        release: ReleaseMetadata,
        run: AnalysisRun,
        inputs: SnapshotInputs,
    ) -> ArchitectureSnapshot:
        """Build a snapshot for `release` from the projected evidence."""

        order_timestamp, order_source = order_timestamp_for(release, run)
        snapshot_id = snapshot_identity(release, run)
        elements = build_elements(inputs.components, inputs.dependencies)
        relationships = build_relationships(
            snapshot_id, elements, inputs.dependencies, inputs.findings
        )
        missing_optional = tuple(
            name for name in inputs.missing_inputs if name not in _REQUIRED_INPUTS
        )
        notes = (
            (
                "source code evidence is absent; relationships rest on "
                "configuration and deployment declarations only",
            )
            if "source_code_analysis" in missing_optional
            else ()
        )
        # Any missing evidence makes the account incomplete. A release whose
        # source was never analyzed is not a release without source-level
        # calls, and only the status can keep those two apart downstream.
        status = (
            SnapshotStatus.INCOMPLETE
            if inputs.missing_inputs
            else SnapshotStatus.COMPLETE
        )

        return ArchitectureSnapshot(
            snapshot_id=snapshot_id,
            status=status,
            release=release,
            run=run,
            order_timestamp=order_timestamp,
            order_source=order_source,
            elements=elements,
            relationships=relationships,
            unresolved=_unresolved(inputs),
            diagnostics=inputs.diagnostics,
            missing_inputs=inputs.missing_inputs,
            notes=notes,
        )

    def build_failed(
        self,
        *,
        release: ReleaseMetadata,
        run: AnalysisRun,
        error: str,
        inputs: SnapshotInputs | None = None,
    ) -> ArchitectureSnapshot:
        """Build a snapshot that records a failed analysis.

        A failed run is stored rather than skipped. Without it, a release that
        was never analyzed looks exactly like a release whose components were
        removed, and downstream degradation detection cannot tell the two
        apart.
        """

        order_timestamp, order_source = order_timestamp_for(release, run)
        inputs = inputs or SnapshotInputs()

        return ArchitectureSnapshot(
            snapshot_id=snapshot_identity(release, run),
            status=SnapshotStatus.FAILED,
            release=release,
            run=run,
            order_timestamp=order_timestamp,
            order_source=order_source,
            elements=(),
            relationships=(),
            unresolved=_unresolved(inputs),
            diagnostics=(*inputs.diagnostics, error),
            missing_inputs=inputs.missing_inputs,
            notes=(
                "the analysis failed; an absent element is not evidence that the "
                "element was removed",
            ),
        )


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


def snapshot_identity(release: ReleaseMetadata, run: AnalysisRun) -> str:
    """Derive the snapshot id from repository, commit and configuration.

    The policy is **reuse**: the same repository at the same commit under the
    same configuration is one snapshot. Rerunning replaces that snapshot's own
    contents and records the new analysis run; it never creates a second
    history for one revision.

    The commit is used and not the tag, so a tag moved to a new commit produces
    a new snapshot while the original stays exactly as it was analyzed.
    """

    digest = hashlib.sha1(
        "|".join(
            (release.repository_id, release.commit_sha, run.configuration_key)
        ).encode("utf-8")
    ).hexdigest()[:16]

    return f"snapshot:{digest}"


def order_timestamp_for(
    release: ReleaseMetadata, run: AnalysisRun
) -> tuple[datetime, OrderSource]:
    """Place the snapshot on the timeline, saying which field placed it there.

    A publication date is preferred, then the commit date, then the moment the
    analysis ran. The fallback is recorded rather than hidden, because an
    ordering built from analysis timestamps is an ordering of when somebody
    ran a tool.
    """

    if release.release_date is not None:
        return _aware(release.release_date), OrderSource.RELEASE_DATE

    if release.commit_date is not None:
        return _aware(release.commit_date), OrderSource.COMMIT_DATE

    return _aware(run.analysis_timestamp), OrderSource.ANALYSIS_TIMESTAMP


def _unresolved(inputs: SnapshotInputs) -> tuple[SnapshotUnresolved, ...]:
    """Carry every unresolved and ambiguous reference onto the snapshot."""

    return tuple(
        SnapshotUnresolved(
            stage=item.stage,
            status=item.status,
            reference=item.reference,
            reason=item.reason,
        )
        for item in inputs.unresolved
    )


def _aware(value: datetime) -> datetime:
    """Return a timezone-aware timestamp, assuming UTC when none is given."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Elements
# --------------------------------------------------------------------------- #


def build_elements(
    components: tuple[ComponentRecord, ...],
    dependencies: tuple[DependencyRecord, ...],
) -> tuple[SnapshotElement, ...]:
    """Build one element per discovered component."""

    infrastructure = {
        record.target_id: record.infrastructure_kind
        for record in dependencies
        if record.target_class == "infrastructure" and record.infrastructure_kind
    }
    shared_names = Counter(component.name_key for component in components)
    elements: list[SnapshotElement] = []

    for component in components:
        logical_id, basis = _logical_identity(component, shared_names)
        size = float(component.file_count) if component.file_count > 0 else None

        elements.append(
            SnapshotElement(
                id=component.id,
                name=component.name,
                kind=infrastructure.get(component.id) or component.kind,
                identity_basis=basis,
                logical_id=logical_id,
                size=size,
                size_unit="files" if size is not None else None,
                confidence=component.confidence,
                evidence=(
                    SnapshotEvidence(
                        stage="component_discovery",
                        type="component",
                        declared=component.confidence == "direct",
                        count=1,
                        references=(component.id,),
                    ),
                ),
            )
        )

    return tuple(sorted(elements, key=lambda item: item.id))


def _logical_identity(
    component: ComponentRecord, shared_names: Counter
) -> tuple[str | None, IdentityBasis]:
    """Return the cross-release identity of a component, or refuse to give one.

    A name shared by two components in one release names neither of them, so
    neither gets a logical id. Refusing is the only choice that does not merge
    two histories on a guess.
    """

    key = component.name_key

    if not key or shared_names[key] > 1:
        return None, IdentityBasis.UNASSIGNED

    if component.confidence == "direct":
        return key, IdentityBasis.DIRECT

    return key, IdentityBasis.HEURISTIC


# --------------------------------------------------------------------------- #
# Relationships
# --------------------------------------------------------------------------- #


def build_relationships(
    snapshot_id: str,
    elements: tuple[SnapshotElement, ...],
    dependencies: tuple[DependencyRecord, ...],
    findings: tuple[FindingRecord, ...],
) -> tuple[SnapshotRelationship, ...]:
    """Build edges, merging corroborating evidence into one logical dependency."""

    known = {element.id for element in elements}
    drafts: dict[tuple[str, str, str], _EdgeDraft] = {}

    for record in dependencies:
        if not _is_edge(record.source_id, record.target_id, known):
            continue

        kind = _DEPENDENCY_KIND.get(record.type, record.type)
        draft = drafts.setdefault(
            (record.source_id, record.target_id, kind),
            _EdgeDraft(record.source_id, record.target_id, kind),
        )
        draft.add(
            SnapshotEvidence(
                stage=DEPENDENCY_STAGE,
                type=record.type,
                declared=True,
                count=1,
                references=(record.id,),
            )
        )

    for finding in findings:
        if not _is_edge(finding.source_id, finding.target_id, known):
            continue

        kind = _FINDING_KIND.get(finding.type)

        if kind is None:
            continue

        draft = drafts.setdefault(
            (finding.source_id, finding.target_id, kind),
            _EdgeDraft(finding.source_id, finding.target_id, kind),
        )
        draft.confirmed_by_source = True
        draft.add(
            SnapshotEvidence(
                stage=SOURCE_STAGE,
                type=finding.type,
                declared=finding.evidence_strength == "observed_invocation",
                count=1,
                references=(finding.id,),
            )
        )

    return tuple(
        sorted(
            (
                SnapshotRelationship(
                    id=relationship_identity(
                        snapshot_id, draft.source_id, draft.target_id, draft.kind
                    ),
                    source_id=draft.source_id,
                    target_id=draft.target_id,
                    kind=draft.kind,
                    confirmed_by_source=draft.confirmed_by_source,
                    evidence=tuple(
                        sorted(
                            draft.evidence.values(),
                            key=lambda item: (item.stage, item.type),
                        )
                    ),
                )
                for draft in drafts.values()
            ),
            key=lambda item: item.id,
        )
    )


def _is_edge(source_id: str, target_id: str, known: set[str]) -> bool:
    """Report whether two ids form an edge inside this snapshot."""

    return (
        source_id in known
        and target_id in known
        and source_id != target_id
    )


class _EdgeDraft:
    """One edge being accumulated from several evidence entries."""

    def __init__(self, source_id: str, target_id: str, kind: str) -> None:
        self.source_id = source_id
        self.target_id = target_id
        self.kind = kind
        self.confirmed_by_source = False
        self.evidence: dict[tuple[str, str], SnapshotEvidence] = {}

    def add(self, evidence: SnapshotEvidence) -> None:
        """Aggregate an evidence entry by stage and type."""

        key = (evidence.stage, evidence.type)
        existing = self.evidence.get(key)

        if existing is None:
            self.evidence[key] = evidence
            return

        self.evidence[key] = SnapshotEvidence(
            stage=existing.stage,
            type=existing.type,
            declared=existing.declared,
            count=existing.count + evidence.count,
            references=tuple(sorted({*existing.references, *evidence.references})),
        )


def relationship_identity(
    snapshot_id: str, source_id: str, target_id: str, kind: str
) -> str:
    """Derive an edge id from the snapshot and the two endpoints.

    Snapshot-scoped on purpose: the same pair in two releases yields two ids,
    so the two observations cannot be mistaken for one edge that was edited.
    """

    digest = hashlib.sha1(
        "|".join((snapshot_id, source_id, target_id, kind)).encode("utf-8")
    ).hexdigest()[:16]

    return f"edge:{digest}"


__all__ = [
    "CONFIGURATION",
    "CONFIGURATION_KEY",
    "GENERATOR_NAME",
    "GENERATOR_VERSION",
    "SnapshotBuilder",
    "build_elements",
    "build_relationships",
    "order_timestamp_for",
    "relationship_identity",
    "snapshot_identity",
]
