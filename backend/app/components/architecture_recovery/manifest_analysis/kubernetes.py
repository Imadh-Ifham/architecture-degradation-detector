"""Kubernetes manifest analyzer.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Parses Kubernetes YAML into workloads, containers, images, service
    selectors, ports, and references to ConfigMaps, Secrets and volumes.

    Secret material is never read: only key names are recorded. A Service
    selector that matches a workload in the same file is recorded as a declared
    mapping, which is configuration, not proof that traffic reaches the pods.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

from app.components.architecture_recovery.manifest_analysis.base import (
    AnalyzerResult,
    ManifestAnalyzer,
    has_template_expressions,
    read_manifest_text,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    DeclaredRelationship,
    DeclaredResource,
    DiagnosticSeverity,
    Endpoint,
    ExtractedEvidence,
    ExtractionMethod,
    ParseStatus,
    ReferenceKind,
    ReferenceStatus,
    RelationshipOrigin,
    RelationshipType,
    ResourceKind,
    ResourceReference,
    SourceLocation,
    endpoint_id,
    reference_id,
    relationship_id,
    resource_id,
)
from app.components.architecture_recovery.manifest_analysis.redaction import (
    extract_endpoint_candidate,
    sanitize_scalar,
)
from app.components.architecture_recovery.manifest_analysis.yaml_support import (
    line_of,
    load_yaml_documents,
)
from app.components.architecture_recovery.repository_inventory.models import (
    FileCategory,
    FileRecord,
)

# Kubernetes kinds mapped to the resource kind recorded for them.
RESOURCE_KINDS: dict[str, ResourceKind] = {
    "deployment": ResourceKind.WORKLOAD,
    "statefulset": ResourceKind.WORKLOAD,
    "daemonset": ResourceKind.WORKLOAD,
    "replicaset": ResourceKind.WORKLOAD,
    "job": ResourceKind.WORKLOAD,
    "cronjob": ResourceKind.WORKLOAD,
    "pod": ResourceKind.WORKLOAD,
    "service": ResourceKind.KUBERNETES_SERVICE,
    "configmap": ResourceKind.CONFIG_MAP,
    "secret": ResourceKind.SECRET,
    "namespace": ResourceKind.NAMESPACE,
    "persistentvolumeclaim": ResourceKind.VOLUME,
    "persistentvolume": ResourceKind.VOLUME,
}

# Kinds whose workload definition holds a pod template.
_TEMPLATE_KINDS = frozenset(
    {"deployment", "statefulset", "daemonset", "replicaset", "job", "cronjob"}
)


class KubernetesAnalyzer(ManifestAnalyzer):
    """Analyzes a Kubernetes YAML manifest, including multi-document files."""

    name = "kubernetes"

    def __init__(self, max_bytes: int = 1_048_576, max_documents: int = 64) -> None:
        """Store the size and document-count limits for one file."""

        self._max_bytes = max_bytes
        self._max_documents = max_documents

    def can_analyze(self, file: FileRecord) -> bool:
        """Accept anything the inventory classified as a YAML deployment manifest.

        Compose files also match this predicate, so the registry must offer this
        analyzer only after the more specific Compose analyzer.
        """

        return (
            file.category is FileCategory.DEPLOYMENT_MANIFEST
            and file.format == "yaml"
        )

    def analyze(self, file: FileRecord, absolute_path: Path) -> AnalyzerResult:
        """Extract workload, service and configuration references."""

        result = AnalyzerResult(method=ExtractionMethod.YAML)

        text, diagnostic = read_manifest_text(
            absolute_path, self._max_bytes, file.path
        )

        if text is None:
            result.status = ParseStatus.SKIPPED
            result.diagnostics.append(replace(diagnostic, analyzer=self.name))
            return result

        if has_template_expressions(text):
            result.status = ParseStatus.SKIPPED
            result.add_diagnostic(
                DiagnosticSeverity.WARNING,
                "templated manifest cannot be parsed without resolving its "
                "template expressions",
                file.path,
                None,
                self.name,
            )
            return result

        loaded = load_yaml_documents(text)

        if loaded.error:
            result.status = ParseStatus.FAILED
            result.add_diagnostic(
                DiagnosticSeverity.ERROR,
                f"could not parse kubernetes manifest: {loaded.error}",
                file.path,
                loaded.error_line,
                self.name,
            )
            return result

        analysis = _KubernetesAnalysis(file, result, loaded.positions)

        if len(loaded.documents) > self._max_documents:
            result.status = ParseStatus.PARTIAL
            result.add_diagnostic(
                DiagnosticSeverity.WARNING,
                f"only the first {self._max_documents} documents were analyzed",
                file.path,
                None,
                self.name,
            )

        for document in loaded.documents[: self._max_documents]:
            analysis.add_document(document)

        analysis.finish()

        if not result.resources:
            # Parsed, but nothing this analyzer recognises.
            result.status = ParseStatus.PARTIAL
            result.add_diagnostic(
                DiagnosticSeverity.INFO,
                "file parsed but declared no recognised kubernetes resource",
                file.path,
                None,
                self.name,
            )

        return result


class _KubernetesAnalysis:
    """Walks the documents of one Kubernetes file and records declarations."""

    def __init__(self, file: FileRecord, result: AnalyzerResult, positions: dict) -> None:
        """Bind the analysis to a file, its result and the position table."""

        self._file = file
        self._result = result
        self._positions = positions

        self._resources_by_name: dict[str, str] = {}
        self._image_ids: set[str] = set()
        self._config_maps: set[str] = set()
        self._secrets: set[str] = set()
        self._volumes: set[str] = set()
        # Workloads are held until every document is read so Service selectors
        # can match regardless of document order.
        self._workloads: list[tuple[dict, str]] = []
        self._selectors: list[tuple[dict, str, SourceLocation]] = []
        # References are collected and resolved in `finish`, because the object
        # they point at may be declared in a later document of the same file.
        self._pending_references: list[
            tuple[ReferenceKind, str, str, str, SourceLocation, str]
        ] = []

    def add_document(self, document) -> None:
        """Record the resources declared by one parsed document."""

        data = document.data
        line = document.line

        if not isinstance(data, dict):
            self._result.add_diagnostic(
                DiagnosticSeverity.WARNING,
                "skipping a document that is not a mapping",
                self._file.path,
                line,
                "kubernetes",
            )
            return

        kind = _text(data.get("kind"))

        if kind is None:
            self._result.add_diagnostic(
                DiagnosticSeverity.WARNING,
                "skipping a document without a 'kind'",
                self._file.path,
                line,
                "kubernetes",
            )
            return

        # A `List` wraps further objects, which are analyzed as if inline.
        if kind.lower() == "list":
            for item in data.get("items") or []:
                if isinstance(item, dict):
                    self._analyze_object(item, line)
            return

        self._analyze_object(data, line)

    def finish(self) -> None:
        """Resolve references and Service selectors now that all input is read."""

        self._resolve_references()

        for service_data, service_id, location in self._selectors:
            selector = service_data.get("selector")

            if not isinstance(selector, dict) or not selector:
                continue

            matched = [
                workload_id
                for labels, workload_id in self._workloads
                if _labels_match(selector, labels)
            ]

            if not matched:
                # The selector may target pods created outside this manifest, so
                # this is ambiguity rather than an error.
                self._result.add_diagnostic(
                    DiagnosticSeverity.INFO,
                    "service selector matches no workload declared in this file",
                    self._file.path,
                    location.line,
                    "kubernetes",
                )
                continue

            for workload_id in matched:
                self._add_relationship(
                    RelationshipType.SELECTS_WORKLOAD,
                    RelationshipOrigin.CONFIGURED_ENDPOINT,
                    service_id,
                    workload_id,
                    location,
                    True,
                    "service selector matches the workload's pod labels",
                )

    # ------------------------------------------------------------------ #
    # Per-object analysis
    # ------------------------------------------------------------------ #

    def _analyze_object(self, data: dict, fallback_line: int | None) -> None:
        """Record one Kubernetes object and dispatch on its kind."""

        kind = _text(data.get("kind")) or ""

        if kind.lower() == "list":
            for item in data.get("items") or []:
                if isinstance(item, dict):
                    self._analyze_object(item, fallback_line)
            return

        resource_kind = RESOURCE_KINDS.get(kind.lower())

        if resource_kind is None:
            self._result.add_diagnostic(
                DiagnosticSeverity.INFO,
                f"unsupported kubernetes kind '{kind}' was not analyzed",
                self._file.path,
                fallback_line,
                "kubernetes",
            )
            return

        metadata = data.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        name = _text(metadata.get("name")) or f"<unnamed-{kind.lower()}>"
        namespace = _text(metadata.get("namespace"))
        labels = metadata.get("labels")
        labels = labels if isinstance(labels, dict) else {}

        location = SourceLocation(
            path=self._file.path, line=line_of(data, self._positions) or fallback_line
        )

        attributes: dict = {
            "kind": kind,
            "api_version": (_text(data.get("apiVersion")) or ""),
        }

        if labels:
            attributes["labels"] = {str(k): str(v) for k, v in labels.items()}

        if self._file.component_id:
            attributes["component_id"] = self._file.component_id

        identifier = resource_id(self._file.path, resource_kind, name)
        self._resources_by_name[name] = identifier

        # Register the names that references can resolve against, so resolution
        # is order-independent across documents in the same file.
        if resource_kind is ResourceKind.CONFIG_MAP:
            self._config_maps.add(name)
        elif resource_kind is ResourceKind.SECRET:
            self._secrets.add(name)
        elif resource_kind is ResourceKind.VOLUME:
            self._volumes.add(name)

        spec = data.get("spec")
        spec = spec if isinstance(spec, dict) else {}

        if resource_kind is ResourceKind.WORKLOAD:
            self._describe_workload(kind, name, data, spec, attributes)
        elif resource_kind is ResourceKind.KUBERNETES_SERVICE:
            self._describe_service(name, metadata, spec, attributes, location)
            self._selectors.append((spec, identifier, location))
        elif resource_kind is ResourceKind.CONFIG_MAP:
            self._describe_config_map(name, data, attributes)
        elif resource_kind is ResourceKind.SECRET:
            self._describe_secret(name, data, attributes)
        elif resource_kind is ResourceKind.NAMESPACE:
            self._result.resources.append(
                DeclaredResource(
                    id=identifier,
                    kind=resource_kind,
                    name=name,
                    namespace=name,
                    location=location,
                    analyzer="kubernetes",
                    method=ExtractionMethod.YAML,
                    attributes=attributes,
                    evidence=[
                        ExtractedEvidence(
                            "kubernetes_object",
                            f"namespace '{name}' is declared",
                            ExtractionMethod.YAML,
                            location,
                        )
                    ],
                )
            )
            return

        self._result.resources.append(
            DeclaredResource(
                id=identifier,
                kind=resource_kind,
                name=name,
                namespace=namespace,
                location=location,
                analyzer="kubernetes",
                method=ExtractionMethod.YAML,
                attributes=attributes,
                evidence=[
                    ExtractedEvidence(
                        "kubernetes_object",
                        f"{kind} '{name}' is declared",
                        ExtractionMethod.YAML,
                        location,
                    )
                ],
            )
        )

    def _describe_workload(
        self,
        kind: str,
        name: str,
        data: dict,
        spec: dict,
        attributes: dict,
    ) -> None:
        """Record a workload's pod labels, containers and their configuration."""

        pod_spec, pod_labels = _pod_spec(kind, spec)
        workload_id = self._resources_by_name[name]

        if pod_labels:
            attributes["pod_labels"] = {
                str(key): str(value) for key, value in pod_labels.items()
            }

        self._workloads.append((pod_labels or attributes.get("labels") or {}, workload_id))

        location = SourceLocation(
            path=self._file.path, line=line_of(data, self._positions)
        )

        for container in _containers(pod_spec):
            self._describe_container(
                name, workload_id, container, location, attributes
            )

        for volume in _as_list(pod_spec.get("volumes")):
            if isinstance(volume, dict):
                self._describe_pod_volume(workload_id, volume, location)

        for pull_secret in _as_list(pod_spec.get("imagePullSecrets")):
            secret_name = _text(pull_secret.get("name")) if isinstance(pull_secret, dict) else None

            if secret_name:
                self._reference(
                    ReferenceKind.SECRET,
                    secret_name,
                    "kubernetes_image_pull_secret",
                    workload_id,
                    location,
                    "imagePullSecret is referenced; its value is never read",
                )

    def _describe_container(
        self,
        workload_name: str,
        workload_id: str,
        container: dict,
        location: SourceLocation,
        workload_attributes: dict,
    ) -> None:
        """Record a container's image, ports and configuration references."""

        container_name = _text(container.get("name")) or "<unnamed>"
        identifier = resource_id(
            self._file.path, ResourceKind.CONTAINER, f"{workload_name}/{container_name}"
        )

        container_location = SourceLocation(
            path=self._file.path, line=line_of(container, self._positions)
        )

        self._result.resources.append(
            DeclaredResource(
                id=identifier,
                kind=ResourceKind.CONTAINER,
                name=container_name,
                location=container_location,
                analyzer="kubernetes",
                method=ExtractionMethod.YAML,
                attributes={"workload": workload_name},
                evidence=[
                    ExtractedEvidence(
                        "kubernetes_container",
                        f"container '{container_name}' is declared by workload "
                        f"'{workload_name}'",
                        ExtractionMethod.YAML,
                        container_location,
                    )
                ],
            )
        )

        image = _text(container.get("image"))

        if image:
            image_name = image.split("@", 1)[0].split(":", 1)[0]
            image_id = resource_id(self._file.path, ResourceKind.IMAGE, image_name)

            if image_id not in self._image_ids:
                self._image_ids.add(image_id)
                self._result.resources.append(
                    DeclaredResource(
                        id=image_id,
                        kind=ResourceKind.IMAGE,
                        name=image_name,
                        location=container_location,
                        analyzer="kubernetes",
                        method=ExtractionMethod.YAML,
                        attributes={"reference": image},
                        evidence=[
                            ExtractedEvidence(
                                "kubernetes_image",
                                f"container '{container_name}' uses image '{image}'",
                                ExtractionMethod.YAML,
                                container_location,
                            )
                        ],
                    )
                )

            self._add_relationship(
                RelationshipType.USES_IMAGE,
                RelationshipOrigin.DECLARED_BUILD_INPUT,
                workload_id,
                image_id,
                container_location,
                True,
                f"container '{container_name}' uses image '{image}'",
            )

        for port in _as_list(container.get("ports")):
            if not isinstance(port, dict):
                continue

            container_port = port.get("containerPort")
            protocol = str(port.get("protocol") or "tcp")

            endpoint = Endpoint(
                id=endpoint_id(
                    self._file.path,
                    f"container:{workload_name}/{container_name}:{container_port}",
                ),
                location=container_location,
                port=container_port if isinstance(container_port, int) else None,
                protocol=protocol,
                source_resource_id=workload_id,
                scope="container",
                evidence=[
                    ExtractedEvidence(
                        "kubernetes_container_port",
                        f"container '{container_name}' declares containerPort "
                        f"{container_port}/{protocol}",
                        ExtractionMethod.YAML,
                        container_location,
                    )
                ],
            )

            self._result.endpoints.append(endpoint)

            self._add_relationship(
                RelationshipType.EXPOSES_PORT,
                RelationshipOrigin.CONFIGURED_ENDPOINT,
                workload_id,
                endpoint.id,
                container_location,
                True,
                f"container '{container_name}' exposes containerPort {container_port}",
            )

        self._describe_container_environment(
            container_name,
            workload_id,
            container,
            container_location,
            workload_attributes,
        )

    def _describe_container_environment(
        self,
        container_name: str,
        workload_id: str,
        container: dict,
        location: SourceLocation,
        workload_attributes: dict,
    ) -> None:
        """Record environment variable names and their configuration references.

        Entries are written onto the owning workload's attributes, which is why
        the workload's attribute mapping is passed in rather than looked up: the
        workload resource is appended after its containers are described.
        """

        recorded: list[dict] = []

        for entry in _as_list(container.get("env")):
            if not isinstance(entry, dict):
                continue

            key = _text(entry.get("name"))

            if not key:
                continue

            item: dict = {"name": key}

            if "value" in entry:
                sanitized = sanitize_scalar(entry.get("value"), key)

                if sanitized.value is not None:
                    item["value"] = sanitized.value

                    candidate = extract_endpoint_candidate(sanitized.value)

                    if candidate is not None:
                        self._add_configured_endpoint(
                            workload_id,
                            container_name,
                            key,
                            candidate,
                            location,
                            sanitized.value,
                        )

                if sanitized.redacted:
                    item["redacted"] = True

            value_from = entry.get("valueFrom")
            value_from = value_from if isinstance(value_from, dict) else {}

            config_ref = value_from.get("configMapKeyRef")
            secret_ref = value_from.get("secretKeyRef")

            if isinstance(config_ref, dict) and config_ref.get("name"):
                referenced = str(config_ref["name"])
                item["from_config_map"] = referenced
                self._reference(
                    ReferenceKind.CONFIG_MAP,
                    referenced,
                    "kubernetes_env_from_config_map",
                    workload_id,
                    location,
                    f"environment variable '{key}' reads ConfigMap '{referenced}'",
                )

            if isinstance(secret_ref, dict) and secret_ref.get("name"):
                referenced = str(secret_ref["name"])
                item["from_secret"] = referenced
                self._reference(
                    ReferenceKind.SECRET,
                    referenced,
                    "kubernetes_env_from_secret",
                    workload_id,
                    location,
                    f"environment variable '{key}' reads Secret '{referenced}' "
                    "(value not extracted)",
                )

            recorded.append(item)

        for entry in _as_list(container.get("envFrom")):
            if not isinstance(entry, dict):
                continue

            for ref_key, kind, label in (
                ("configMapRef", ReferenceKind.CONFIG_MAP, "config_map_ref"),
                ("secretRef", ReferenceKind.SECRET, "secret_ref"),
            ):
                reference = entry.get(ref_key)

                if isinstance(reference, dict) and reference.get("name"):
                    referenced = str(reference["name"])
                    recorded.append(
                        {
                            "name": f"<{ref_key}>",
                            "referenced": referenced,
                        }
                    )
                    self._reference(
                        kind,
                        referenced,
                        f"kubernetes_env_from_{label}",
                        workload_id,
                        location,
                        f"container '{container_name}' loads all keys from "
                        f"'{referenced}'",
                    )

        if not recorded:
            return

        environment = workload_attributes.setdefault("environment", [])
        environment.extend(recorded)

    def _add_configured_endpoint(
        self,
        workload_id: str,
        container_name: str,
        key: str,
        candidate,
        location: SourceLocation,
        value: str,
    ) -> None:
        """Record an endpoint named by a literal environment value.

        This mirrors the Compose analyzer: the value configures a target, so it
        is evidence of a configured endpoint, never proof that traffic reaches
        it.
        """

        endpoint = Endpoint(
            id=endpoint_id(self._file.path, f"env:{container_name}:{key}"),
            location=location,
            host=candidate.host,
            port=candidate.port,
            protocol=candidate.scheme,
            source_resource_id=workload_id,
            scope="environment",
            evidence=[
                ExtractedEvidence(
                    "kubernetes_environment",
                    f"environment variable '{key}' names the endpoint "
                    f"'{candidate.sanitized_value or value}'",
                    ExtractionMethod.YAML,
                    location,
                )
            ],
        )

        self._result.endpoints.append(endpoint)

        self._add_relationship(
            RelationshipType.REFERS_TO_SERVICE,
            RelationshipOrigin.CONFIGURED_ENDPOINT,
            workload_id,
            endpoint.id,
            location,
            True,
            f"environment variable '{key}' configures the endpoint "
            f"'{candidate.sanitized_value or value}'",
        )

    def _describe_pod_volume(
        self, workload_id: str, volume: dict, location: SourceLocation
    ) -> None:
        """Record a pod volume, including what it references."""

        volume_name = _text(volume.get("name")) or "<unnamed>"

        config_map = volume.get("configMap")

        if isinstance(config_map, dict) and config_map.get("name"):
            self._reference(
                ReferenceKind.CONFIG_MAP,
                str(config_map["name"]),
                "kubernetes_volume_from_config_map",
                workload_id,
                location,
                f"volume '{volume_name}' is populated from a ConfigMap",
            )

        secret = volume.get("secret")

        if isinstance(secret, dict) and secret.get("secretName"):
            self._reference(
                ReferenceKind.SECRET,
                str(secret["secretName"]),
                "kubernetes_volume_from_secret",
                workload_id,
                location,
                f"volume '{volume_name}' is populated from a Secret (values not read)",
            )

        claim = volume.get("persistentVolumeClaim")

        if isinstance(claim, dict) and claim.get("claimName"):
            claim_name = str(claim["claimName"])
            self._reference(
                ReferenceKind.VOLUME,
                claim_name,
                "kubernetes_persistent_volume_claim",
                workload_id,
                location,
                f"volume '{volume_name}' uses the claim '{claim_name}'",
            )

    def _describe_service(
        self,
        name: str,
        metadata: dict,
        spec: dict,
        attributes: dict,
        location: SourceLocation,
    ) -> None:
        """Record a Service's type, selector and ports."""

        service_type = _text(spec.get("type")) or "ClusterIP"
        attributes["service_type"] = service_type

        selector = spec.get("selector")

        if isinstance(selector, dict):
            attributes["selector"] = {
                str(key): str(value) for key, value in selector.items()
            }

        if service_type == "ExternalName":
            external = _text(spec.get("externalName"))

            if external:
                attributes["external_name"] = external

        service_id = resource_id(self._file.path, ResourceKind.KUBERNETES_SERVICE, name)
        cluster_ip = _text(spec.get("clusterIP"))

        if cluster_ip:
            attributes["cluster_ip"] = cluster_ip

        for port in _as_list(spec.get("ports")):
            if not isinstance(port, dict):
                continue

            port_number_value = port.get("port")
            protocol = str(port.get("protocol") or "tcp")

            endpoint = Endpoint(
                id=endpoint_id(
                    self._file.path,
                    f"service:{name}:{port_number_value}/{protocol}",
                ),
                location=location,
                host=cluster_ip,
                port=port_number_value if isinstance(port_number_value, int) else None,
                protocol=protocol,
                source_resource_id=service_id,
                scope="service",
                evidence=[
                    ExtractedEvidence(
                        "kubernetes_service_port",
                        f"service '{name}' declares port {port_number_value}/{protocol}",
                        ExtractionMethod.YAML,
                        location,
                    )
                ],
            )

            self._result.endpoints.append(endpoint)

            self._add_relationship(
                RelationshipType.EXPOSES_PORT,
                RelationshipOrigin.CONFIGURED_ENDPOINT,
                service_id,
                endpoint.id,
                location,
                True,
                f"service '{name}' exposes port {port_number_value}/{protocol}",
            )

    def _describe_config_map(
        self, name: str, data: dict, attributes: dict
    ) -> None:
        """Record a ConfigMap's key names without its values."""

        keys = sorted(
            {
                *(_keys(data.get("data"))),
                *(_keys(data.get("binaryData"))),
            }
        )

        attributes["keys"] = keys
        attributes["values_extracted"] = False

    def _describe_secret(self, name: str, data: dict, attributes: dict) -> None:
        """Record a Secret's type and key names, never its values."""

        keys = sorted(
            {
                *(_keys(data.get("data"))),
                *(_keys(data.get("stringData"))),
            }
        )

        attributes["keys"] = keys
        attributes["secret_type"] = _text(data.get("type")) or "Opaque"
        # Explicit so a consumer can rely on the absence of secret material.
        attributes["values_extracted"] = False

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _reference(
        self,
        kind: ReferenceKind,
        name: str,
        reference_type: str,
        source_id: str,
        location: SourceLocation,
        detail: str,
    ) -> None:
        """Queue a reference for resolution once the whole file has been read."""

        self._pending_references.append(
            (kind, name, reference_type, source_id, location, detail)
        )

    def _resolve_references(self) -> None:
        """Resolve every queued reference against the names declared in this file.

        A reference that resolves also yields a relationship, because the target
        is known; one that does not stays an unresolved reference so a later
        stage can resolve it against the rest of the repository.
        """

        declared: dict[ReferenceKind, set[str]] = {
            ReferenceKind.CONFIG_MAP: self._config_maps,
            ReferenceKind.SECRET: self._secrets,
            ReferenceKind.VOLUME: self._volumes,
        }

        relationship_types: dict[ReferenceKind, tuple[RelationshipType, RelationshipOrigin]] = {
            ReferenceKind.CONFIG_MAP: (
                RelationshipType.REFERENCES_CONFIG,
                RelationshipOrigin.DECLARED_DEPENDENCY,
            ),
            ReferenceKind.SECRET: (
                RelationshipType.REFERENCES_SECRET,
                RelationshipOrigin.DECLARED_DEPENDENCY,
            ),
            ReferenceKind.VOLUME: (
                RelationshipType.MOUNTS_VOLUME,
                RelationshipOrigin.CONFIGURED_FILESYSTEM,
            ),
        }

        resource_kinds: dict[ReferenceKind, ResourceKind] = {
            ReferenceKind.CONFIG_MAP: ResourceKind.CONFIG_MAP,
            ReferenceKind.SECRET: ResourceKind.SECRET,
            ReferenceKind.VOLUME: ResourceKind.VOLUME,
        }

        for kind, name, reference_type, source_id, location, detail in (
            self._pending_references
        ):
            target_id: str | None = None
            status = ReferenceStatus.UNRESOLVED
            reason = "not declared in this file"

            if name in declared.get(kind, set()):
                target_id = resource_id(self._file.path, resource_kinds[kind], name)
                status = ReferenceStatus.RESOLVED
                reason = None

            self._result.references.append(
                ResourceReference(
                    id=reference_id(self._file.path, kind, name, reference_type),
                    kind=kind,
                    name=name,
                    location=location,
                    status=status,
                    reference_type=reference_type,
                    target_id=target_id,
                    reason=reason,
                    evidence=[
                        ExtractedEvidence(
                            reference_type,
                            detail,
                            ExtractionMethod.YAML,
                            location,
                        )
                    ],
                )
            )

            if target_id is None:
                continue

            relationship_type, origin = relationship_types[kind]

            self._add_relationship(
                relationship_type,
                origin,
                source_id,
                target_id,
                location,
                True,
                detail,
            )

    def _add_relationship(
        self,
        relationship_type: RelationshipType,
        origin: RelationshipOrigin,
        source_id: str,
        target_id: str,
        location: SourceLocation,
        resolved: bool,
        detail: str,
    ) -> None:
        """Record a relationship with its evidence."""

        self._result.relationships.append(
            DeclaredRelationship(
                id=relationship_id(relationship_type, source_id, target_id),
                type=relationship_type,
                origin=origin,
                source_id=source_id,
                target_id=target_id,
                location=location,
                resolved=resolved,
                evidence=[
                    ExtractedEvidence(
                        "kubernetes_declaration",
                        detail,
                        ExtractionMethod.YAML,
                        location,
                    )
                ],
            )
        )


def _pod_spec(kind: str, spec: dict) -> tuple[dict, dict]:
    """Return the pod spec and pod labels for a workload.

    Handles the three nesting shapes Kubernetes uses: a bare Pod, a templated
    workload, and a CronJob whose template is one level deeper.
    """

    if kind.lower() == "pod":
        return spec, {}

    template = spec.get("template")

    if kind.lower() == "cronjob":
        job_template = spec.get("jobTemplate")
        if isinstance(job_template, dict):
            job_spec = job_template.get("spec")
            if isinstance(job_spec, dict):
                template = job_spec.get("template")

    if not isinstance(template, dict):
        return {}, {}

    pod_spec = template.get("spec")
    metadata = template.get("metadata")
    labels = metadata.get("labels") if isinstance(metadata, dict) else None

    return (
        pod_spec if isinstance(pod_spec, dict) else {},
        labels if isinstance(labels, dict) else {},
    )


def _containers(pod_spec: dict) -> list[dict]:
    """Return every container in a pod spec, including init containers."""

    containers = [
        item
        for item in _as_list(pod_spec.get("containers"))
        if isinstance(item, dict)
    ]
    containers.extend(
        item
        for item in _as_list(pod_spec.get("initContainers"))
        if isinstance(item, dict)
    )

    return containers


def _labels_match(selector: dict, labels: dict) -> bool:
    """Report whether a Service selector is satisfied by a set of pod labels."""

    if not selector or not labels:
        return False

    return all(
        str(labels.get(str(key))) == str(value) for key, value in selector.items()
    )


def _keys(section: Any) -> list[str]:
    """Return the key names of a ConfigMap or Secret data section."""

    return [str(key) for key in section] if isinstance(section, dict) else []


def _as_list(value: Any) -> list:
    """Coerce a manifest field to a list for uniform iteration."""

    if value is None:
        return []

    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str | None:
    """Return a non-empty string for a scalar, else None."""

    if value is None:
        return None

    text = str(value).strip()

    return text or None
