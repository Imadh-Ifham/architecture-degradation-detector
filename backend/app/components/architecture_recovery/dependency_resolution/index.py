"""Component and target index for dependency resolution.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Projects the component-discovery and manifest-analysis documents into the
    lookup structures dependency resolution needs: resource-to-component
    ownership, explicit deployment aliases, Kubernetes qualified names,
    component ports, infrastructure classification and contract artifacts.

    The index only records what the upstream stages established. A deployment
    alias is an exact name a manifest declares; a component display name or a
    normalised name key is always treated as weaker, inferred evidence.
"""

from dataclasses import dataclass, field

from app.components.architecture_recovery.component_discovery.models import (
    ComponentDiscoveryReport,
)
from app.components.architecture_recovery.component_discovery.paths import (
    normalize_name,
)
from app.components.architecture_recovery.dependency_resolution.errors import (
    DependencyResolutionInputError,
)
from app.components.architecture_recovery.dependency_resolution.models import (
    EvidenceSource,
    InfrastructureKind,
    ResolutionEvidence,
    TargetClass,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    ManifestAnalysisReport,
    ResourceKind,
)

# Artifact roles that prove a component has its own implementation or contract.
_IMPLEMENTED_ROLES = frozenset({"implementation", "definition", "contract"})


# Image families that identify infrastructure rather than an application
# service. Matching uses the final image path segment, so `bitnami/redis` and
# `redis` both count, while a repository name such as `example/redis-client`
# only matches when it is one of the listed families.
_INFRASTRUCTURE_IMAGES: tuple[tuple[tuple[str, ...], InfrastructureKind], ...] = (
    (("redis", "keydb", "memcached"), InfrastructureKind.CACHE),
    (
        (
            "postgres",
            "postgresql",
            "mysql",
            "mariadb",
            "mongo",
            "mongodb",
            "cassandra",
            "couchdb",
            "cockroach",
            "cockroachdb",
            "sqlite",
        ),
        InfrastructureKind.DATABASE,
    ),
    (
        ("rabbitmq", "kafka", "nats", "activemq", "pulsar"),
        InfrastructureKind.MESSAGE_BROKER,
    ),
    (
        ("zookeeper", "elasticsearch", "opensearch", "minio", "vault"),
        InfrastructureKind.INFRASTRUCTURE,
    ),
)


@dataclass(frozen=True)
class ComponentInput:
    """A component as dependency resolution needs to see it."""

    id: str
    name: str
    type: str
    name_keys: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactInput:
    """An artifact associated with a component."""

    id: str
    role: str
    kind: str
    name: str | None = None
    path: str | None = None
    line: int | None = None
    resource_id: str | None = None
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AliasMatch:
    """One component a configured host can identify."""

    component_id: str
    component_name: str
    method: str
    declared: bool
    detail: str
    artifact_id: str | None = None
    path: str | None = None
    line: int | None = None
    resource_id: str | None = None

    def to_evidence(self) -> ResolutionEvidence:
        """Return the target-mapping evidence for this match."""

        return ResolutionEvidence(
            source=EvidenceSource.COMPONENT_DISCOVERY,
            type="target_alias",
            detail=self.detail,
            declared=self.declared,
            path=self.path,
            line=self.line,
            artifact_id=self.artifact_id,
            resource_id=self.resource_id,
            resolution_method=self.method,
        )


@dataclass(frozen=True)
class InfrastructureMatch:
    """An infrastructure classification supported by manifest evidence."""

    kind: InfrastructureKind
    evidence: tuple[ResolutionEvidence, ...]

    @property
    def target_class(self) -> TargetClass:
        """Return the target class implied by the classification."""

        return TargetClass.INFRASTRUCTURE


class ComponentIndex:
    """Lookup structures built from the two upstream reports."""

    def __init__(self) -> None:
        """Initialise an empty index."""

        self._components: dict[str, ComponentInput] = {}
        self._exact: dict[str, list[AliasMatch]] = {}
        self._normalized: dict[str, list[AliasMatch]] = {}
        self._resource_to_component: dict[str, str] = {}
        self._resource_to_artifact: dict[str, ArtifactInput] = {}
        self._component_artifacts: dict[str, list[ArtifactInput]] = {}
        self._component_ports: dict[str, set[int]] = {}
        self._infrastructure: dict[str, InfrastructureMatch] = {}
        self._contracts: dict[str, list[ArtifactInput]] = {}
        self._resources_by_id: dict[str, object] = {}
        self.diagnostics: list[str] = []

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    @classmethod
    def from_report(
        cls, report: ComponentDiscoveryReport, analysis: ManifestAnalysisReport
    ) -> "ComponentIndex":
        """Build the index from the typed component-discovery report."""

        components = [
            ComponentInput(
                id=component.id,
                name=component.name,
                type=component.type.value,
                name_keys=tuple(component.name_keys),
                artifact_ids=tuple(component.artifact_ids),
            )
            for component in report.components
        ]

        artifacts = [
            ArtifactInput(
                id=artifact.id,
                role=artifact.role.value,
                kind=artifact.kind,
                name=artifact.name,
                path=artifact.path,
                line=artifact.line,
                resource_id=artifact.resource_id,
                attributes=dict(artifact.attributes),
            )
            for artifact in report.artifacts
        ]

        return cls.build(components, artifacts, analysis)

    @classmethod
    def from_document(
        cls, document: dict, analysis: ManifestAnalysisReport
    ) -> "ComponentIndex":
        """Build the index from a component-discovery JSON document.

        Used when a caller has only the artifact on disk. The same two lists the
        typed loader provides are validated and projected, never re-derived.
        """

        if not isinstance(document, dict):
            raise DependencyResolutionInputError(
                "The component discovery artifact is not a JSON object."
            )

        raw_components = document.get("components")
        raw_artifacts = document.get("artifacts")

        if not isinstance(raw_components, list) or not isinstance(raw_artifacts, list):
            raise DependencyResolutionInputError(
                "The component discovery artifact must contain 'components' and "
                "'artifacts' lists."
            )

        try:
            components = [
                ComponentInput(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    type=str(item.get("type") or "unknown"),
                    name_keys=tuple(str(key) for key in item.get("name_keys") or []),
                    artifact_ids=tuple(
                        str(artifact_id) for artifact_id in item.get("artifact_ids") or []
                    ),
                )
                for item in raw_components
            ]

            artifacts = [
                ArtifactInput(
                    id=str(item["id"]),
                    role=str(item.get("role") or ""),
                    kind=str(item.get("kind") or ""),
                    name=(str(item["name"]) if item.get("name") else None),
                    path=(str(item["path"]) if item.get("path") else None),
                    line=item.get("line"),
                    resource_id=(
                        str(item["resource_id"]) if item.get("resource_id") else None
                    ),
                    attributes=dict(item.get("attributes") or {}),
                )
                for item in raw_artifacts
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise DependencyResolutionInputError(
                f"The component discovery artifact has an unexpected structure: {error}"
            ) from error

        return cls.build(components, artifacts, analysis)

    @classmethod
    def build(
        cls,
        components: list[ComponentInput],
        artifacts: list[ArtifactInput],
        analysis: ManifestAnalysisReport,
    ) -> "ComponentIndex":
        """Build the index from projected components and artifacts."""

        index = cls()
        index._resources_by_id = {resource.id: resource for resource in analysis.resources}

        artifacts_by_id = {artifact.id: artifact for artifact in artifacts}

        for component in sorted(components, key=lambda item: (item.name, item.id)):
            index._components[component.id] = component

            index._component_artifacts[component.id] = [
                artifacts_by_id[artifact_id]
                for artifact_id in component.artifact_ids
                if artifact_id in artifacts_by_id
            ]

            index._add_alias(
                component.name,
                AliasMatch(
                    component_id=component.id,
                    component_name=component.name,
                    method="component_name",
                    declared=False,
                    detail=(
                        f"configured host matches the display name of component "
                        f"'{component.name}'"
                    ),
                ),
            )

            for key in component.name_keys:
                index._add_normalized_alias(
                    key,
                    AliasMatch(
                        component_id=component.id,
                        component_name=component.name,
                        method="component_name_key",
                        declared=False,
                        detail=(
                            f"configured host matches a normalised name key of "
                            f"component '{component.name}'"
                        ),
                    ),
                )

            for artifact_id in component.artifact_ids:
                artifact = artifacts_by_id.get(artifact_id)

                if artifact is not None:
                    index._add_artifact_alias(component, artifact)

        for component in components:
            for artifact_id in component.artifact_ids:
                artifact = artifacts_by_id.get(artifact_id)

                if artifact is None or not artifact.resource_id:
                    continue

                existing = index._resource_to_component.get(artifact.resource_id)

                if existing is not None and existing != component.id:
                    index.diagnostics.append(
                        f"resource '{artifact.resource_id}' is associated with more than "
                        "one component; the first association wins"
                    )
                    continue

                index._resource_to_component[artifact.resource_id] = component.id
                index._resource_to_artifact.setdefault(artifact.resource_id, artifact)

        index._index_ports(analysis)
        index._index_infrastructure(analysis)
        index._index_contracts(components, artifacts_by_id)

        return index

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #

    def component(self, component_id: str) -> ComponentInput | None:
        """Return a component by id."""

        return self._components.get(component_id)

    def component_for_resource(self, resource_id: str | None) -> str | None:
        """Return the component that owns an analysis resource."""

        if not resource_id:
            return None

        return self._resource_to_component.get(resource_id)

    def artifact_for_resource(self, resource_id: str | None) -> ArtifactInput | None:
        """Return the component artifact that declared a resource."""

        if not resource_id:
            return None

        return self._resource_to_artifact.get(resource_id)

    def component_name(self, component_id: str | None) -> str | None:
        """Return a component's display name."""

        if not component_id:
            return None

        component = self._components.get(component_id)

        return component.name if component else None

    def component_ports(self, component_id: str) -> set[int]:
        """Return the ports the component's deployment declares."""

        return set(self._component_ports.get(component_id, set()))

    def infrastructure(self, component_id: str) -> InfrastructureMatch | None:
        """Return the component's infrastructure classification, if any."""

        return self._infrastructure.get(component_id)

    def contracts(self, component_id: str) -> list[ArtifactInput]:
        """Return the contract artifacts that belong to a component."""

        return list(self._contracts.get(component_id, []))

    def lookup(self, host: str, port: int | None = None) -> tuple[list[AliasMatch], str]:
        """Resolve a configured host to candidate components.

        Returns the candidates and how the lookup was made. A unique candidate
        is still returned with its method so the caller can decide whether the
        mapping is declared or inferred.
        """

        normalized = _normalize_host(host)

        if not normalized:
            return [], "empty"

        if _is_local_host(normalized):
            return [], "local_host"

        method = "exact_alias"
        matches = self._exact.get(normalized, [])

        if not matches:
            matches = self._normalized.get(normalize_name(normalized), [])
            method = "normalized_alias"

        # A host written as `<name>.svc.cluster.local` is still the Kubernetes
        # Service `<name>`; try the first label when no qualified alias matched.
        if not matches and ".svc.cluster.local" in normalized:
            matches = self._exact.get(normalized.split(".", 1)[0], [])
            method = "kubernetes_dns_suffix"

        unique: dict[str, AliasMatch] = {}

        for match in matches:
            current = unique.get(match.component_id)

            # Prefer explicit deployment evidence over a display-name match.
            if current is None or (_rank(match) > _rank(current)):
                unique[match.component_id] = match

        candidates = list(unique.values())

        if len(candidates) > 1 and port is not None:
            compatible = [
                match
                for match in candidates
                if port in self._component_ports.get(match.component_id, set())
            ]

            if len(compatible) == 1:
                return compatible, "host_port_disambiguation"

        return candidates, method

    # ------------------------------------------------------------------ #
    # Alias construction
    # ------------------------------------------------------------------ #

    def _add_artifact_alias(
        self, component: ComponentInput, artifact: ArtifactInput
    ) -> None:
        """Add the explicit names a deployment artifact declares."""

        if not artifact.name:
            return

        name = artifact.name

        if artifact.kind == "compose_service":
            method = "compose_service_alias"
            label = "Compose service"
        elif artifact.kind == "kubernetes_workload":
            method = "kubernetes_workload_alias"
            label = "Kubernetes workload"
        elif artifact.kind == "kubernetes_service":
            method = "kubernetes_service_alias"
            label = "Kubernetes Service"
        elif artifact.kind == "inventory_deployment":
            method = "inventory_deployment_alias"
            label = "deployment declaration"
        else:
            return

        detail = (
            f"configured host matches the {label} '{name}' of component "
            f"'{component.name}'"
        )

        match = AliasMatch(
            component_id=component.id,
            component_name=component.name,
            method=method,
            declared=True,
            detail=detail,
            artifact_id=artifact.id,
            path=artifact.path,
            line=artifact.line,
            resource_id=artifact.resource_id,
        )

        self._add_alias(name, match)

        if artifact.kind in ("kubernetes_workload", "kubernetes_service"):
            self._add_kubernetes_aliases(name, artifact, match)

    def _add_kubernetes_aliases(
        self, name: str, artifact: ArtifactInput, match: AliasMatch
    ) -> None:
        """Add the DNS names a Kubernetes Service or workload is reachable by."""

        namespace = _resource_namespace(self._resources_by_id.get(artifact.resource_id or ""))
        namespace = namespace or artifact.attributes.get("namespace")

        suffixes = ["svc", "svc.cluster.local"]

        if isinstance(namespace, str) and namespace:
            suffixes = [
                f"{namespace}",
                f"{namespace}.svc",
                f"{namespace}.svc.cluster.local",
            ]

        for suffix in suffixes:
            self._add_alias(
                f"{name}.{suffix}",
                AliasMatch(
                    component_id=match.component_id,
                    component_name=match.component_name,
                    method="kubernetes_dns_name",
                    declared=True,
                    detail=(
                        f"configured host matches the Kubernetes DNS name '{name}.{suffix}' "
                        f"of component '{match.component_name}'"
                    ),
                    artifact_id=match.artifact_id,
                    path=match.path,
                    line=match.line,
                    resource_id=match.resource_id,
                ),
            )

    def _add_alias(self, alias: str, match: AliasMatch) -> None:
        """Record an exact alias and its normalised form."""

        key = _normalize_host(alias)

        if not key:
            return

        self._add_to(self._exact, key, match)
        self._add_normalized_alias(key, match)

    def _add_normalized_alias(self, alias: str, match: AliasMatch) -> None:
        """Record a normalised alias without recording a new exact alias."""

        key = normalize_name(alias)

        if not key:
            return

        self._add_to(self._normalized, key, match)

    @staticmethod
    def _add_to(bucket: dict[str, list[AliasMatch]], key: str, match: AliasMatch) -> None:
        """Append a match unless an equivalent one is already recorded."""

        entries = bucket.setdefault(key, [])
        identity = (
            match.component_id,
            match.method,
            match.declared,
            match.artifact_id,
        )

        if any(
            (item.component_id, item.method, item.declared, item.artifact_id) == identity
            for item in entries
        ):
            return

        entries.append(match)

    # ------------------------------------------------------------------ #
    # Ports, infrastructure and contracts
    # ------------------------------------------------------------------ #

    def _index_ports(self, analysis: ManifestAnalysisReport) -> None:
        """Collect the ports each component's deployment declares."""

        for endpoint in analysis.endpoints:
            if endpoint.scope in ("environment", "base_url") or endpoint.port is None:
                continue

            component_id = self.component_for_resource(endpoint.source_resource_id)

            if component_id is None:
                continue

            self._component_ports.setdefault(component_id, set()).add(endpoint.port)

    def _index_infrastructure(self, analysis: ManifestAnalysisReport) -> None:
        """Classify deployment-only components from their container images."""

        imaging: dict[str, list[tuple[str, str, str | None]]] = {}

        for relationship in analysis.relationships:
            if relationship.type.value != "uses_image":
                continue

            component_id = self.component_for_resource(relationship.source_id)

            if component_id is None:
                continue

            image = self._resources_by_id.get(relationship.target_id)

            if image is None or getattr(image, "kind", None) is not ResourceKind.IMAGE:
                continue

            imaging.setdefault(component_id, []).append(
                (
                    str(image.name),
                    str(getattr(image.location, "path", "") or ""),
                    getattr(image.location, "line", None),
                )
            )

        for component_id, images in sorted(imaging.items()):
            component = self._components.get(component_id)

            if component is None:
                continue

            component_artifacts = self._component_artifacts.get(component_id, [])
            roles = {artifact.role for artifact in component_artifacts}

            # A component with its own implementation or contract is an
            # application, even if a helper container inside it uses a cache.
            if roles & _IMPLEMENTED_ROLES:
                continue

            deployment_artifact = next(
                (artifact for artifact in component_artifacts if artifact.role == "deployment"),
                None,
            )

            classified = [
                (image_name, _classify_image(image_name), path, line)
                for image_name, path, line in sorted(images)
            ]

            # Classify only when every image in the component identifies
            # infrastructure. An unclassified image may be the application
            # itself with an infrastructure sidecar, which is not an
            # infrastructure component.
            if not classified or any(kind is None for _, kind, _, _ in classified):
                continue

            kinds = {kind for _, kind, _, _ in classified if kind is not None}

            kind = next(iter(kinds)) if len(kinds) == 1 else InfrastructureKind.INFRASTRUCTURE
            evidence: list[ResolutionEvidence] = []

            for image_name, image_kind, path, line in classified:
                if image_kind is None:
                    continue

                evidence.append(
                    ResolutionEvidence(
                        source=EvidenceSource.MANIFEST_ANALYSIS,
                        type="container_image",
                        detail=(
                            f"component '{component.name}' is deployed from image "
                            f"'{image_name}', which identifies {image_kind.value} infrastructure"
                        ),
                        declared=True,
                        path=path or None,
                        line=line,
                        artifact_id=(
                            deployment_artifact.id if deployment_artifact else None
                        ),
                        resource_id=(
                            deployment_artifact.resource_id if deployment_artifact else None
                        ),
                        resolution_method="container_image_family",
                    )
                )

            self._infrastructure[component_id] = InfrastructureMatch(
                kind=kind, evidence=tuple(evidence)
            )

    def _index_contracts(
        self, components: list[ComponentInput], artifacts_by_id: dict[str, ArtifactInput]
    ) -> None:
        """Record contract artifacts as supporting evidence, never as edges."""

        for component in components:
            contracts = [
                artifacts_by_id[artifact_id]
                for artifact_id in component.artifact_ids
                if artifact_id in artifacts_by_id
                and artifacts_by_id[artifact_id].role == "contract"
            ]

            if contracts:
                self._contracts[component.id] = sorted(
                    contracts, key=lambda item: (item.path or "", item.id)
                )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _normalize_host(host: str) -> str:
    """Reduce a configured host to a comparable DNS key."""

    value = host.strip().lower()

    if "://" in value:
        value = value.split("://", 1)[1]

    value = value.split("/", 1)[0].split("@")[-1]

    return value.rstrip(".")


def _is_local_host(host: str) -> bool:
    """Report whether a host is a loopback or wildcard address."""

    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}


def _rank(match: AliasMatch) -> int:
    """Rank a match so explicit deployment evidence wins over a display name."""

    if not match.declared:
        return 0

    if match.method in (
        "compose_service_alias",
        "kubernetes_service_alias",
        "kubernetes_workload_alias",
        "kubernetes_dns_name",
    ):
        return 3

    return 2


def _classify_image(image_name: str) -> InfrastructureKind | None:
    """Return the infrastructure kind an image name identifies."""

    base = image_name.lower().rsplit("/", 1)[-1].split(":", 1)[0]

    # Exporter and client images are tooling around infrastructure, not the
    # infrastructure itself.
    if "exporter" in base or base.endswith("-client"):
        return None

    for families, kind in _INFRASTRUCTURE_IMAGES:
        for family in families:
            if base == family or base.startswith(f"{family}-") or base.startswith(f"{family}_"):
                return kind

    return None


def _resource_namespace(resource: object | None) -> str | None:
    """Return a declared resource's namespace, when it has one."""

    if resource is None:
        return None

    namespace = getattr(resource, "namespace", None)

    return str(namespace) if namespace else None


__all__ = [
    "AliasMatch",
    "ArtifactInput",
    "ComponentIndex",
    "ComponentInput",
    "InfrastructureMatch",
]
