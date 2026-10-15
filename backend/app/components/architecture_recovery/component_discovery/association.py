"""Artifact association and component assembly.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Turns resolved identity groups into components, attaches the artifacts each
    component owns, and records everything that could not be resolved.

    Three outcomes are kept strictly apart, because collapsing them would lose
    information a consumer needs:

      * a **component** - artifacts with enough evidence to identify a logical
        unit;
      * an **unresolved artifact** - a real artifact whose component identity
        cannot be determined (a Dockerfile with no build context, a contract with
        no implementation, a directory that is only a directory);
      * an **ambiguous association** - a case where more than one component is
        plausible, so a match is deliberately *not* forced.

    A lone artifact is only promoted to a component when its kind is evidence of
    a component in its own right (a deployment declaration or a source project).
    A lone Dockerfile or API contract is reported as unresolved instead, which is
    what keeps "every directory is a component" and "every Dockerfile is a
    service" from happening.
"""

from dataclasses import dataclass, field

from app.components.architecture_recovery.component_discovery.candidates import (
    COMPOSE_SERVICE,
    DOCKERFILE,
    DIRECTORY_GROUP,
    INVENTORY_DEPLOYMENT,
    KUBERNETES_SERVICE,
    KUBERNETES_WORKLOAD,
    OPENAPI_DOCUMENT,
    PROTOBUF_SERVICE,
    SOURCE_PROJECT,
    Candidate,
)
from app.components.architecture_recovery.component_discovery.identity import (
    IdentityGroup,
)
from app.components.architecture_recovery.component_discovery.models import (
    AmbiguousAssociation,
    ArtifactRole,
    AssociationConfidence,
    Component,
    ComponentArtifact,
    ComponentType,
    DiscoveryEvidence,
    MergeRule,
    UnresolvedArtifact,
    ambiguous_id,
    component_id,
    confidence_for_rule,
    unresolved_id,
    weakest_confidence,
)
from app.components.architecture_recovery.component_discovery.paths import (
    ROOT_DIRECTORY,
    normalize_name,
    shallowest,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    Diagnostic,
    DiagnosticSeverity,
)


#: Kinds that carry no component identity on their own. A lone artifact of one of
#: these is unresolved rather than promoted to a component.
_INSUFFICIENT_ALONE: frozenset[str] = frozenset(
    {DOCKERFILE, PROTOBUF_SERVICE, OPENAPI_DOCUMENT, DIRECTORY_GROUP}
)

#: Kinds whose only valid outcome is attachment to another component. A
#: Kubernetes Service is exposure for a workload, so it must never become a
#: component of its own, whether alone or in a group with other contracts.
_ATTACHMENT_ONLY: frozenset[str] = frozenset({KUBERNETES_SERVICE})

#: Contract kinds. A group made only of these describes an API with no
#: implementation, which is not an application component.
_CONTRACT_KINDS: frozenset[str] = frozenset({PROTOBUF_SERVICE, OPENAPI_DOCUMENT})

#: Deployment kinds for which more than one artifact of the same kind inside one
#: component suggests an over-merge. Kubernetes Services are excluded: a workload
#: legitimately has several, such as a ClusterIP service and an external one.
_SINGULAR_DEPLOYMENT_KINDS: frozenset[str] = frozenset(
    {COMPOSE_SERVICE, KUBERNETES_WORKLOAD, INVENTORY_DEPLOYMENT}
)

#: Preference order for choosing a component's display name: the most explicit
#: declaration wins, because it is the name an operator would recognise.
_NAME_PREFERENCE: tuple[str, ...] = (
    COMPOSE_SERVICE,
    KUBERNETES_WORKLOAD,
    INVENTORY_DEPLOYMENT,
    SOURCE_PROJECT,
    DIRECTORY_GROUP,
    PROTOBUF_SERVICE,
    OPENAPI_DOCUMENT,
)

_ANALYZER = "component_discovery"


@dataclass
class AssemblyResult:
    """Everything association produced for a discovery run."""

    components: list[Component] = field(default_factory=list)
    artifacts: list[ComponentArtifact] = field(default_factory=list)
    unresolved: list[UnresolvedArtifact] = field(default_factory=list)
    ambiguous: list[AmbiguousAssociation] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


class ComponentAssembler:
    """Assembles components from resolved identity groups."""

    def assemble(
        self,
        candidates: list[Candidate],
        groups: list[IdentityGroup],
        orphan_diagnostics: list[Diagnostic] | None = None,
    ) -> AssemblyResult:
        """Return the components, artifacts, and everything unresolved."""

        result = AssemblyResult(diagnostics=list(orphan_diagnostics or []))

        by_artifact_id = {candidate.artifact.id: candidate for candidate in candidates}
        candidate_to_component: dict[str, str] = {}
        # Candidates attached to a resource id rather than by name keys, used to
        # place Kubernetes Services onto the workload they select.
        component_by_resource_id: dict[str, str] = {}

        for group in groups:
            members = [
                by_artifact_id[candidate_id]
                for candidate_id in group.candidate_ids
                if candidate_id in by_artifact_id
            ]

            if not members:
                continue

            kinds = {member.kind for member in members}

            if kinds <= _ATTACHMENT_ONLY:
                # Handled entirely by attachment below: a Service belongs to the
                # workload its selector matched, never to a component of its own.
                continue

            if len(members) == 1 and members[0].kind in _INSUFFICIENT_ALONE:
                result.unresolved.append(self._unresolved(members[0]))
                continue

            if kinds <= _CONTRACT_KINDS:
                # An API surface with no implementation, build or deployment is a
                # contract whose component identity cannot be determined.
                result.unresolved.extend(
                    self._unresolved(member) for member in members
                )
                continue

            component = self._component(members, group)

            result.components.append(component)

            for member in members:
                candidate_to_component[member.artifact.id] = component.id

                if member.artifact.resource_id:
                    component_by_resource_id[member.artifact.resource_id] = component.id

        self._attach_attached_artifacts(candidates, component_by_resource_id, result)
        self._collect_artifacts(candidates, result)

        result.components.sort(key=lambda item: item.id)
        result.artifacts.sort(key=lambda item: item.id)
        result.unresolved.sort(key=lambda item: item.id)
        result.ambiguous.sort(key=lambda item: item.id)

        self._flag_duplicate_identities(result)

        return result

    @staticmethod
    def _flag_duplicate_identities(result: AssemblyResult) -> None:
        """Record components that share a name but resolved to different identities.

        This is the visible outcome of refusing to merge on a name alone: two
        projects called `frontend` stay separate, and the conflict is reported
        rather than hidden.
        """

        by_name: dict[str, list[Component]] = {}

        for component in result.components:
            by_name.setdefault(component.name.lower(), []).append(component)

        for name, components in sorted(by_name.items()):
            if len(components) < 2:
                continue

            ids = sorted(component.id for component in components)

            result.diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    message=(
                        f"{len(components)} components share the name '{name}' but "
                        "resolved to different identities: "
                        + ", ".join(
                            component.root_path or "<no location>"
                            for component in components
                        )
                        + "; they were not merged because a shared name alone is "
                        "not evidence of one component"
                    ),
                    path=components[0].root_path or components[0].id,
                    analyzer=_ANALYZER,
                )
            )

            for component in components[1:]:
                result.ambiguous.append(
                    AmbiguousAssociation(
                        id=ambiguous_id("duplicate_identity", name, component.id),
                        kind="duplicate_identity",
                        name=name,
                        path=component.root_path or component.id,
                        candidate_component_ids=ids,
                        reason=(
                            "another component already carries this name, so this "
                            "identity is not unique in the repository"
                        ),
                    )
                )

    # ------------------------------------------------------------------ #
    # Component assembly
    # ------------------------------------------------------------------ #

    def _component(self, members: list[Candidate], group: IdentityGroup) -> Component:
        """Build one component from the candidates that resolved together."""

        name, name_key = _display_name(members)
        root_path = _root_path(members)
        component_type = _component_type(members)
        confidence = weakest_confidence(
            [member.artifact.confidence for member in members]
            + [decision.confidence for decision in group.decisions]
        )

        evidence = self._merge_evidence(group)

        # One grounding fact per artifact kind, so the component explains what
        # evidence exists even when no merge was needed to create it.
        for kind in sorted({member.kind for member in members}):
            member = next(item for item in members if item.kind == kind)

            if member.artifact.evidence:
                evidence.append(member.artifact.evidence[0])

        files = sum(
            int(member.artifact.attributes.get("file_count") or 0)
            for member in members
            if member.kind == SOURCE_PROJECT
        )

        component = Component(
            id=component_id(name_key, root_path),
            name=name,
            type=component_type,
            confidence=confidence,
            root_path=root_path,
            languages=_languages(members),
            file_count=files,
            inventory_component_id=_inventory_component_id(members),
            artifact_ids=sorted(member.artifact.id for member in members),
            name_keys=sorted({key for member in members for key in member.keys}),
            evidence=evidence,
        )

        component.diagnostics.extend(self._component_diagnostics(members, group))

        return component

    @staticmethod
    def _merge_evidence(group: IdentityGroup) -> list[DiscoveryEvidence]:
        """Collapse a group's merge decisions into one entry per rule and reason.

        Identity resolution evaluates every pair, so a component holding several
        copies of the same contract produces many decisions that say the same
        thing. Collapsing them keeps the evidence readable and the report small
        while still recording how many pairs each rule connected.
        """

        counts: dict[tuple[str, str], int] = {}

        for decision in group.decisions:
            key = (decision.rule.value, decision.detail)
            counts[key] = counts.get(key, 0) + 1

        evidence: list[DiscoveryEvidence] = []

        for (rule, detail), count in sorted(counts.items()):
            suffix = f" ({count} artifact pairs)" if count > 1 else ""

            evidence.append(
                DiscoveryEvidence(
                    source="component_discovery",
                    type="merge_rule",
                    detail=f"{detail}{suffix}",
                    confidence=confidence_for_rule(MergeRule(rule)),
                    rule=MergeRule(rule),
                )
            )

        return evidence

    def _component_diagnostics(
        self, members: list[Candidate], group: IdentityGroup
    ) -> list[Diagnostic]:
        """Return the diagnostics explaining what is uncertain about a component."""

        diagnostics: list[Diagnostic] = []
        deployments = [member for member in members if member.is_deployment]
        kinds = [member.kind for member in deployments]

        # Two deployment declarations of the same kind inside one component is the
        # signature of an over-merge: two services that were not distinguished.
        for kind in sorted(set(kinds)):
            if kind not in _SINGULAR_DEPLOYMENT_KINDS:
                continue

            if kinds.count(kind) > 1:
                paths = sorted(
                    member.artifact.path
                    for member in deployments
                    if member.kind == kind
                )
                diagnostics.append(
                    Diagnostic(
                        severity=DiagnosticSeverity.WARNING,
                        message=(
                            f"{kinds.count(kind)} '{kind}' declarations were merged "
                            f"into one component ({', '.join(paths)}); this may be "
                            "an over-merge"
                        ),
                        path=paths[0],
                        analyzer=_ANALYZER,
                    )
                )

        if not deployments and not any(member.is_project for member in members):
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    message=(
                        "component has neither deployment nor source-project "
                        "evidence; its identity is unresolved"
                    ),
                    path=members[0].artifact.path,
                    analyzer=_ANALYZER,
                )
            )

        heuristic_rules = sorted(
            {
                decision.rule.value
                for decision in group.decisions
                if decision.confidence is AssociationConfidence.HEURISTIC
            }
        )

        if heuristic_rules:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.INFO,
                    message=(
                        "component is held together by heuristic evidence: "
                        + ", ".join(heuristic_rules)
                    ),
                    path=members[0].artifact.path,
                    analyzer=_ANALYZER,
                )
            )

        if all(member.kind == DIRECTORY_GROUP for member in members):
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    message=(
                        "component rests on directory grouping alone, which is not "
                        "evidence of a service boundary"
                    ),
                    path=members[0].artifact.path,
                    analyzer=_ANALYZER,
                )
            )

        return diagnostics

    # ------------------------------------------------------------------ #
    # Artifacts attached by resource id
    # ------------------------------------------------------------------ #

    def _attach_attached_artifacts(
        self,
        candidates: list[Candidate],
        component_by_resource_id: dict[str, str],
        result: AssemblyResult,
    ) -> None:
        """Place artifacts that reference a component by resource id.

        A Kubernetes Service selects a workload rather than declaring a name of
        its own, so it is attached to the workload's component. When a Service
        matches workloads in more than one component the association is reported
        as ambiguous instead of being forced.
        """

        for candidate in candidates:
            if not candidate.attached_to_resource_ids:
                continue

            targets = sorted(
                {
                    component_by_resource_id[resource_id]
                    for resource_id in candidate.attached_to_resource_ids
                    if resource_id in component_by_resource_id
                }
            )

            if not targets:
                result.unresolved.append(
                    UnresolvedArtifact(
                        id=unresolved_id(
                            candidate.kind,
                            candidate.artifact.path,
                            candidate.artifact.name,
                        ),
                        kind=candidate.kind,
                        name=candidate.artifact.name,
                        path=candidate.artifact.path,
                        line=candidate.artifact.line,
                        resource_id=candidate.artifact.resource_id,
                        reason=(
                            "the service selector matched no workload that belongs "
                            "to a component"
                        ),
                        evidence=list(candidate.artifact.evidence),
                    )
                )
                continue

            if len(targets) > 1:
                result.ambiguous.append(
                    AmbiguousAssociation(
                        id=ambiguous_id(
                            candidate.kind,
                            candidate.artifact.path,
                            candidate.artifact.name or candidate.kind,
                        ),
                        kind=candidate.kind,
                        name=candidate.artifact.name or candidate.kind,
                        path=candidate.artifact.path,
                        line=candidate.artifact.line,
                        candidate_component_ids=targets,
                        reason=(
                            "the service selector matches workloads in more than one "
                            "component, so it cannot be attached unambiguously"
                        ),
                        evidence=list(candidate.artifact.evidence),
                    )
                )
                continue

            component = next(
                (item for item in result.components if item.id == targets[0]), None
            )

            if component is None:
                continue

            component.artifact_ids = sorted(
                {*component.artifact_ids, candidate.artifact.id}
            )
            component.evidence.append(
                DiscoveryEvidence(
                    source="component_discovery",
                    type="attached_artifact",
                    detail=(
                        f"'{candidate.artifact.name}' exposes this component's "
                        "workload and is not a separate component"
                    ),
                    confidence=AssociationConfidence.DIRECT,
                    path=candidate.artifact.path,
                    line=candidate.artifact.line,
                    resource_id=candidate.artifact.resource_id,
                )
            )

    def _collect_artifacts(
        self, candidates: list[Candidate], result: AssemblyResult
    ) -> None:
        """Collect the flat artifact list from the components that own them.

        Components are the authority after attachment has run, so the report has
        exactly one artifact record per associated artifact and every id a
        component references exists in the list.
        """

        by_artifact_id = {candidate.artifact.id: candidate for candidate in candidates}
        placed: set[str] = set()

        for component in result.components:
            for artifact_id_value in component.artifact_ids:
                if artifact_id_value in placed:
                    continue

                candidate = by_artifact_id.get(artifact_id_value)

                if candidate is None:
                    continue

                placed.add(artifact_id_value)
                result.artifacts.append(candidate.artifact)

    # ------------------------------------------------------------------ #
    # Unresolved
    # ------------------------------------------------------------------ #

    @staticmethod
    def _unresolved(candidate: Candidate) -> UnresolvedArtifact:
        """Return the unresolved record for a lone artifact."""

        reasons = {
            DOCKERFILE: (
                "no build context, source project or deployment could be associated "
                "with this Dockerfile, so its component identity is undetermined"
            ),
            PROTOBUF_SERVICE: (
                "no deployment, source project or build context could be associated "
                "with this protobuf service"
            ),
            OPENAPI_DOCUMENT: (
                "no deployment, source project or build context could be associated "
                "with this API specification"
            ),
            DIRECTORY_GROUP: (
                "directory structure alone is not evidence of a component boundary"
            ),
        }

        return UnresolvedArtifact(
            id=unresolved_id(
                candidate.kind, candidate.artifact.path, candidate.artifact.name
            ),
            kind=candidate.kind,
            name=candidate.artifact.name,
            path=candidate.artifact.path,
            line=candidate.artifact.line,
            resource_id=candidate.artifact.resource_id,
            reason=reasons.get(
                candidate.kind, "the artifact could not be associated with a component"
            ),
            evidence=list(candidate.artifact.evidence),
        )


# --------------------------------------------------------------------------- #
# Field selection helpers
# --------------------------------------------------------------------------- #


def _display_name(members: list[Candidate]) -> tuple[str, str]:
    """Choose a component's display name and identity key.

    Policy: prefer the most explicit declaration, and within a kind the
    lexicographically smallest name, so the choice depends only on the set of
    members rather than on the order they were collected in.
    """

    for kind in _NAME_PREFERENCE:
        names = sorted(
            {
                member.artifact.name
                for member in members
                if member.kind == kind and member.artifact.name
            }
        )

        if names:
            return names[0], normalize_name(names[0])

    keys = sorted({key for member in members for key in member.keys})

    if keys:
        return keys[0], keys[0]

    # Nothing named: fall back to the path, which is always present.
    path = sorted(member.artifact.path for member in members)[0]

    return path, normalize_name(path)


def _root_path(members: list[Candidate]) -> str | None:
    """Choose a component's root path from its project locations."""

    roots = [
        member.root_path
        for member in members
        if member.is_project
        and member.root_path
        and member.root_path != ROOT_DIRECTORY
    ]

    return shallowest(roots)


def _component_type(members: list[Candidate]) -> ComponentType:
    """Classify a component from the evidence that composed it."""

    if any(member.is_deployment for member in members):
        return ComponentType.SERVICE

    if any(member.is_project for member in members):
        return ComponentType.APPLICATION

    if any(member.kind in (PROTOBUF_SERVICE, OPENAPI_DOCUMENT) for member in members):
        # A contract with no implementation is not known to be an application.
        return ComponentType.UNKNOWN

    return ComponentType.UNKNOWN


def _languages(members: list[Candidate]) -> list[str]:
    """Return the union of the languages reported for a component's projects."""

    languages: set[str] = set()

    for member in members:
        for language in member.artifact.attributes.get("languages") or []:
            languages.add(str(language))

    return sorted(languages)


def _inventory_component_id(members: list[Candidate]) -> str | None:
    """Return the inventory component id a component corresponds to, if any."""

    candidates = sorted(
        {
            member.artifact.inventory_component_id
            for member in members
            if member.artifact.inventory_component_id
        }
    )

    return candidates[0] if candidates else None


__all__ = [
    "AssemblyResult",
    "ComponentAssembler",
]
