"""Target resolution for source-level findings.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Reuses component discovery for component identities and dependency
    resolution for configured endpoint, environment-key and infrastructure
    targets. It does not reparse manifests or recreate endpoint resolution.

    Resolution is conservative: a finding is resolved only when exactly one
    component matches. Otherwise it stays unresolved or ambiguous with the
    original reference preserved.
"""

import re
from dataclasses import dataclass

from app.components.architecture_recovery.component_discovery.models import (
    ComponentDiscoveryReport,
)
from app.components.architecture_recovery.component_discovery.paths import (
    normalize_name,
)
from app.components.architecture_recovery.source_code_analysis.models import (
    FindingType,
)
from app.components.architecture_recovery.source_code_analysis.patterns import (
    ScanResult,
)

_DEPLOYMENT_ALIAS_KINDS = frozenset(
    {
        "compose_service",
        "kubernetes_workload",
        "kubernetes_service",
        "inventory_deployment",
    }
)


@dataclass(frozen=True)
class ComponentRef:
    """A component identity and the names a source finding may reference."""

    id: str
    name: str
    root_path: str | None = None
    inventory_component_id: str | None = None
    aliases: tuple[str, ...] = ()
    normalized_keys: tuple[str, ...] = ()

    @classmethod
    def from_report(
        cls, report: ComponentDiscoveryReport
    ) -> list["ComponentRef"]:
        """Build refs from the typed component discovery report."""

        artifacts = {artifact.id: artifact for artifact in report.artifacts}
        components: list[ComponentRef] = []

        for component in report.components:
            aliases = [
                artifact.name
                for artifact_id in component.artifact_ids
                if (artifact := artifacts.get(artifact_id)) is not None
                and artifact.kind in _DEPLOYMENT_ALIAS_KINDS
                and artifact.name
            ]

            components.append(
                ComponentRef(
                    id=component.id,
                    name=component.name,
                    root_path=component.root_path,
                    inventory_component_id=component.inventory_component_id,
                    aliases=tuple(sorted(set(aliases))),
                    normalized_keys=tuple(sorted(set(component.name_keys))),
                )
            )

        return components

    @classmethod
    def from_document(cls, document: dict) -> list["ComponentRef"]:
        """Build refs from a component-discovery JSON document."""

        artifacts = {
            str(item["id"]): item
            for item in document.get("artifacts") or []
            if isinstance(item, dict) and item.get("id")
        }
        components: list[ComponentRef] = []

        for component in document.get("components") or []:
            if not isinstance(component, dict):
                continue

            aliases = [
                str(artifact["name"])
                for artifact_id in component.get("artifact_ids") or []
                if (artifact := artifacts.get(str(artifact_id))) is not None
                and artifact.get("kind") in _DEPLOYMENT_ALIAS_KINDS
                and artifact.get("name")
            ]

            components.append(
                cls(
                    id=str(component["id"]),
                    name=str(component["name"]),
                    root_path=(
                        str(component["root_path"])
                        if component.get("root_path")
                        else None
                    ),
                    inventory_component_id=(
                        str(component["inventory_component_id"])
                        if component.get("inventory_component_id")
                        else None
                    ),
                    aliases=tuple(sorted(set(aliases))),
                    normalized_keys=tuple(
                        sorted(str(key) for key in component.get("name_keys") or [])
                    ),
                )
            )

        return components


@dataclass(frozen=True)
class DependencyLink:
    """A resolved dependency-resolution relationship projected for this stage."""

    relationship_id: str
    source_component_id: str
    target_component_id: str
    relationship_type: str
    target_class: str
    target_infrastructure_kind: str | None = None
    evidence: tuple[tuple[str | None, str | None], ...] = ()

    @classmethod
    def from_relationship(cls, relationship) -> "DependencyLink":
        """Build a link from a resolved dependency relationship."""

        return cls(
            relationship_id=relationship.id,
            source_component_id=relationship.source_component_id,
            target_component_id=relationship.target_component_id,
            relationship_type=relationship.type.value,
            target_class=relationship.target_class.value,
            target_infrastructure_kind=(
                relationship.target_infrastructure_kind.value
                if relationship.target_infrastructure_kind
                else None
            ),
            evidence=tuple(
                (item.key, item.endpoint) for item in relationship.evidence
            ),
        )

    @classmethod
    def from_document(cls, item: dict) -> "DependencyLink":
        """Build a link from a serialised resolved relationship."""

        return cls(
            relationship_id=str(item["id"]),
            source_component_id=str(item["source_component_id"]),
            target_component_id=str(item["target_component_id"]),
            relationship_type=str(item.get("type") or ""),
            target_class=str(item.get("target_class") or "component"),
            target_infrastructure_kind=(
                str(item["target_infrastructure_kind"])
                if item.get("target_infrastructure_kind")
                else None
            ),
            evidence=tuple(
                (
                    str(evidence["key"]) if evidence.get("key") else None,
                    str(evidence["endpoint"]) if evidence.get("endpoint") else None,
                )
                for evidence in item.get("evidence") or []
                if isinstance(evidence, dict)
            ),
        )


@dataclass(frozen=True)
class DependencyCandidateLink:
    """An unresolved or ambiguous dependency reference projected for this stage."""

    source_component_id: str
    target_reference: str | None
    host: str | None
    candidate_component_ids: tuple[str, ...] = ()
    evidence_keys: tuple[str, ...] = ()

    @classmethod
    def from_candidate(cls, candidate) -> "DependencyCandidateLink":
        """Build a candidate link from a dependency-resolution candidate."""

        return cls(
            source_component_id=candidate.source_component_id,
            target_reference=candidate.target_reference,
            host=candidate.host,
            candidate_component_ids=tuple(candidate.candidate_component_ids),
            evidence_keys=tuple(
                sorted(
                    {
                        item.key
                        for item in candidate.evidence
                        if item.key
                    }
                )
            ),
        )

    @classmethod
    def from_document(cls, item: dict) -> "DependencyCandidateLink":
        """Build a candidate link from a serialised dependency candidate."""

        return cls(
            source_component_id=str(item["source_component_id"]),
            target_reference=(
                str(item["target_reference"])
                if item.get("target_reference")
                else None
            ),
            host=str(item["host"]) if item.get("host") else None,
            candidate_component_ids=tuple(
                str(component_id)
                for component_id in item.get("candidate_component_ids") or []
            ),
            evidence_keys=tuple(
                sorted(
                    {
                        str(evidence["key"])
                        for evidence in item.get("evidence") or []
                        if isinstance(evidence, dict) and evidence.get("key")
                    }
                )
            ),
        )


@dataclass(frozen=True)
class ResolutionResult:
    """The outcome of resolving one raw source reference."""

    target_ids: tuple[str, ...] = ()
    method: str | None = None
    reason: str | None = None
    target_reference: str | None = None


class TargetIndex:
    """Lookup structures over components and dependency-resolution evidence."""

    def __init__(
        self,
        components: list[ComponentRef],
        links: list[DependencyLink],
        candidates: list[DependencyCandidateLink] | None = None,
    ) -> None:
        """Build the alias, endpoint and infrastructure lookups."""

        self._components = {component.id: component for component in components}
        self._aliases: dict[str, set[str]] = {}
        self._host_targets: dict[str, set[str]] = {}
        self._env_key_targets: dict[str, set[str]] = {}
        self._infrastructure_targets: dict[str, list[tuple[str, str | None]]] = {}
        self._dependency_pairs: dict[tuple[str, str], str] = {}
        self._source_configured_targets: dict[str, set[str]] = {}

        for component in components:
            self._add_alias(component.name, component.id)

            for alias in component.aliases:
                self._add_alias(alias, component.id)

            for key in component.normalized_keys:
                self._add_normalized_alias(key, component.id)

        for link in links:
            self._dependency_pairs[
                (link.source_component_id, link.target_component_id)
            ] = link.relationship_id

            if link.relationship_type == "configured_endpoint":
                self._source_configured_targets.setdefault(
                    link.source_component_id, set()
                ).add(link.target_component_id)

            if link.target_class == "infrastructure":
                self._infrastructure_targets.setdefault(
                    link.source_component_id, []
                ).append(
                    (link.target_component_id, link.target_infrastructure_kind)
                )

            for key, endpoint in link.evidence:
                if key:
                    self._env_key_targets.setdefault(key, set()).add(
                        link.target_component_id
                    )

                host = _host_of_endpoint(endpoint)

                if host:
                    self._host_targets.setdefault(host, set()).add(
                        link.target_component_id
                    )

        for candidate in candidates or []:
            if candidate.host:
                self._host_targets.setdefault(
                    _normalize_host(candidate.host), set()
                ).update(candidate.candidate_component_ids)

            for key in candidate.evidence_keys:
                self._env_key_targets.setdefault(key, set()).update(
                    candidate.candidate_component_ids
                )

    def component_name(self, component_id: str | None) -> str | None:
        """Return a component's display name."""

        if not component_id:
            return None

        component = self._components.get(component_id)

        return component.name if component else None

    def resolve_service(
        self, service_reference: str, source_component_id: str
    ) -> ResolutionResult:
        """Resolve a generated gRPC service name to a component."""

        key = normalize_name(service_reference)
        targets = self._aliases.get(key, set())

        if not targets:
            # Generated clients sometimes suffix the type with `Service` or
            # `Stub`; the alias index already normalises punctuation and case.
            for suffix in ("service", "stub", "client"):
                if key.endswith(suffix) and len(key) > len(suffix):
                    targets = self._aliases.get(key[: -len(suffix)], set())

                    if targets:
                        break

        return _result_for_targets(
            targets,
            method="component_alias",
            target_reference=service_reference,
            unresolved_reason=(
                f"service '{service_reference}' does not match any discovered component"
            ),
        )

    def resolve_http(
        self,
        expression: str | None,
        source_component_id: str,
        scan: ScanResult,
        fallback_reference: str | None = None,
    ) -> ResolutionResult:
        """Resolve an HTTP call expression to a component."""

        raw_expression = expression or fallback_reference or ""
        expanded = _expand_expression(raw_expression, scan.assignments)
        reference = fallback_reference or raw_expression or "<unnamed request>"

        host = _host_from_expression(expanded)

        if host:
            targets = self._host_targets.get(host, set()) or self._aliases.get(
                normalize_name(host), set()
            )
            result = _result_for_targets(
                targets,
                method="configured_endpoint_host",
                target_reference=host,
                unresolved_reason=(
                    f"host '{host}' does not match any discovered component"
                ),
            )

            # A literal host is decisive: if it does not match, falling back to
            # the component's only configured endpoint would invent a target.
            return result

        env_keys = _environment_keys_for_expression(expanded, scan)

        if env_keys:
            targets: set[str] = set()
            unresolved_keys: list[str] = []

            for key in sorted(env_keys):
                key_targets = self._env_key_targets.get(key, set())

                if key_targets:
                    targets.update(key_targets)
                else:
                    unresolved_keys.append(key)

            if unresolved_keys:
                return ResolutionResult(
                    reason=(
                        "HTTP call references configuration key(s) "
                        + ", ".join(sorted(unresolved_keys))
                        + " that dependency resolution did not map to a component"
                    ),
                    target_reference=f"env:{next(iter(sorted(unresolved_keys)))}",
                )

            if targets:
                return _result_for_targets(
                    targets,
                    method="configured_env_key",
                    target_reference=(
                        f"env:{','.join(sorted(env_keys))}"
                        if len(env_keys) > 1
                        else f"env:{next(iter(env_keys))}"
                    ),
                    unresolved_reason=None,
                )

        configured = self._source_configured_targets.get(source_component_id, set())

        if len(configured) == 1:
            return ResolutionResult(
                target_ids=(next(iter(configured)),),
                method="single_configured_endpoint",
                target_reference=reference,
            )

        return ResolutionResult(
            reason=(
                "HTTP target is not identifiable from the call site and the "
                "component has no unique configured endpoint"
            ),
            target_reference=reference,
        )

    def resolve_infrastructure(
        self, source_component_id: str, finding_type: FindingType
    ) -> ResolutionResult:
        """Resolve cache or database client usage to a known infrastructure target."""

        expected_kind = {
            FindingType.CACHE_CLIENT_USAGE: "cache",
            FindingType.DATABASE_CLIENT_USAGE: "database",
        }.get(finding_type)

        targets = [
            target
            for target, kind in self._infrastructure_targets.get(
                source_component_id, []
            )
            if expected_kind is None or kind == expected_kind
        ]

        if len(targets) == 1:
            return ResolutionResult(
                target_ids=(targets[0],),
                method="infrastructure_target",
                target_reference=expected_kind or "infrastructure",
            )

        if len(targets) > 1:
            return ResolutionResult(
                target_ids=tuple(sorted(set(targets))),
                method="infrastructure_target",
                target_reference=expected_kind or "infrastructure",
            )

        return ResolutionResult(
            reason=(
                f"no {expected_kind or 'matching'} infrastructure target is known "
                "from dependency resolution"
            ),
            target_reference=expected_kind or "infrastructure",
        )

    def corroborating_relationship(
        self, source_component_id: str, target_component_id: str
    ) -> str | None:
        """Return the dependency-resolution relationship id for a pair, if any."""

        return self._dependency_pairs.get((source_component_id, target_component_id))

    # ------------------------------------------------------------------ #
    # Alias construction
    # ------------------------------------------------------------------ #

    def _add_alias(self, alias: str, component_id: str) -> None:
        """Record an exact alias and its normalised form."""

        key = normalize_name(alias)

        if key:
            self._aliases.setdefault(key, set()).add(component_id)

    def _add_normalized_alias(self, key: str, component_id: str) -> None:
        """Record an already-normalised component name key."""

        if key:
            self._aliases.setdefault(key, set()).add(component_id)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _result_for_targets(
    targets: set[str],
    *,
    method: str,
    target_reference: str,
    unresolved_reason: str | None,
) -> ResolutionResult:
    """Turn a set of candidate target ids into a resolution result."""

    ordered = tuple(sorted(targets))

    if len(ordered) == 1:
        return ResolutionResult(
            target_ids=ordered,
            method=method,
            target_reference=target_reference,
        )

    if len(ordered) > 1:
        return ResolutionResult(
            target_ids=ordered,
            method=method,
            reason="reference matches more than one discovered component",
            target_reference=target_reference,
        )

    return ResolutionResult(
        reason=unresolved_reason or "reference does not match a discovered component",
        target_reference=target_reference,
    )


def _normalize_host(value: str) -> str:
    """Reduce a host or endpoint to a comparable DNS key."""

    host = value.strip().lower()

    if "://" in host:
        host = host.split("://", 1)[1]

    host = host.split("/", 1)[0].split("@", 1)[-1]

    if host.startswith("[") and "]" in host:
        return host.split("]", 1)[0] + "]"

    if ":" in host:
        head, _, tail = host.rpartition(":")

        if tail.isdigit():
            host = head

    return host.rstrip(".")


def _host_of_endpoint(endpoint: str | None) -> str | None:
    """Return the host part of a dependency-resolution endpoint string."""

    if not endpoint:
        return None

    return _normalize_host(endpoint) or None


_HOST_PATTERN = re.compile(r"https?://([^/\s\"'+,]+)", re.IGNORECASE)
_LITERAL_HOST_PORT = re.compile(r"[\"']([A-Za-z0-9][A-Za-z0-9._-]*:\d{1,5})[\"']")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


def _host_from_expression(expression: str) -> str | None:
    """Find a literal host in an HTTP expression."""

    match = _HOST_PATTERN.search(expression)

    if match:
        return _normalize_host(match.group(1))

    match = _LITERAL_HOST_PORT.search(expression)

    if match:
        return _normalize_host(match.group(1))

    return None


def _expand_expression(
    expression: str, assignments: dict[str, str], depth: int = 3
) -> str:
    """Expand a simple variable to its assigned expression."""

    value = expression.strip()

    if depth <= 0:
        return value

    if re.fullmatch(r"[A-Za-z_]\w*", value):
        assigned = assignments.get(value)

        if assigned:
            return _expand_expression(assigned, assignments, depth - 1)

    return value


def _environment_keys_for_expression(
    expression: str, scan: ScanResult
) -> set[str]:
    """Return the environment keys referenced by an expression."""

    keys: set[str] = set()

    for identifier in _IDENTIFIER.findall(expression):
        key = scan.env_keys.get(identifier)

        if key:
            keys.add(key)

    # A component may reference the environment key directly, for example
    # `process.env.FRONTEND_ADDR` or `Configuration["REDIS_ADDR"]`.
    for key in scan.env_keys:
        if key in expression:
            keys.add(scan.env_keys[key])

    return keys


__all__ = [
    "ComponentRef",
    "DependencyCandidateLink",
    "DependencyLink",
    "ResolutionResult",
    "TargetIndex",
]
