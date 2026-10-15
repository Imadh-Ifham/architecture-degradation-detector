"""Candidate artifact collection.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Turns the two upstream artifacts - `repository_inventory.json` and
    `manifest_analysis.json` - into a flat list of candidate artifacts, each
    carrying the identity evidence needed to decide which of them describe the
    same logical component.

    Nothing is parsed again here: repository structure comes from the inventory
    and manifest structure from manifest analysis. This module only re-projects
    what those stages already established into the shape identity resolution
    needs, which is why it contains no YAML, JSON-manifest or Dockerfile parsing.

    A candidate is deliberately *not* a component. Several candidates normally
    collapse into one component during identity resolution.
"""

from dataclasses import dataclass, field

from app.components.architecture_recovery.component_discovery.models import (
    ArtifactRole,
    AssociationConfidence,
    ComponentArtifact,
    DiscoveryEvidence,
    Diagnostic,
    MergeRule,
    artifact_id,
)
from app.components.architecture_recovery.component_discovery.paths import (
    ROOT_DIRECTORY,
    directory_of,
    name_keys,
    normalize_context,
    normalize_image,
    normalize_name,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    Diagnostic,
    DiagnosticSeverity,
)
from app.components.architecture_recovery.repository_inventory.models import (
    ComponentKind,
    FileRecord,
    RepositoryInventory,
)

# Candidate kinds, used by the merge rules and recorded on output artifacts.
COMPOSE_SERVICE = "compose_service"
KUBERNETES_WORKLOAD = "kubernetes_workload"
INVENTORY_DEPLOYMENT = "inventory_deployment"
SOURCE_PROJECT = "source_project"
DIRECTORY_GROUP = "directory_group"
DOCKERFILE = "dockerfile"
PROTOBUF_SERVICE = "protobuf_service"
OPENAPI_DOCUMENT = "openapi_document"
KUBERNETES_SERVICE = "kubernetes_service"

#: Candidate kinds whose path *is* their identity location. A deployment
#: manifest's own directory is not: it usually says more about where manifests
#: are kept than about which component is declared.
_LOCATED_KINDS: frozenset[str] = frozenset(
    {SOURCE_PROJECT, DIRECTORY_GROUP, DOCKERFILE}
)


@dataclass
class Candidate:
    """A candidate artifact plus the evidence identity resolution needs."""

    artifact: ComponentArtifact
    kind: str
    keys: frozenset[str] = frozenset()
    directory: str = ROOT_DIRECTORY
    root_path: str | None = None
    build_contexts: tuple[str, ...] = ()
    dockerfile_hint: str | None = None
    images: frozenset[str] = frozenset()
    is_deployment: bool = False
    is_project: bool = False
    #: Resource ids this artifact is explicitly attached to, used for artifacts
    #: that must not carry identity keys of their own (a Kubernetes Service is
    #: attached to the workload its selector matched).
    attached_to_resource_ids: frozenset[str] = frozenset()

    @property
    def has_location(self) -> bool:
        """Report whether this candidate's path identifies its component."""

        return self.kind in _LOCATED_KINDS


@dataclass
class CandidateCollection:
    """The candidates found, plus anything that could not be turned into one."""

    candidates: list[Candidate] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


class CandidateCollector:
    """Builds candidate artifacts from the inventory and manifest analysis."""

    def __init__(self) -> None:
        """Initialise an empty collector."""

        self._diagnostics: list[Diagnostic] = []

    def collect(
        self,
        inventory: RepositoryInventory,
        report,
    ) -> CandidateCollection:
        """Return every candidate artifact the two inputs describe."""

        self._diagnostics = []

        files_by_component = _files_by_component(inventory.files)
        resources = {resource.id: resource for resource in report.resources}
        image_names = _image_names_by_id(report.resources)
        images_by_source = _images_by_source(report.relationships, image_names)

        candidates: list[Candidate] = []

        candidates.extend(self._deployment_candidates(report, images_by_source))
        candidates.extend(
            self._inventory_deployment_candidates(
                inventory, candidates, _kubernetes_service_names(report)
            )
        )
        candidates.extend(self._project_candidates(inventory, files_by_component))
        candidates.extend(self._dockerfile_candidates(report))
        candidates.extend(self._contract_candidates(report))
        candidates.extend(self._kubernetes_service_candidates(report, resources))

        # A stable order keeps the union-find and every derived choice
        # independent of the order the upstream stages happened to emit.
        candidates.sort(key=lambda item: (item.kind, item.artifact.path, item.artifact.id))

        return CandidateCollection(candidates=candidates, diagnostics=self._diagnostics)

    # ------------------------------------------------------------------ #
    # Deployment evidence
    # ------------------------------------------------------------------ #

    def _deployment_candidates(self, report, images_by_source) -> list[Candidate]:
        """Collect Compose services and Kubernetes workloads.

        Kubernetes `Service`, `ConfigMap`, `Secret` and volume resources are
        deliberately excluded: a Service is exposure for a workload, not an
        application component of its own.
        """

        candidates: list[Candidate] = []

        for resource in report.resources:
            if resource.kind.value == "service" and resource.analyzer == "compose":
                candidates.append(
                    self._compose_candidate(resource, images_by_source)
                )
            elif resource.kind.value == "workload":
                candidates.append(
                    self._workload_candidate(resource, images_by_source)
                )

        return candidates

    def _compose_candidate(self, resource, images_by_source) -> Candidate:
        """Build a candidate for one Docker Compose service."""

        attributes = resource.attributes or {}
        raw_context = attributes.get("build_context")
        context = (
            normalize_context(str(raw_context))
            if isinstance(raw_context, str) and raw_context.strip()
            else ""
        )

        # A context of the repository root is dropped: it claims every path, so
        # it cannot distinguish one component from another.
        contexts = (context,) if context and context != ROOT_DIRECTORY else ()

        candidate = Candidate(
            artifact=ComponentArtifact(
                id=artifact_id(COMPOSE_SERVICE, resource.location.path, resource.name),
                role=ArtifactRole.DEPLOYMENT,
                confidence=AssociationConfidence.DIRECT,
                kind=COMPOSE_SERVICE,
                name=resource.name,
                path=resource.location.path,
                line=resource.location.line,
                resource_id=resource.id,
                inventory_component_id=attributes.get("component_id"),
                attributes={
                    key: value
                    for key, value in attributes.items()
                    if key in ("build_context", "dockerfile", "container_name")
                },
                evidence=[
                    DiscoveryEvidence(
                        source="manifest_analysis",
                        type="compose_service",
                        detail=f"compose declares the service '{resource.name}'",
                        confidence=AssociationConfidence.DIRECT,
                        path=resource.location.path,
                        line=resource.location.line,
                        resource_id=resource.id,
                        rule=MergeRule.BUILD_CONTEXT_CONTAINMENT if contexts else None,
                    )
                ],
            ),
            kind=COMPOSE_SERVICE,
            keys=frozenset(name_keys(resource.name)),
            directory=directory_of(resource.location.path),
            build_contexts=contexts,
            dockerfile_hint=attributes.get("dockerfile"),
            images=frozenset(images_by_source.get(resource.id, ())),
            is_deployment=True,
        )

        return candidate

    def _workload_candidate(self, resource, images_by_source) -> Candidate:
        """Build a candidate for one Kubernetes workload."""

        attributes = resource.attributes or {}

        return Candidate(
            artifact=ComponentArtifact(
                id=artifact_id(
                    KUBERNETES_WORKLOAD, resource.location.path, resource.name
                ),
                role=ArtifactRole.DEPLOYMENT,
                confidence=AssociationConfidence.DIRECT,
                kind=KUBERNETES_WORKLOAD,
                name=resource.name,
                path=resource.location.path,
                line=resource.location.line,
                resource_id=resource.id,
                inventory_component_id=attributes.get("component_id"),
                attributes={
                    key: value
                    for key, value in attributes.items()
                    if key in ("kind", "pod_labels", "labels", "namespace")
                },
                evidence=[
                    DiscoveryEvidence(
                        source="manifest_analysis",
                        type="kubernetes_workload",
                        detail=(
                            f"kubernetes declares the {attributes.get('kind', 'workload')} "
                            f"'{resource.name}'"
                        ),
                        confidence=AssociationConfidence.DIRECT,
                        path=resource.location.path,
                        line=resource.location.line,
                        resource_id=resource.id,
                    )
                ],
            ),
            kind=KUBERNETES_WORKLOAD,
            keys=frozenset(name_keys(resource.name)),
            directory=directory_of(resource.location.path),
            images=frozenset(images_by_source.get(resource.id, ())),
            is_deployment=True,
        )

    def _inventory_deployment_candidates(
        self,
        inventory: RepositoryInventory,
        existing: list[Candidate],
        service_names: set[str],
    ) -> list[Candidate]:
        """Add deployment references the inventory found but analysis did not.

        The inventory records a deployment service when a deployment manifest
        *names* one, even if analysis could not parse that manifest (a templated
        Helm chart, for example). Those are added only when analysis produced no
        deployment artifact of the same name, so the same service is never
        represented twice.

        The inventory's manifest reader also recognises Kubernetes `Service`
        objects as deployment declarations. Those are exposure for a workload
        rather than workloads themselves, so any name analysis identified as a
        Service is skipped here.
        """

        covered = {
            key
            for candidate in existing
            if candidate.is_deployment
            for key in candidate.keys
        }

        candidates: list[Candidate] = []

        for component in inventory.components:
            if component.kind is not ComponentKind.DEPLOYMENT_SERVICE:
                continue

            keys = frozenset(name_keys(component.name))

            if not keys or keys <= covered or keys & service_names:
                continue

            path = _first_evidence_path(component) or ROOT_DIRECTORY

            candidates.append(
                Candidate(
                    artifact=ComponentArtifact(
                        id=artifact_id(INVENTORY_DEPLOYMENT, path, component.name),
                        role=ArtifactRole.DEPLOYMENT,
                        # The deployment manifest itself could not be parsed, so
                        # the declaration is real but its detail is not verified.
                        confidence=AssociationConfidence.HEURISTIC,
                        kind=INVENTORY_DEPLOYMENT,
                        name=component.name,
                        path=path,
                        inventory_component_id=component.id,
                        evidence=[
                            DiscoveryEvidence(
                                source="repository_inventory",
                                type="deployment_reference",
                                detail=(
                                    f"the inventory recorded a deployment named "
                                    f"'{component.name}' that manifest analysis did "
                                    "not extract"
                                ),
                                confidence=AssociationConfidence.HEURISTIC,
                                path=path,
                                rule=MergeRule.NAME_MATCH,
                            )
                        ],
                    ),
                    kind=INVENTORY_DEPLOYMENT,
                    keys=keys,
                    directory=directory_of(path),
                    is_deployment=True,
                )
            )

        return candidates

    # ------------------------------------------------------------------ #
    # Source-project evidence
    # ------------------------------------------------------------------ #

    def _project_candidates(
        self,
        inventory: RepositoryInventory,
        files_by_component: dict[str, list[FileRecord]],
    ) -> list[Candidate]:
        """Collect the source projects the inventory identified.

        `BUILD_UNIT` is the inventory's own source-project boundary (a directory
        holding a build manifest), so it is reused rather than re-derived from
        build manifests here. `DIRECTORY_GROUP` is carried as weaker evidence:
        the inventory already marked it as inferred, and identity resolution
        treats it as heuristic.
        """

        candidates: list[Candidate] = []

        for component in inventory.components:
            if component.kind is ComponentKind.BUILD_UNIT:
                # The project root is the implementation; its build manifest is
                # a separate artifact recorded just below.
                artifact_role = ArtifactRole.IMPLEMENTATION
                kind = SOURCE_PROJECT
                description = "build manifest identifies a source project"
                confidence = AssociationConfidence.DIRECT
            elif component.kind is ComponentKind.DIRECTORY_GROUP:
                artifact_role = ArtifactRole.IMPLEMENTATION
                kind = DIRECTORY_GROUP
                description = (
                    "a directory holding code but declaring no build manifest"
                )
                confidence = AssociationConfidence.HEURISTIC
            else:
                continue

            root = component.root_path
            files = files_by_component.get(component.id, [])

            # The project root and its directory name are both identity keys:
            # the declared name can be unrelated to the directory (a Gradle
            # `rootProject.name` need not match its folder).
            keys = frozenset(
                name_keys(component.name, _basename(root)) - {""},
            )

            candidate = Candidate(
                artifact=ComponentArtifact(
                    id=artifact_id(kind, root or ROOT_DIRECTORY, component.name),
                    role=artifact_role,
                    confidence=confidence,
                    kind=kind,
                    name=component.name,
                    path=root or ROOT_DIRECTORY,
                    inventory_component_id=component.id,
                    attributes={
                        "languages": sorted(component.languages),
                        "file_count": len(files) or component.file_count,
                    },
                    evidence=[
                        DiscoveryEvidence(
                            source="repository_inventory",
                            type=kind,
                            detail=f"{description}: '{component.name}'",
                            confidence=confidence,
                            path=root or ROOT_DIRECTORY,
                            rule=(
                                MergeRule.PROJECT_LOCATION_CONTAINMENT
                                if kind == SOURCE_PROJECT
                                else MergeRule.DIRECTORY_GROUP_ONLY
                            ),
                        )
                    ],
                ),
                kind=kind,
                keys=keys,
                directory=root or ROOT_DIRECTORY,
                root_path=root,
                is_project=True,
            )

            candidates.append(candidate)

            # A source project also has a build manifest file, which is a
            # distinct artifact from the implementation directory itself.
            manifest_path = _first_evidence_path(component)

            if kind == SOURCE_PROJECT and manifest_path:
                candidates.append(
                    Candidate(
                        artifact=ComponentArtifact(
                            id=artifact_id(
                                SOURCE_PROJECT + "_manifest",
                                manifest_path,
                                component.name,
                            ),
                            role=ArtifactRole.DEFINITION,
                            confidence=AssociationConfidence.DIRECT,
                            kind=SOURCE_PROJECT,
                            name=component.name,
                            path=manifest_path,
                            inventory_component_id=component.id,
                            evidence=[
                                DiscoveryEvidence(
                                    source="repository_inventory",
                                    type="build_manifest",
                                    detail=(
                                        f"build manifest belonging to the project "
                                        f"'{component.name}'"
                                    ),
                                    confidence=AssociationConfidence.DIRECT,
                                    path=manifest_path,
                                )
                            ],
                        ),
                        kind=SOURCE_PROJECT,
                        keys=keys,
                        directory=directory_of(manifest_path),
                        root_path=root,
                        is_project=True,
                    )
                )

        return candidates

    # ------------------------------------------------------------------ #
    # Build and contract evidence
    # ------------------------------------------------------------------ #

    def _dockerfile_candidates(self, report) -> list[Candidate]:
        """Collect one candidate per Dockerfile, grouping its build stages."""

        grouped: dict[str, list] = {}

        for resource in report.resources:
            if resource.kind.value == "build_stage":
                grouped.setdefault(resource.location.path, []).append(resource)

        candidates: list[Candidate] = []

        for path, stages in sorted(grouped.items()):
            stages = sorted(stages, key=lambda item: item.name)
            stage_names = [stage.name for stage in stages]
            base_images = sorted(
                {
                    str(stage.attributes.get("base_image"))
                    for stage in stages
                    if stage.attributes.get("base_image")
                }
            )
            directory = directory_of(path)

            candidates.append(
                Candidate(
                    artifact=ComponentArtifact(
                        id=artifact_id(DOCKERFILE, path, None),
                        role=ArtifactRole.BUILD,
                        confidence=AssociationConfidence.DIRECT,
                        kind=DOCKERFILE,
                        name=_basename(directory),
                        path=path,
                        line=stages[0].location.line,
                        resource_id=stages[0].id,
                        inventory_component_id=stages[0].attributes.get("component_id"),
                        attributes={
                            "stages": stage_names,
                            "stage_count": len(stages),
                            "base_images": base_images,
                        },
                        evidence=[
                            DiscoveryEvidence(
                                source="manifest_analysis",
                                type="dockerfile",
                                detail=(
                                    f"Dockerfile declares {len(stages)} build stage(s): "
                                    f"{', '.join(stage_names)}"
                                ),
                                confidence=AssociationConfidence.DIRECT,
                                path=path,
                                line=stages[0].location.line,
                                resource_id=stages[0].id,
                            )
                        ],
                    ),
                    kind=DOCKERFILE,
                    keys=frozenset(name_keys(_basename(directory))),
                    directory=directory,
                    # Base images are deliberately *not* identity evidence: two
                    # unrelated Dockerfiles sharing `node:20` do not describe one
                    # component. Only an application image a deployment actually
                    # runs is evidence that two artifacts are the same service.
                    images=frozenset(),
                )
            )

        return candidates

    def _contract_candidates(self, report) -> list[Candidate]:
        """Collect API contracts: one per Protobuf service, one per API document.

        Protobuf *messages* and *RPCs* are deliberately not candidates. A contract
        component is the service surface; enumerating every message would add
        hundreds of artifacts without changing which component a contract belongs
        to.
        """

        candidates: list[Candidate] = []

        for resource in report.resources:
            kind_value = resource.kind.value

            if kind_value == "proto_service":
                kind = PROTOBUF_SERVICE
                description = f"protobuf service '{resource.name}' is declared"
            elif kind_value == "api":
                kind = OPENAPI_DOCUMENT
                description = f"API specification '{resource.name}' is declared"
            else:
                continue

            candidates.append(
                Candidate(
                    artifact=ComponentArtifact(
                        id=artifact_id(kind, resource.location.path, resource.name),
                        role=ArtifactRole.CONTRACT,
                        confidence=AssociationConfidence.DIRECT,
                        kind=kind,
                        name=resource.name,
                        path=resource.location.path,
                        line=resource.location.line,
                        resource_id=resource.id,
                        inventory_component_id=(resource.attributes or {}).get(
                            "component_id"
                        ),
                        attributes={
                            key: value
                            for key, value in (resource.attributes or {}).items()
                            if key in ("package", "version", "specification")
                        },
                        evidence=[
                            DiscoveryEvidence(
                                source="manifest_analysis",
                                type=kind,
                                detail=description,
                                confidence=AssociationConfidence.DIRECT,
                                path=resource.location.path,
                                line=resource.location.line,
                                resource_id=resource.id,
                            )
                        ],
                    ),
                    kind=kind,
                    keys=frozenset(name_keys(resource.name)),
                    directory=directory_of(resource.location.path),
                )
            )

        return candidates

    def _kubernetes_service_candidates(self, report, resources) -> list[Candidate]:
        """Collect Kubernetes Services as artifacts, never as components.

        A Service is exposure for the workload its selector matched. It carries
        no identity keys of its own, so it can only ever join a component through
        the workload it is attached to - which is what stops a Service named
        `frontend-external` from becoming its own application component.
        """

        # Workload resource id -> Service resource ids that select it.
        selected_by: dict[str, list[str]] = {}

        for relationship in report.relationships:
            if relationship.type.value == "selects_workload":
                selected_by.setdefault(relationship.target_id, []).append(
                    relationship.source_id
                )

        candidates: list[Candidate] = []

        for resource in report.resources:
            if resource.kind.value != "kubernetes_service":
                continue

            # Reverse the map so each Service knows the workload it targets.
            targeted = frozenset(
                workload_id
                for workload_id, service_ids in selected_by.items()
                if resource.id in service_ids
            )

            candidates.append(
                Candidate(
                    artifact=ComponentArtifact(
                        id=artifact_id(
                            KUBERNETES_SERVICE, resource.location.path, resource.name
                        ),
                        role=ArtifactRole.DEPLOYMENT,
                        confidence=AssociationConfidence.DIRECT,
                        kind=KUBERNETES_SERVICE,
                        name=resource.name,
                        path=resource.location.path,
                        line=resource.location.line,
                        resource_id=resource.id,
                        attributes={
                            key: value
                            for key, value in (resource.attributes or {}).items()
                            if key in ("service_type", "selector")
                        },
                        evidence=[
                            DiscoveryEvidence(
                                source="manifest_analysis",
                                type="kubernetes_service",
                                detail=(
                                    f"Service '{resource.name}' exposes the workload "
                                    "matched by its selector"
                                ),
                                confidence=AssociationConfidence.DIRECT,
                                path=resource.location.path,
                                line=resource.location.line,
                                resource_id=resource.id,
                            )
                        ],
                    ),
                    kind=KUBERNETES_SERVICE,
                    keys=frozenset(),
                    directory=directory_of(resource.location.path),
                    attached_to_resource_ids=targeted,
                )
            )

        return candidates


# --------------------------------------------------------------------------- #
# Helpers over the upstream documents
# --------------------------------------------------------------------------- #


def _kubernetes_service_names(report) -> set[str]:
    """Return the normalised names of the Kubernetes Services in the analysis."""

    return {
        normalize_name(resource.name)
        for resource in report.resources
        if resource.kind.value == "kubernetes_service" and resource.name
    }


def _files_by_component(files: list[FileRecord]) -> dict[str, list[FileRecord]]:
    """Group inventory files by the component the inventory assigned them to."""

    grouped: dict[str, list[FileRecord]] = {}

    for file in files:
        if file.component_id:
            grouped.setdefault(file.component_id, []).append(file)

    return grouped


def _images_by_source(relationships, image_names: dict[str, str]) -> dict[str, list[str]]:
    """Map a resource id to the normalised image names it uses."""

    images: dict[str, list[str]] = {}

    for relationship in relationships:
        if relationship.type.value != "uses_image":
            continue

        name = image_names.get(relationship.target_id)

        if name:
            images.setdefault(relationship.source_id, []).append(
                normalize_image(name)
            )

    return images


def _image_names_by_id(resources) -> dict[str, str]:
    """Map an image resource id to its image name."""

    return {
        resource.id: resource.name
        for resource in resources
        if resource.kind.value == "image"
    }


def _first_evidence_path(component) -> str | None:
    """Return the first repository-relative path recorded on an inventory component."""

    for evidence in component.evidence:
        if evidence.path:
            return evidence.path

    return None


def _basename(path: str | None) -> str:
    """Return the final segment of a path, tolerating None and the root."""

    if not path or path == ROOT_DIRECTORY:
        return ""

    return path.rstrip("/").rsplit("/", 1)[-1]
