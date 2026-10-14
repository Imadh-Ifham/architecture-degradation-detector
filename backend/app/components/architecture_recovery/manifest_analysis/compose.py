"""Docker Compose analyzer.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Parses Docker Compose files into declared services, images, build inputs,
    published ports, networks, volumes and dependencies.

    Only declarations are recorded. A `depends_on` entry is a declared
    dependency, not evidence that the two services talk to each other, and an
    environment value that looks like a url is a configured endpoint, not a
    verified connection. Values that could carry credentials are redacted.
"""

from dataclasses import replace
from fnmatch import fnmatchcase
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
    parse_compose_port,
    port_number,
    sanitize_scalar,
)
from app.components.architecture_recovery.manifest_analysis.yaml_support import (
    load_yaml_documents,
    line_of,
)
from app.components.architecture_recovery.repository_inventory.models import (
    FileRecord,
)

COMPOSE_NAME_PATTERNS: tuple[str, ...] = (
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "compose*.yml",
    "compose*.yaml",
    "*.compose.yml",
    "*.compose.yaml",
    # Any name mentioning compose, so a project-specific arrangement such as
    # `local-compose.yaml` is still recognised as a Compose file.
    "*compose*.yml",
    "*compose*.yaml",
)


class ComposeAnalyzer(ManifestAnalyzer):
    """Analyzes a Docker Compose file."""

    name = "compose"

    def __init__(self, max_bytes: int = 1_048_576) -> None:
        """Store the maximum number of bytes read from a single file."""

        self._max_bytes = max_bytes

    def can_analyze(self, file: FileRecord) -> bool:
        """Match Compose by filename convention on a YAML file."""

        if file.format != "yaml":
            return False

        name = file.name.lower()

        return any(fnmatchcase(name, pattern) for pattern in COMPOSE_NAME_PATTERNS)

    def analyze(self, file: FileRecord, absolute_path: Path) -> AnalyzerResult:
        """Extract services, images, ports, networks and dependencies."""

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
                f"could not parse compose file: {loaded.error}",
                file.path,
                loaded.error_line,
                self.name,
            )
            return result

        document = _first_mapping(loaded.documents)

        if document is None:
            result.status = ParseStatus.FAILED
            result.add_diagnostic(
                DiagnosticSeverity.ERROR,
                "compose file has no mapping document",
                file.path,
                None,
                self.name,
            )
            return result

        analysis = _ComposeAnalysis(file, result, loaded.positions)
        analysis.run(document)

        # A file that parsed but declared nothing usable is reported as partial
        # rather than parsed, so a consumer does not read absence as success.
        if not result.resources:
            result.status = ParseStatus.PARTIAL

        return result


def _first_mapping(documents: list) -> dict | None:
    """Return the first mapping document, ignoring null or empty documents."""

    for document in documents:
        if isinstance(document.data, dict):
            return document.data

    return None


class _ComposeAnalysis:
    """Walks one parsed Compose document and records its declarations."""

    def __init__(self, file: FileRecord, result: AnalyzerResult, positions: dict) -> None:
        """Bind the analysis to a file, its result and the position table."""

        self._file = file
        self._result = result
        self._positions = positions

        # Resource ids by declared name, used to resolve in-file references.
        self._services: dict[str, str] = {}
        self._images: dict[str, str] = {}
        self._networks: dict[str, str] = {}
        self._volumes: dict[str, str] = {}
        self._secrets: dict[str, str] = {}
        self._document: dict = {}

    def run(self, document: dict) -> None:
        """Analyze the document's top-level volumes, networks and services."""

        self._document = document

        # Top-level declarations come first so service-level references can
        # resolve against them.
        self._top_level_resources("networks", ResourceKind.NETWORK, self._networks)
        self._top_level_resources("volumes", ResourceKind.VOLUME, self._volumes)
        self._top_level_secrets(document)

        services = document.get("services")

        if not isinstance(services, dict):
            self._result.add_diagnostic(
                DiagnosticSeverity.ERROR,
                "compose file declares no 'services' mapping",
                self._file.path,
                line_of(document, self._positions),
                "compose",
            )
            return

        # Pass one: declare every service so references can resolve regardless
        # of the order services appear in the file.
        for name, spec in services.items():
            if isinstance(spec, dict):
                self._declare_service(str(name), spec)

        # Pass two: resolve references now that every name is known.
        for name, spec in services.items():
            if isinstance(spec, dict):
                self._analyze_service_body(str(name), spec)

    # ------------------------------------------------------------------ #
    # Declaration pass
    # ------------------------------------------------------------------ #

    def _declare_service(self, name: str, spec: dict) -> None:
        """Create the service resource and its image/build declarations."""

        location = self._location(spec)
        service_id = resource_id(self._file.path, ResourceKind.SERVICE, name)

        attributes: dict = {}

        for key in ("container_name", "restart", "user", "working_dir", "profiles"):
            if key in spec:
                value = spec[key]
                attributes[key] = (
                    [str(item) for item in value]
                    if isinstance(value, list)
                    else str(value)
                )

        if self._file.component_id:
            # Links the finding back to the candidate component the inventory
            # associated with this file.
            attributes["component_id"] = self._file.component_id

        self._result.resources.append(
            DeclaredResource(
                id=service_id,
                kind=ResourceKind.SERVICE,
                name=name,
                location=location,
                analyzer="compose",
                method=ExtractionMethod.YAML,
                attributes=attributes,
                evidence=[
                    ExtractedEvidence(
                        "compose_service",
                        "declared under the compose 'services' key",
                        ExtractionMethod.YAML,
                        location,
                    )
                ],
            )
        )

        self._services[name] = service_id

        image = spec.get("image")

        if isinstance(image, str) and image:
            self._record_image(name, service_id, image, location)

        self._record_build(name, service_id, spec.get("build"), location)

    def _record_image(
        self, service: str, service_id: str, image: str, location: SourceLocation
    ) -> None:
        """Record a container image and the service's use of it."""

        # Tags make each reference distinct, so the repository-less name is the
        # shared identity of the image.
        image_name = image.split("@", 1)[0].split(":", 1)[0]
        image_id = self._images.get(image_name)

        if image_id is None:
            image_id = resource_id(self._file.path, ResourceKind.IMAGE, image_name)
            self._images[image_name] = image_id
            self._result.resources.append(
                DeclaredResource(
                    id=image_id,
                    kind=ResourceKind.IMAGE,
                    name=image_name,
                    location=location,
                    analyzer="compose",
                    method=ExtractionMethod.YAML,
                    attributes={"reference": image},
                    evidence=[
                        ExtractedEvidence(
                            "compose_image",
                            f"service '{service}' declares the image '{image}'",
                            ExtractionMethod.YAML,
                            location,
                        )
                    ],
                )
            )

        self._add_relationship(
            RelationshipType.USES_IMAGE,
            RelationshipOrigin.DECLARED_BUILD_INPUT,
            service_id,
            image_id,
            location,
            True,
            f"service '{service}' uses image '{image}'",
        )

    def _record_build(
        self, service: str, service_id: str, build: Any, location: SourceLocation
    ) -> None:
        """Record a build context and Dockerfile path as an unresolved input.

        The context and Dockerfile live outside this file, so they are recorded
        as references for a later stage to resolve against the inventory.
        """

        if build is None:
            return

        if isinstance(build, str):
            context: Any = build
            dockerfile = None
        elif isinstance(build, dict):
            context = build.get("context")
            dockerfile = build.get("dockerfile")
        else:
            return

        if isinstance(context, str) and context:
            self._add_file_reference(
                service_id, context, "compose_build_context", location
            )

        if isinstance(dockerfile, str) and dockerfile:
            self._add_file_reference(
                service_id, dockerfile, "compose_build_dockerfile", location
            )

    # ------------------------------------------------------------------ #
    # Reference pass
    # ------------------------------------------------------------------ #

    def _analyze_service_body(self, name: str, spec: dict) -> None:
        """Record ports, networks, volumes, environment and dependencies."""

        service_id = self._services[name]
        location = self._location(spec)

        self._record_ports(name, service_id, spec, location)
        self._record_networks(service_id, spec.get("networks"), location)
        self._record_volumes(service_id, spec.get("volumes"), location)
        self._record_environment(service_id, spec.get("environment"), location)
        self._record_dependencies(name, service_id, spec, location)
        self._record_secrets(service_id, spec.get("secrets"), location)

    def _record_ports(
        self, name: str, service_id: str, spec: dict, location: SourceLocation
    ) -> None:
        """Record published and exposed ports."""

        for entry in _as_list(spec.get("ports")):
            parts = parse_compose_port(entry)

            if parts is None:
                self._result.add_diagnostic(
                    DiagnosticSeverity.WARNING,
                    f"could not parse port entry {entry!r}",
                    self._file.path,
                    location.line,
                    "compose",
                )
                continue

            self._add_port_endpoint(
                name,
                service_id,
                parts,
                location,
                published=parts.get("host_port") is not None,
                raw=parts.get("raw"),
            )

        for entry in _as_list(spec.get("expose")):
            port = port_number(entry)

            if port is None:
                continue

            self._add_port_endpoint(
                name,
                service_id,
                {
                    "host_ip": None,
                    "host_port": None,
                    "container_port": port,
                    "protocol": "tcp",
                    "raw": str(entry),
                },
                location,
                published=False,
                raw=str(entry),
            )

    def _add_port_endpoint(
        self,
        name: str,
        service_id: str,
        parts: dict,
        location: SourceLocation,
        published: bool,
        raw: str | None,
    ) -> None:
        """Record one port as an endpoint plus the relationship that exposes it."""

        container_port = port_number(parts.get("container_port"))
        host_port = port_number(parts.get("host_port"))
        host_ip = parts.get("host_ip")
        protocol = parts.get("protocol") or "tcp"

        scoped_port = host_port if published else container_port
        key = f"port:{name}:{raw or scoped_port}"

        endpoint = Endpoint(
            id=endpoint_id(self._file.path, key),
            location=location,
            host=str(host_ip) if host_ip else None,
            port=scoped_port,
            protocol=str(protocol),
            source_resource_id=service_id,
            scope="published" if published else "container",
            evidence=[
                ExtractedEvidence(
                    "compose_port",
                    f"service '{name}' declares the port mapping '{raw or scoped_port}'",
                    ExtractionMethod.YAML,
                    location,
                )
            ],
        )

        self._result.endpoints.append(endpoint)

        relationship_type = (
            RelationshipType.PUBLISHES_PORT
            if published
            else RelationshipType.EXPOSES_PORT
        )

        self._add_relationship(
            relationship_type,
            RelationshipOrigin.CONFIGURED_ENDPOINT,
            service_id,
            endpoint.id,
            location,
            True,
            f"service '{name}' "
            f"{'publishes' if published else 'exposes'} {raw or scoped_port}",
        )

    def _record_networks(
        self, service_id: str, networks: Any, location: SourceLocation
    ) -> None:
        """Record the networks a service joins."""

        # Compose accepts both a list of names and a mapping of name to options.
        names = list(networks) if isinstance(networks, (list, dict)) else []

        for name in names:
            network_name = str(name)
            network_id = self._networks.get(network_name)

            if network_id is None:
                network_id = resource_id(
                    self._file.path, ResourceKind.NETWORK, network_name
                )
                self._networks[network_name] = network_id
                self._result.resources.append(
                    DeclaredResource(
                        id=network_id,
                        kind=ResourceKind.NETWORK,
                        name=network_name,
                        location=location,
                        analyzer="compose",
                        method=ExtractionMethod.YAML,
                        evidence=[
                            ExtractedEvidence(
                                "compose_network",
                                f"network '{network_name}' referenced by a service "
                                "but not declared at the top level",
                                ExtractionMethod.YAML,
                                location,
                            )
                        ],
                    )
                )

            self._add_relationship(
                RelationshipType.JOINS_NETWORK,
                RelationshipOrigin.CONFIGURED_ENDPOINT,
                service_id,
                network_id,
                location,
                True,
                f"service joins network '{network_name}'",
            )

    def _record_volumes(
        self, service_id: str, volumes: Any, location: SourceLocation
    ) -> None:
        """Record volume mounts, distinguishing named volumes from bind mounts."""

        for entry in _as_list(volumes):
            source: str | None = None
            target: str | None = None
            read_only = False
            mount_type = "volume"
            raw: str | None = None

            if isinstance(entry, str):
                raw = entry
                parts = entry.split(":")
                source = parts[0] if len(parts) > 1 else None
                target = parts[1] if len(parts) > 1 else parts[0]
                read_only = len(parts) > 2 and parts[2].startswith("ro")
            elif isinstance(entry, dict):
                source = _text(entry.get("source"))
                target = _text(entry.get("target"))
                mount_type = str(entry.get("type") or "volume")
                read_only = bool(entry.get("read_only"))
            else:
                continue

            # A path source is a bind mount onto the host, not a named resource.
            is_bind = mount_type == "bind" or (
                source is not None
                and source.startswith(("./", "../", "/", "~", "."))
            )

            if is_bind:
                self._result.references.append(
                    ResourceReference(
                        id=reference_id(
                            self._file.path,
                            ReferenceKind.FILE,
                            source or str(target),
                            "compose_bind_mount",
                        ),
                        kind=ReferenceKind.FILE,
                        name=source or str(target),
                        location=location,
                        status=ReferenceStatus.UNRESOLVED,
                        reference_type="compose_bind_mount",
                        reason="bind mount source is outside the manifest",
                        evidence=[
                            ExtractedEvidence(
                                "compose_volume",
                                f"service mounts the host path '{source}'",
                                ExtractionMethod.YAML,
                                location,
                            )
                        ],
                    )
                )
                continue

            if not source:
                continue

            volume_id = self._volumes.get(source)

            if volume_id is None:
                volume_id = resource_id(self._file.path, ResourceKind.VOLUME, source)
                self._volumes[source] = volume_id
                self._result.resources.append(
                    DeclaredResource(
                        id=volume_id,
                        kind=ResourceKind.VOLUME,
                        name=source,
                        location=location,
                        analyzer="compose",
                        method=ExtractionMethod.YAML,
                        evidence=[
                            ExtractedEvidence(
                                "compose_volume",
                                f"volume '{source}' referenced by a service but not "
                                "declared at the top level",
                                ExtractionMethod.YAML,
                                location,
                            )
                        ],
                    )
                )

            self._add_relationship(
                RelationshipType.MOUNTS_VOLUME,
                RelationshipOrigin.CONFIGURED_FILESYSTEM,
                service_id,
                volume_id,
                location,
                True,
                f"service mounts volume '{source}' at '{target}'"
                + (" (read-only)" if read_only else ""),
            )

    def _record_environment(
        self, service_id: str, environment: Any, location: SourceLocation
    ) -> None:
        """Record environment variable names, redacting sensitive values.

        A value that names an endpoint is recorded as a configured endpoint, and
        additionally linked to the service it names when that service is declared
        in this same file.
        """

        entries = _environment_items(environment)

        if not entries:
            return

        recorded: list[dict] = []

        for key, value in entries:
            sanitized = sanitize_scalar(value, key)

            item: dict = {"name": key}

            if sanitized.value is not None:
                item["value"] = sanitized.value

            if sanitized.redacted:
                item["redacted"] = True

            recorded.append(item)

            if sanitized.value is None:
                continue

            candidate = extract_endpoint_candidate(sanitized.value)

            if candidate is None:
                continue

            self._add_configured_endpoint(
                service_id, key, candidate, location, sanitized.value
            )

        if not recorded:
            return

        # Attribute the environment onto the service resource so the values live
        # with the declaration they belong to.
        for resource in self._result.resources:
            if resource.id == service_id:
                resource.attributes["environment"] = recorded
                break

    def _add_configured_endpoint(
        self, service_id: str, key: str, candidate, location: SourceLocation, value: str
    ) -> None:
        """Record an endpoint found in an environment value."""

        endpoint = Endpoint(
            id=endpoint_id(self._file.path, f"env:{key}"),
            location=location,
            host=candidate.host,
            port=candidate.port,
            protocol=candidate.scheme,
            source_resource_id=service_id,
            scope="environment",
            evidence=[
                ExtractedEvidence(
                    "compose_environment",
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
            service_id,
            endpoint.id,
            location,
            True,
            f"environment variable '{key}' configures the endpoint "
            f"'{candidate.sanitized_value or value}'",
        )

        # If the endpoint names another service in this file, record that as a
        # *configured* reference. It still does not prove traffic flows.
        target_id = self._services.get(candidate.host)

        if target_id is not None and target_id != service_id:
            self._add_relationship(
                RelationshipType.REFERS_TO_SERVICE,
                RelationshipOrigin.CONFIGURED_ENDPOINT,
                service_id,
                target_id,
                location,
                True,
                f"environment variable '{key}' names the service "
                f"'{candidate.host}' declared in this file",
            )
        elif candidate.host and candidate.host not in self._services:
            self._result.references.append(
                ResourceReference(
                    id=reference_id(
                        self._file.path,
                        ReferenceKind.SERVICE,
                        candidate.host,
                        "compose_environment",
                    ),
                    kind=ReferenceKind.SERVICE,
                    name=candidate.host,
                    location=location,
                    status=ReferenceStatus.UNRESOLVED,
                    reference_type="compose_environment",
                    reason=(
                        f"environment variable '{key}' names a host that is not a "
                        "service declared in this file"
                    ),
                    evidence=[
                        ExtractedEvidence(
                            "compose_environment",
                            f"'{key}' points at '{candidate.host}'",
                            ExtractionMethod.YAML,
                            location,
                        )
                    ],
                )
            )

    def _record_dependencies(
        self, name: str, service_id: str, spec: dict, location: SourceLocation
    ) -> None:
        """Record explicit service dependencies."""

        # `depends_on` accepts a list of names or a mapping of name to options,
        # and the long form attaches a `condition`.
        depends_on = spec.get("depends_on")
        conditions: dict[str, str] = {}

        if isinstance(depends_on, dict):
            targets = list(depends_on)
            for target, options in depends_on.items():
                if isinstance(options, dict) and options.get("condition"):
                    conditions[str(target)] = str(options["condition"])
        elif isinstance(depends_on, list):
            targets = depends_on
        else:
            targets = []

        for target in targets:
            target_name = str(target)
            target_id = self._services.get(target_name)
            resolved = target_id is not None

            condition = conditions.get(target_name)
            detail = f"service '{name}' declares depends_on '{target_name}'"

            if condition:
                detail += f" (condition: {condition})"

            self._add_relationship(
                RelationshipType.DEPENDS_ON,
                RelationshipOrigin.DECLARED_DEPENDENCY,
                service_id,
                target_id or reference_id(
                    self._file.path,
                    ReferenceKind.SERVICE,
                    target_name,
                    "compose_depends_on",
                ),
                location,
                resolved,
                detail,
            )

            if not resolved:
                self._result.references.append(
                    ResourceReference(
                        id=reference_id(
                            self._file.path,
                            ReferenceKind.SERVICE,
                            target_name,
                            "compose_depends_on",
                        ),
                        kind=ReferenceKind.SERVICE,
                        name=target_name,
                        location=location,
                        status=ReferenceStatus.UNRESOLVED,
                        reference_type="compose_depends_on",
                        reason="depends_on target is not declared in this file",
                        evidence=[
                            ExtractedEvidence(
                                "compose_depends_on",
                                detail,
                                ExtractionMethod.YAML,
                                location,
                            )
                        ],
                    )
                )

        # `links` predates `depends_on` but carries the same intent, so it is
        # recorded as a declared dependency with the legacy origin noted.
        for entry in _as_list(spec.get("links")):
            target_name = str(entry).split(":", 1)[0]
            target_id = self._services.get(target_name)

            self._add_relationship(
                RelationshipType.DEPENDS_ON,
                RelationshipOrigin.DECLARED_DEPENDENCY,
                service_id,
                target_id
                or reference_id(
                    self._file.path,
                    ReferenceKind.SERVICE,
                    target_name,
                    "compose_links",
                ),
                location,
                target_id is not None,
                f"service '{name}' declares the legacy link '{target_name}'",
            )

    def _record_secrets(
        self, service_id: str, secrets: Any, location: SourceLocation
    ) -> None:
        """Record secret references by name, never by value."""

        for entry in _as_list(secrets):
            if isinstance(entry, dict):
                secret_name = _text(entry.get("source") or entry.get("secret"))
            else:
                secret_name = _text(entry)

            if not secret_name:
                continue

            target_id = self._secrets.get(secret_name)

            if target_id is None:
                target_id = resource_id(
                    self._file.path, ResourceKind.SECRET, secret_name
                )
                self._secrets[secret_name] = target_id
                self._result.resources.append(
                    DeclaredResource(
                        id=target_id,
                        kind=ResourceKind.SECRET,
                        name=secret_name,
                        location=location,
                        analyzer="compose",
                        method=ExtractionMethod.YAML,
                        attributes={"values_extracted": False},
                        evidence=[
                            ExtractedEvidence(
                                "compose_secret",
                                f"secret '{secret_name}' is referenced; its value is "
                                "never read",
                                ExtractionMethod.YAML,
                                location,
                            )
                        ],
                    )
                )

            self._add_relationship(
                RelationshipType.REFERENCES_SECRET,
                RelationshipOrigin.DECLARED_DEPENDENCY,
                service_id,
                target_id,
                location,
                True,
                f"service references secret '{secret_name}' (value not extracted)",
            )

    # ------------------------------------------------------------------ #
    # Top-level declarations
    # ------------------------------------------------------------------ #

    def _top_level_resources(
        self, key: str, kind: ResourceKind, registry: dict[str, str]
    ) -> None:
        """Declare top-level networks and volumes, flagging external ones."""

        section = self._document_section(key)

        for name, spec in section.items():
            external = bool(spec.get("external")) if isinstance(spec, dict) else False
            resource_identifier = resource_id(self._file.path, kind, name)
            registry[name] = resource_identifier

            self._result.resources.append(
                DeclaredResource(
                    id=resource_identifier,
                    kind=kind,
                    name=name,
                    location=self._location(spec),
                    analyzer="compose",
                    method=ExtractionMethod.YAML,
                    attributes={
                        "external": external,
                        "name_override": _text(spec.get("name"))
                        if isinstance(spec, dict)
                        else None,
                    },
                    evidence=[
                        ExtractedEvidence(
                            "compose_external_resource"
                            if external
                            else "compose_top_level",
                            f"{kind.value} '{name}' is declared"
                            + (" as external" if external else ""),
                            ExtractionMethod.YAML,
                            self._location(spec),
                        )
                    ],
                )
            )

    def _top_level_secrets(self, document: dict) -> None:
        """Declare top-level secrets by name only, never by value."""

        secrets = document.get("secrets")

        if not isinstance(secrets, dict):
            return

        for name, spec in secrets.items():
            secret_id = resource_id(self._file.path, ResourceKind.SECRET, str(name))
            self._secrets[str(name)] = secret_id
            external = bool(spec.get("external")) if isinstance(spec, dict) else False

            self._result.resources.append(
                DeclaredResource(
                    id=secret_id,
                    kind=ResourceKind.SECRET,
                    name=str(name),
                    location=self._location(spec),
                    analyzer="compose",
                    method=ExtractionMethod.YAML,
                    # The declaration is recorded; the secret material is not.
                    attributes={"external": external, "values_extracted": False},
                    evidence=[
                        ExtractedEvidence(
                            "compose_secret",
                            f"secret '{name}' is declared; its value is never read",
                            ExtractionMethod.YAML,
                            self._location(spec),
                        )
                    ],
                )
            )

    def _document_section(self, key: str) -> dict:
        """Return a top-level mapping section of the parsed document."""

        section = self._document.get(key)

        return section if isinstance(section, dict) else {}

    # ------------------------------------------------------------------ #
    # Small helpers
    # ------------------------------------------------------------------ #

    def _location(self, node: Any) -> SourceLocation:
        """Build a source location for a parsed node."""

        return SourceLocation(
            path=self._file.path, line=line_of(node, self._positions)
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
                        "compose_declaration",
                        detail,
                        ExtractionMethod.YAML,
                        location,
                    )
                ],
            )
        )

    def _add_file_reference(
        self,
        source_id: str,
        path: str,
        reference_type: str,
        location: SourceLocation,
    ) -> None:
        """Record a path that points outside the manifest."""

        self._result.references.append(
            ResourceReference(
                id=reference_id(
                    self._file.path, ReferenceKind.FILE, path, reference_type
                ),
                kind=ReferenceKind.FILE,
                name=path,
                location=location,
                status=ReferenceStatus.UNRESOLVED,
                reference_type=reference_type,
                reason="path is outside the manifest and needs the inventory to resolve",
                evidence=[
                    ExtractedEvidence(
                        reference_type,
                        f"build input '{path}' is declared by a service",
                        ExtractionMethod.YAML,
                        location,
                    )
                ],
            )
        )


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


def _environment_items(environment: Any) -> list[tuple[str, Any]]:
    """Normalise the two Compose environment forms into key/value pairs.

    Both the mapping form (`KEY: value`) and the list form (`KEY=value`) are
    supported; a list entry without `=` declares a name with no value.
    """

    if isinstance(environment, dict):
        return [(str(key), value) for key, value in environment.items()]

    if isinstance(environment, list):
        items = []

        for entry in environment:
            if not isinstance(entry, str):
                continue

            key, _, value = entry.partition("=")
            items.append((key.strip(), value if value else None))

        return items

    return []
