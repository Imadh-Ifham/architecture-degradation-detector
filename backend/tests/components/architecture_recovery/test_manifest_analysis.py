"""Tests for the manifest analysis subcomponent.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Covers each analyzer against representative manifests, the analyzer
    selection rules, the analysis service, and the security properties that
    matter most: credentials and Secret values must never reach the output, and
    no declaration may be promoted to a verified communication relationship.

    Assertions check extracted resources and relationships, not merely that a
    file parsed.
"""

import json
from pathlib import Path

import pytest

from app.components.architecture_recovery.manifest_analysis import (
    MANIFEST_ANALYSIS_FILE_NAME,
    AnalysisInputError,
    AnalyzerRegistry,
    ComposeAnalyzer,
    DockerfileAnalyzer,
    ExtractionMethod,
    KubernetesAnalyzer,
    ManifestAnalysisService,
    OpenApiAnalyzer,
    ParseStatus,
    ProtobufAnalyzer,
    ReferenceStatus,
    RelationshipOrigin,
    RelationshipType,
    ResourceKind,
    has_template_expressions,
    load_inventory,
    write_manifest_analysis,
)
from app.components.architecture_recovery.manifest_analysis.redaction import (
    extract_endpoint_candidate,
    is_sensitive_key,
    parse_compose_port,
    sanitize_scalar,
    sanitize_url,
)
from app.components.architecture_recovery.manifest_analysis.yaml_support import (
    load_yaml_documents,
)
from app.components.architecture_recovery.repository_inventory import (
    FileClassifier,
    FileRecord,
    RepositoryInventory,
    RepositoryInventoryService,
    RepositoryRef,
    build_file_id,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "manifest_analysis"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def classify(relative_path: str) -> FileRecord:
    """Build a file record the way the inventory would."""

    path = FIXTURES / relative_path

    record = FileRecord(
        id=build_file_id(relative_path),
        path=relative_path,
        name=Path(relative_path).name,
        extension=Path(relative_path).suffix.lower(),
        size_bytes=path.stat().st_size,
        depth=len(relative_path.split("/")),
    )

    FileClassifier().classify(record)
    return record


def analyze(analyzer, relative_path: str):
    """Run an analyzer over a fixture file."""

    return analyzer.analyze(classify(relative_path), FIXTURES / relative_path)


def resource_named(result, name: str, kind: ResourceKind | None = None):
    """Return the resource with the given name, failing the test when absent."""

    for resource in result.resources:
        if resource.name == name and (kind is None or resource.kind is kind):
            return resource

    present = [(item.kind.value, item.name) for item in result.resources]
    raise AssertionError(f"resource '{name}' not found; present: {present}")


def relationships_of(result, relationship_type: RelationshipType) -> list:
    """Return every relationship of the given type."""

    return [item for item in result.relationships if item.type is relationship_type]


def reference_named(result, name: str):
    """Return the reference with the given name, failing the test when absent."""

    for reference in result.references:
        if reference.name == name:
            return reference

    present = [(item.kind.value, item.name) for item in result.references]
    raise AssertionError(f"reference '{name}' not found; present: {present}")


def serialized(result) -> str:
    """Serialise everything a result produced, for leak checks."""

    return json.dumps(
        {
            "resources": [item.to_dict() for item in result.resources],
            "relationships": [item.to_dict() for item in result.relationships],
            "endpoints": [item.to_dict() for item in result.endpoints],
            "references": [item.to_dict() for item in result.references],
            "diagnostics": [item.to_dict() for item in result.diagnostics],
        }
    )


# --------------------------------------------------------------------------- #
# Analyzer selection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("relative_path", "analyzer_name"),
    [
        ("compose/valid-compose.yaml", "compose"),
        ("compose/minimal-compose.yaml", "compose"),
        ("kubernetes/multi-document.yaml", "kubernetes"),
        ("kubernetes/no-kind.yaml", "kubernetes"),
        ("dockerfile/Dockerfile", "dockerfile"),
        ("api/openapi-cart.yaml", "openapi"),
        ("api/openapi-cart.json", "openapi"),
        ("proto/cart.proto", "protobuf"),
    ],
)
def test_registry_selects_the_right_analyzer(
    relative_path: str, analyzer_name: str
) -> None:
    analyzer = AnalyzerRegistry().select(classify(relative_path))

    assert analyzer is not None
    assert analyzer.name == analyzer_name


def test_registry_offers_compose_before_kubernetes() -> None:
    """Both are YAML deployment manifests, so order decides the winner."""

    names = AnalyzerRegistry().names()

    assert names.index("compose") < names.index("kubernetes")


def test_compose_wins_over_the_permissive_kubernetes_fallback() -> None:
    """The Kubernetes analyzer is a catch-all, so ordering must decide.

    `can_analyze` is deliberately broad for the fallback analyzer; the guarantee
    that a Compose file is parsed as Compose comes from the registry offering
    Compose first, not from the fallback declining it.
    """

    registry = AnalyzerRegistry()
    fallback = KubernetesAnalyzer()

    assert fallback.can_analyze(classify("kubernetes/multi-document.yaml"))
    # Deliberately permissive: it would also accept a Compose file.
    assert fallback.can_analyze(classify("compose/valid-compose.yaml"))

    # What actually protects a Compose file is the selection order.
    assert registry.select(classify("compose/valid-compose.yaml")).name == "compose"
    assert (
        registry.select(classify("kubernetes/multi-document.yaml")).name
        == "kubernetes"
    )


def test_source_and_configuration_files_are_not_candidates() -> None:
    # A .tf file is infrastructure configuration, which this stage does not
    # claim, so it is not reported on at all.
    assert AnalyzerRegistry().is_candidate(classify("kubernetes/multi-document.yaml"))
    assert AnalyzerRegistry().is_candidate(classify("proto/cart.proto"))


# --------------------------------------------------------------------------- #
# Docker Compose
# --------------------------------------------------------------------------- #


@pytest.fixture
def compose_result():
    return analyze(ComposeAnalyzer(), "compose/valid-compose.yaml")


def test_compose_declares_its_services(compose_result) -> None:
    assert compose_result.status is ParseStatus.PARSED

    web = resource_named(compose_result, "web", ResourceKind.SERVICE)

    assert web.attributes["container_name"] == "web-app"


def test_compose_records_images_and_build_inputs(compose_result) -> None:
    resource_named(compose_result, "example/web", ResourceKind.IMAGE)

    uses_image = relationships_of(compose_result, RelationshipType.USES_IMAGE)

    assert len(uses_image) == 2
    assert all(
        item.origin is RelationshipOrigin.DECLARED_BUILD_INPUT
        for item in uses_image
    )

    # A build context and Dockerfile live outside this file, so they stay
    # unresolved references rather than guessed relationships.
    assert reference_named(compose_result, "./web").status is (
        ReferenceStatus.UNRESOLVED
    )
    assert reference_named(compose_result, "Dockerfile").reference_type == (
        "compose_build_dockerfile"
    )


def test_compose_distinguishes_published_from_exposed_ports(compose_result) -> None:
    published = relationships_of(compose_result, RelationshipType.PUBLISHES_PORT)
    exposed = relationships_of(compose_result, RelationshipType.EXPOSES_PORT)

    assert len(published) == 2
    assert len(exposed) == 1

    ports = {(item.host, item.port, item.protocol) for item in compose_result.endpoints}

    assert (None, 8080, "tcp") in ports
    assert ("127.0.0.1", 9000, "udp") in ports
    assert (None, 5432, "tcp") in ports


def test_compose_records_networks_including_external(compose_result) -> None:
    frontend = resource_named(compose_result, "frontend", ResourceKind.NETWORK)
    backend = resource_named(compose_result, "backend", ResourceKind.NETWORK)

    assert frontend.attributes["external"] is False
    assert backend.attributes["external"] is True

    joins = relationships_of(compose_result, RelationshipType.JOINS_NETWORK)

    assert len(joins) == 3
    assert all(
        item.origin is RelationshipOrigin.CONFIGURED_ENDPOINT for item in joins
    )


def test_compose_records_volumes_and_bind_mounts(compose_result) -> None:
    web_data = resource_named(compose_result, "web-data", ResourceKind.VOLUME)
    db_data = resource_named(compose_result, "db-data", ResourceKind.VOLUME)

    assert db_data.attributes["external"] is True
    assert web_data.attributes["external"] is False

    mounts = relationships_of(compose_result, RelationshipType.MOUNTS_VOLUME)

    # Two of the three mounts are named volumes; the third is a host path, which
    # is a filesystem reference rather than a volume resource.
    assert len(mounts) == 2
    assert all(
        item.origin is RelationshipOrigin.CONFIGURED_FILESYSTEM for item in mounts
    )

    assert reference_named(compose_result, "./local").reference_type == (
        "compose_bind_mount"
    )


def test_compose_redacts_sensitive_environment_values(compose_result) -> None:
    web = resource_named(compose_result, "web", ResourceKind.SERVICE)
    entries = {item["name"]: item for item in web.attributes["environment"]}

    assert entries["DB_PASSWORD"]["redacted"] is True
    assert "value" not in entries["DB_PASSWORD"]
    assert entries["LOG_LEVEL"]["value"] == "info"
    assert entries["LOG_FORMAT"]["value"] == "json"

    assert "hunter2" not in serialized(compose_result)


def test_compose_turns_environment_urls_into_configured_endpoints(
    compose_result,
) -> None:
    endpoints = [item for item in compose_result.endpoints if item.scope == "environment"]

    assert len(endpoints) == 1
    assert endpoints[0].host == "db"
    assert endpoints[0].port == 5432
    assert endpoints[0].protocol == "postgres"


def test_compose_links_a_configured_endpoint_to_its_service(compose_result) -> None:
    """The host `db` is a declared service, so the reference resolves."""

    refs = relationships_of(compose_result, RelationshipType.REFERS_TO_SERVICE)
    db_id = resource_named(compose_result, "db", ResourceKind.SERVICE).id

    assert any(
        item.target_id == db_id
        and item.origin is RelationshipOrigin.CONFIGURED_ENDPOINT
        for item in refs
    )


def test_compose_records_declared_dependencies(compose_result) -> None:
    depends_on = relationships_of(compose_result, RelationshipType.DEPENDS_ON)

    assert all(
        item.origin is RelationshipOrigin.DECLARED_DEPENDENCY for item in depends_on
    )

    db_id = resource_named(compose_result, "db", ResourceKind.SERVICE).id
    resolved = [item for item in depends_on if item.resolved]

    assert [item.target_id for item in resolved] == [db_id]
    assert any("service_healthy" in item.evidence[0].detail for item in resolved)

    # A dependency on a service this file does not declare stays unresolved.
    unresolved = [item for item in depends_on if not item.resolved]

    assert len(unresolved) == 1
    assert reference_named(compose_result, "unknown-service").reference_type == (
        "compose_depends_on"
    )


def test_compose_records_secret_references_without_values(compose_result) -> None:
    secret = resource_named(compose_result, "api_key", ResourceKind.SECRET)

    assert secret.attributes["values_extracted"] is False
    assert secret.attributes["external"] is True

    links = relationships_of(compose_result, RelationshipType.REFERENCES_SECRET)

    assert len(links) == 1


def test_compose_reports_line_numbers(compose_result) -> None:
    web = resource_named(compose_result, "web", ResourceKind.SERVICE)

    assert web.location.line == 2
    assert web.location.path == "compose/valid-compose.yaml"


def test_compose_minimal_file_parses_with_missing_optional_fields() -> None:
    result = analyze(ComposeAnalyzer(), "compose/minimal-compose.yaml")

    assert result.status is ParseStatus.PARSED
    assert len(result.resources) == 2
    assert not result.diagnostics


def test_compose_malformed_file_fails_without_raising() -> None:
    result = analyze(ComposeAnalyzer(), "compose/malformed-compose.yaml")

    assert result.status is ParseStatus.FAILED
    assert result.diagnostics[0].line is not None


# --------------------------------------------------------------------------- #
# Kubernetes
# --------------------------------------------------------------------------- #


@pytest.fixture
def kubernetes_result():
    return analyze(KubernetesAnalyzer(), "kubernetes/multi-document.yaml")


def test_kubernetes_reads_every_document(kubernetes_result) -> None:
    assert kubernetes_result.status is ParseStatus.PARSED

    kinds = {item.kind for item in kubernetes_result.resources}

    assert ResourceKind.WORKLOAD in kinds
    assert ResourceKind.KUBERNETES_SERVICE in kinds
    assert ResourceKind.CONFIG_MAP in kinds
    assert ResourceKind.SECRET in kinds
    assert ResourceKind.VOLUME in kinds
    assert ResourceKind.CONTAINER in kinds


def test_kubernetes_records_namespace_and_workload_details(kubernetes_result) -> None:
    workload = resource_named(kubernetes_result, "cart", ResourceKind.WORKLOAD)

    assert workload.namespace == "shop"
    assert workload.attributes["kind"] == "Deployment"
    assert workload.attributes["pod_labels"] == {"app": "cart"}


def test_kubernetes_records_container_images_and_ports(kubernetes_result) -> None:
    container = resource_named(kubernetes_result, "cart", ResourceKind.CONTAINER)
    image = resource_named(kubernetes_result, "gcr.io/example/cart", ResourceKind.IMAGE)

    assert container.attributes["workload"] == "cart"
    assert image.attributes["reference"] == "gcr.io/example/cart:1.2.3"

    ports = [
        item for item in kubernetes_result.endpoints if item.scope == "container"
    ]

    assert [item.port for item in ports] == [8080]


def test_kubernetes_matches_a_service_selector_to_its_workload(
    kubernetes_result,
) -> None:
    matches = relationships_of(kubernetes_result, RelationshipType.SELECTS_WORKLOAD)

    assert len(matches) == 1

    workload_id = resource_named(kubernetes_result, "cart", ResourceKind.WORKLOAD).id
    service_id = resource_named(
        kubernetes_result, "cart", ResourceKind.KUBERNETES_SERVICE
    ).id

    assert matches[0].source_id == service_id
    assert matches[0].target_id == workload_id


def test_kubernetes_reports_a_selector_that_matches_nothing(
    kubernetes_result,
) -> None:
    """Ambiguity is recorded, not treated as an error or a relationship."""

    matched_sources = {
        item.source_id
        for item in relationships_of(kubernetes_result, RelationshipType.SELECTS_WORKLOAD)
    }
    orphan_id = resource_named(
        kubernetes_result, "orphan", ResourceKind.KUBERNETES_SERVICE
    ).id

    assert orphan_id not in matched_sources
    assert any(
        "selector matches no workload" in item.message
        for item in kubernetes_result.diagnostics
    )


def test_kubernetes_resolves_config_and_secret_references(kubernetes_result) -> None:
    config_links = relationships_of(
        kubernetes_result, RelationshipType.REFERENCES_CONFIG
    )
    secret_links = relationships_of(
        kubernetes_result, RelationshipType.REFERENCES_SECRET
    )

    assert config_links
    assert secret_links
    assert all(item.resolved for item in config_links)
    assert all(item.resolved for item in secret_links)

    # An undeclared Secret is recorded as an unresolved reference.
    undeclared = reference_named(kubernetes_result, "undeclared-secret")

    assert undeclared.status is ReferenceStatus.UNRESOLVED
    assert undeclared.reason == "not declared in this file"


def test_kubernetes_records_volume_claim_as_a_mount(kubernetes_result) -> None:
    mounts = relationships_of(kubernetes_result, RelationshipType.MOUNTS_VOLUME)

    assert any(
        item.origin is RelationshipOrigin.CONFIGURED_FILESYSTEM and item.resolved
        for item in mounts
    )

    assert reference_named(kubernetes_result, "cart-data").status is (
        ReferenceStatus.RESOLVED
    )


def test_kubernetes_never_exposes_config_map_or_secret_values(
    kubernetes_result,
) -> None:
    config_map = resource_named(kubernetes_result, "cart-config", ResourceKind.CONFIG_MAP)
    secret = resource_named(kubernetes_result, "cart-secret", ResourceKind.SECRET)

    # Only key names are recorded, and the flag says so explicitly.
    assert sorted(config_map.attributes["keys"]) == ["DB_PASSWORD", "LOG_LEVEL"]
    assert sorted(secret.attributes["keys"]) == ["api_key", "inline", "password"]
    assert config_map.attributes["values_extracted"] is False
    assert secret.attributes["values_extracted"] is False
    assert secret.attributes["secret_type"] == "Opaque"

    blob = serialized(kubernetes_result)

    for secret_value in (
        "c3VwZXJzZWNyZXQ=",
        "YWJjMTIz",
        "plaintext-secret",
        "configmap-secret-value",
    ):
        assert secret_value not in blob


def test_kubernetes_redacts_sensitive_container_environment(
    kubernetes_result,
) -> None:
    workload = resource_named(kubernetes_result, "cart", ResourceKind.WORKLOAD)
    entries = {item["name"]: item for item in workload.attributes["environment"]}

    assert entries["LOG_LEVEL"]["value"] == "debug"
    assert entries["DB_PASSWORD"]["from_secret"] == "cart-secret"
    assert entries["CONFIG_PATH"]["from_config_map"] == "cart-config"
    assert entries["API_TOKEN"]["from_secret"] == "undeclared-secret"


def test_kubernetes_reads_containers_nested_in_a_cronjob(kubernetes_result) -> None:
    container = resource_named(kubernetes_result, "sweeper", ResourceKind.CONTAINER)

    assert container.attributes["workload"] == "cart-sweeper"


def test_kubernetes_reports_an_unsupported_kind(kubernetes_result) -> None:
    assert any(
        "unsupported kubernetes kind 'Ingress'" in item.message
        for item in kubernetes_result.diagnostics
    )
    assert not any(item.name == "cart-ingress" for item in kubernetes_result.resources)


def test_kubernetes_document_without_a_kind_is_reported() -> None:
    result = analyze(KubernetesAnalyzer(), "kubernetes/no-kind.yaml")

    assert result.status is ParseStatus.PARTIAL
    assert any("without a 'kind'" in item.message for item in result.diagnostics)


def test_kubernetes_malformed_file_fails_without_raising() -> None:
    result = analyze(KubernetesAnalyzer(), "kubernetes/malformed.yaml")

    assert result.status is ParseStatus.FAILED
    assert result.diagnostics[0].severity.value == "error"


def test_templated_manifest_is_skipped_not_failed() -> None:
    """A Helm template is not malformed, so it is reported as skipped."""

    result = analyze(KubernetesAnalyzer(), "kubernetes/templated.yaml")

    assert result.status is ParseStatus.SKIPPED
    assert result.resources == []
    assert any(
        "templated manifest cannot be parsed" in item.message
        for item in result.diagnostics
    )


def test_template_expression_detection_ignores_shell_style_variables() -> None:
    """Compose interpolation must not be mistaken for templating."""

    assert not has_template_expressions(
        "services:\n  web:\n    image: ${REGISTRY}/web:${TAG}\n"
    )
    assert has_template_expressions("name: {{ .Release.Name }}")


# --------------------------------------------------------------------------- #
# Dockerfile
# --------------------------------------------------------------------------- #


@pytest.fixture
def dockerfile_result():
    return analyze(DockerfileAnalyzer(), "dockerfile/Dockerfile")


def test_dockerfile_records_every_build_stage(dockerfile_result) -> None:
    assert dockerfile_result.status is ParseStatus.PARSED

    stages = [
        item
        for item in dockerfile_result.resources
        if item.kind is ResourceKind.BUILD_STAGE
    ]

    assert [item.name for item in stages] == ["build", "runtime"]
    assert stages[0].attributes["base_image"] == "golang:1.22"
    assert stages[1].attributes["base_image"] == "alpine:3.20"


def test_dockerfile_links_stages_to_their_base_images(dockerfile_result) -> None:
    builds_from = relationships_of(dockerfile_result, RelationshipType.BUILDS_FROM)

    assert all(
        item.origin is RelationshipOrigin.DECLARED_BUILD_INPUT
        for item in builds_from
    )

    target_names = {
        next(
            item.name for item in dockerfile_result.resources if item.id == relationship.target_id
        )
        for relationship in builds_from
    }

    assert target_names == {"golang:1.22", "alpine:3.20", "build"}


def test_dockerfile_resolves_copy_from_stage(dockerfile_result) -> None:
    present = reference_named(dockerfile_result, "build")
    missing = reference_named(dockerfile_result, "missing-stage")

    assert present.status is ReferenceStatus.RESOLVED
    assert present.target_id is not None
    assert missing.status is ReferenceStatus.UNRESOLVED
    assert missing.reason == "stage is not declared in this file"


def test_dockerfile_records_exposed_ports(dockerfile_result) -> None:
    exposed = relationships_of(dockerfile_result, RelationshipType.EXPOSES_PORT)

    assert len(exposed) == 2

    ports = {(item.port, item.protocol) for item in dockerfile_result.endpoints}

    assert (8080, "tcp") in ports
    assert (9090, "udp") in ports


def test_dockerfile_redacts_sensitive_environment_values(dockerfile_result) -> None:
    stage = resource_named(dockerfile_result, "runtime", ResourceKind.BUILD_STAGE)
    entries = {item["name"]: item for item in stage.attributes["environment"]}

    assert entries["LOG_LEVEL"]["value"] == "info"
    assert entries["DB_PASSWORD"]["redacted"] is True
    assert "value" not in entries["DB_PASSWORD"]
    assert "hunter2" not in serialized(dockerfile_result)


def test_dockerfile_handles_continuation_lines(dockerfile_result) -> None:
    stage = resource_named(dockerfile_result, "runtime", ResourceKind.BUILD_STAGE)

    # The three-variable ENV block spans continuation lines and must all parse.
    assert {"LOG_LEVEL", "DB_PASSWORD", "REGISTRY_URL"} <= set(
        item["name"] for item in stage.attributes["environment"]
    )


def test_dockerfile_recognises_an_environment_endpoint(dockerfile_result) -> None:
    endpoints = [
        item
        for item in dockerfile_result.endpoints
        if item.scope == "build_configuration"
    ]

    assert any(item.host == "registry.example.com" for item in endpoints)


def test_dockerfile_records_runtime_configuration(dockerfile_result) -> None:
    stage = resource_named(dockerfile_result, "runtime", ResourceKind.BUILD_STAGE)

    assert stage.attributes["entrypoint"] == '["/usr/local/bin/cart"]'
    assert stage.attributes["cmd"] == '["--serve"]'
    assert stage.attributes["user"] == "nobody"
    assert "healthcheck" in stage.attributes


def test_dockerfile_records_copied_build_inputs(dockerfile_result) -> None:
    sources = {
        item.name
        for item in dockerfile_result.references
        if item.reference_type == "dockerfile_copy_source"
    }

    assert {"go.mod", "go.sum", ".", "config/app.yaml"} <= sources

    assert all(
        item.status is ReferenceStatus.UNRESOLVED
        for item in dockerfile_result.references
        if item.reference_type == "dockerfile_copy_source"
    )


def test_dockerfile_links_to_the_inventory_component() -> None:
    record = classify("dockerfile/Dockerfile")
    record.component_id = "component:abc123"

    result = DockerfileAnalyzer().analyze(record, FIXTURES / "dockerfile/Dockerfile")

    stage = resource_named(result, "build", ResourceKind.BUILD_STAGE)

    assert stage.attributes["component_id"] == "component:abc123"


def test_dockerfile_without_from_is_partial() -> None:
    result = analyze(DockerfileAnalyzer(), "dockerfile/malformed.Dockerfile")

    assert result.status is ParseStatus.PARTIAL
    assert result.resources == []
    assert result.diagnostics == []


# --------------------------------------------------------------------------- #
# OpenAPI
# --------------------------------------------------------------------------- #


@pytest.fixture
def openapi_result():
    return analyze(OpenApiAnalyzer(), "api/openapi-cart.yaml")


def test_openapi_records_the_api_identity(openapi_result) -> None:
    api = resource_named(openapi_result, "Cart API", ResourceKind.API)

    assert api.attributes["version"] == "1.4.0"
    assert api.attributes["specification"] == "openapi 3.0.0"


def test_openapi_records_servers_as_configured_endpoints(openapi_result) -> None:
    servers = [item for item in openapi_result.endpoints if item.scope == "base_url"]

    assert len(servers) == 2

    resolved = [item for item in servers if item.host == "cart.example.com"]

    assert len(resolved) == 1
    assert resolved[0].port == 443
    assert resolved[0].protocol == "https"

    # A templated url has no resolvable host.
    templated = [item for item in servers if item.host is None]

    assert len(templated) == 1

    relationships = relationships_of(openapi_result, RelationshipType.SERVES_AT)

    assert all(
        item.origin is RelationshipOrigin.CONFIGURED_ENDPOINT for item in relationships
    )
    assert not any(item.resolved for item in relationships if item.target_id == templated[0].id)


def test_openapi_records_operations_with_their_methods(openapi_result) -> None:
    operations = [
        item
        for item in openapi_result.resources
        if item.kind is ResourceKind.API_OPERATION
    ]

    assert len(operations) == 3

    by_name = {item.name: item for item in operations}

    assert by_name["listCarts"].attributes["method"] == "GET"
    assert by_name["listCarts"].attributes["path"] == "/carts"
    assert by_name["listCarts"].attributes["tags"] == ["cart"]
    assert by_name["createCart"].attributes["deprecated"] is True
    assert by_name["deleteCart"].attributes["method"] == "DELETE"

    # A path-level `parameters` entry must not be mistaken for a method.
    assert not any(item.name == "parameters" for item in operations)


def test_openapi_operations_are_api_definitions(openapi_result) -> None:
    defines = relationships_of(openapi_result, RelationshipType.DEFINES_OPERATION)

    assert len(defines) == 3
    assert all(
        item.origin is RelationshipOrigin.API_DEFINITION for item in defines
    )

    api_id = resource_named(openapi_result, "Cart API", ResourceKind.API).id

    assert all(item.source_id == api_id for item in defines)


def test_openapi_reports_line_numbers(openapi_result) -> None:
    api = resource_named(openapi_result, "Cart API", ResourceKind.API)

    assert api.location.line == 1


def test_openapi_json_specification_is_supported() -> None:
    result = analyze(OpenApiAnalyzer(), "api/openapi-cart.json")

    assert result.status is ParseStatus.PARSED
    assert result.method is ExtractionMethod.JSON

    api = resource_named(result, "Cart API", ResourceKind.API)

    # JSON has no position information available, so the line is unknown.
    assert api.location.line is None
    assert len(
        [item for item in result.resources if item.kind is ResourceKind.API_OPERATION]
    ) == 1


def test_openapi_malformed_json_fails_without_raising() -> None:
    result = analyze(OpenApiAnalyzer(), "api/openapi-malformed.json")

    assert result.status is ParseStatus.FAILED
    assert result.diagnostics[0].line is not None


def test_openapi_file_that_is_not_a_specification_is_partial() -> None:
    result = analyze(OpenApiAnalyzer(), "api/openapi-not-a-spec.yaml")

    assert result.status is ParseStatus.PARTIAL
    assert any("not treated as a specification" in item.message for item in result.diagnostics)


# --------------------------------------------------------------------------- #
# Protobuf
# --------------------------------------------------------------------------- #


@pytest.fixture
def protobuf_result():
    return analyze(ProtobufAnalyzer(), "proto/cart.proto")


def test_protobuf_records_package_and_syntax(protobuf_result) -> None:
    package = resource_named(protobuf_result, "cart.v1", ResourceKind.PROTO_PACKAGE)

    assert package.attributes["syntax"] == "proto3"


def test_protobuf_records_services_and_their_rpcs(protobuf_result) -> None:
    services = {
        item.name
        for item in protobuf_result.resources
        if item.kind is ResourceKind.PROTO_SERVICE
    }

    assert services == {"CartService", "AdminService"}

    defines = relationships_of(protobuf_result, RelationshipType.DEFINES_RPC)

    assert len(defines) == 4
    assert all(item.origin is RelationshipOrigin.API_DEFINITION for item in defines)


def test_protobuf_attributes_rpcs_to_the_enclosing_service(protobuf_result) -> None:
    """Scope tracking must not leak rpcs into the next service block."""

    purge = next(
        item
        for item in protobuf_result.resources
        if item.kind is ResourceKind.PROTO_RPC and item.name == "Purge"
    )

    assert purge.attributes["service"] == "AdminService"


def test_protobuf_links_rpc_request_and_response_types(protobuf_result) -> None:
    accepts = relationships_of(protobuf_result, RelationshipType.ACCEPTS_MESSAGE)
    returns = relationships_of(protobuf_result, RelationshipType.RETURNS_MESSAGE)

    assert len(accepts) == 4
    assert len(returns) == 4

    resolved = [item for item in accepts + returns if item.resolved]

    assert len(resolved) == 7

    # `google.protobuf.Empty` is imported, not declared here.
    unresolved = [item for item in accepts + returns if not item.resolved]

    assert len(unresolved) == 1
    assert unresolved[0].target_id == "unresolved:google.protobuf.Empty"


def test_protobuf_records_messages_and_enums(protobuf_result) -> None:
    messages = {
        item.name
        for item in protobuf_result.resources
        if item.kind is ResourceKind.PROTO_MESSAGE
    }

    assert {"Cart", "CartSummary", "CartStatus"} <= messages


def test_protobuf_records_an_import_as_an_unresolved_reference(
    protobuf_result,
) -> None:
    imported = reference_named(protobuf_result, "google/protobuf/empty.proto")

    assert imported.status is ReferenceStatus.UNRESOLVED
    assert imported.reference_type == "protobuf_import"


def test_protobuf_strips_comments_and_keeps_line_numbers(protobuf_result) -> None:
    service = resource_named(protobuf_result, "CartService", ResourceKind.PROTO_SERVICE)

    # The service declaration is the 24th line of the fixture.
    assert service.location.line == 24


def test_protobuf_without_declarations_is_partial() -> None:
    result = analyze(ProtobufAnalyzer(), "proto/malformed.proto")

    assert result.status is ParseStatus.PARTIAL
    assert result.diagnostics


# --------------------------------------------------------------------------- #
# Redaction helpers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "key",
    [
        "DB_PASSWORD",
        "API_KEY",
        "api-key",
        "SECRET",
        "GITHUB_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "PRIVATE_KEY",
        "CLIENT_SECRET",
        "JWT_TOKEN",
        "Authorization",
    ],
)
def test_sensitive_keys_are_recognised(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize(
    "key",
    ["LOG_LEVEL", "PORT", "DATABASE_URL", "AUTHOR", "REGION", "AUTHORS_FILE"],
)
def test_non_sensitive_keys_are_not_over_redacted(key: str) -> None:
    assert not is_sensitive_key(key)


def test_sanitize_scalar_redacts_by_key() -> None:
    result = sanitize_scalar("hunter2", "DB_PASSWORD")

    assert result.value is None
    assert result.redacted is True


def test_sanitize_scalar_strips_url_credentials() -> None:
    result = sanitize_scalar("postgres://user:pw@db:5432/app")

    assert result.redacted is True
    assert result.value == "postgres://db:5432"
    assert "pw" not in (result.value or "")


def test_sanitize_url_keeps_only_the_origin() -> None:
    assert sanitize_url("https://user:tok@api.example.com/v1/x?token=abc") == (
        "https://api.example.com"
    )


@pytest.mark.parametrize(
    ("value", "host", "port", "scheme"),
    [
        ("http://api:8080/v1", "api", 8080, "http"),
        ("https://api.example.com", "api.example.com", 443, "https"),
        ("grpc://cart:50051", "cart", 50051, "grpc"),
        ("redis://cache:6379/0", "cache", 6379, "redis"),
        ("db:5432", "db", 5432, None),
    ],
)
def test_endpoint_candidates_are_extracted(value, host, port, scheme) -> None:
    candidate = extract_endpoint_candidate(value)

    assert candidate is not None
    assert (candidate.host, candidate.port, candidate.scheme) == (host, port, scheme)


@pytest.mark.parametrize(
    "value",
    [
        "info",
        "gcr.io/example/cart:1.2.3",
        "plain text",
        # A url carrying credentials is deliberately not treated as an endpoint.
        "mysql://user:pw@db:3306/app",
        "/usr/local/bin/cart",
        "",
    ],
)
def test_non_endpoint_values_are_not_mistaken_for_endpoints(value: str) -> None:
    assert extract_endpoint_candidate(value) is None


@pytest.mark.parametrize(
    ("entry", "host_port", "container_port", "protocol"),
    [
        ("8080:80", "8080", "80", "tcp"),
        ("127.0.0.1:9000:9000/udp", "9000", "9000", "udp"),
        ("3000", None, "3000", "tcp"),
        ("8000-8010:80", "8000-8010", "80", "tcp"),
    ],
)
def test_compose_port_forms_parse(entry, host_port, container_port, protocol) -> None:
    parts = parse_compose_port(entry)

    assert parts is not None
    assert parts["host_port"] == host_port
    assert parts["container_port"] == container_port
    assert parts["protocol"] == protocol


def test_compose_port_long_form_parses() -> None:
    parts = parse_compose_port({"published": 8080, "target": 80, "protocol": "udp"})

    assert parts == {
        "host_ip": None,
        "host_port": 8080,
        "container_port": 80,
        "protocol": "udp",
        "raw": None,
    }


# --------------------------------------------------------------------------- #
# YAML safety
# --------------------------------------------------------------------------- #


def test_yaml_loader_refuses_arbitrary_python_objects() -> None:
    """A malicious manifest must not be able to execute code."""

    loaded = load_yaml_documents(
        "value: !!python/object/apply:os.system ['echo pwned']\n"
    )

    assert loaded.error is not None
    assert loaded.documents == []


def test_yaml_loader_reports_multi_document_lines() -> None:
    loaded = load_yaml_documents("kind: A\n---\nkind: B\n")

    assert [document.line for document in loaded.documents] == [1, 3]


# --------------------------------------------------------------------------- #
# Analysis service
# --------------------------------------------------------------------------- #


def build_inventory(root: Path) -> RepositoryInventory:
    """Run the inventory stage over a fixture tree."""

    return RepositoryInventoryService().build(
        root, RepositoryRef(id="fixture", branch="main", commit="a" * 40)
    )


def test_service_analyzes_only_manifest_files(tmp_path: Path) -> None:
    """Source code must never be opened by this stage."""

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.go").write_text("package main\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# docs\n", encoding="utf-8")
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n', encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")

    report = ManifestAnalysisService().analyze(build_inventory(tmp_path), tmp_path)

    analyzed = {item.path for item in report.results}

    assert analyzed == {"Dockerfile"}


def test_service_reports_a_manifest_no_analyzer_supports() -> None:
    root = FIXTURES / "unsupported"
    report = ManifestAnalysisService().analyze(build_inventory(root), root)

    result = next(item for item in report.results if item.path.endswith("notes.txt"))

    assert result.status is ParseStatus.SKIPPED
    assert result.analyzer is None
    assert "no analyzer supports" in result.diagnostics[0].message
    assert report.summary.skipped_count == 1


def test_service_produces_a_consistent_summary() -> None:
    report = ManifestAnalysisService().analyze(
        build_inventory(FIXTURES), FIXTURES
    )
    summary = report.summary

    assert summary.file_count == len(report.results)
    assert summary.resource_count == len(report.resources)
    assert summary.relationship_count == len(report.relationships)
    assert summary.endpoint_count == len(report.endpoints)
    assert set(summary.by_analyzer) == {
        "compose",
        "dockerfile",
        "kubernetes",
        "openapi",
        "protobuf",
    }
    assert summary.failed_count == 3
    assert summary.analyzed_count + summary.skipped_count + summary.failed_count == (
        summary.file_count
    )


def test_service_output_is_deterministic() -> None:
    service = ManifestAnalysisService()
    inventory = build_inventory(FIXTURES)

    first = service.analyze(inventory, FIXTURES).to_dict()
    second = service.analyze(inventory, FIXTURES).to_dict()

    first.pop("generated_at")
    second.pop("generated_at")

    assert first == second


def test_service_never_asserts_verified_communication() -> None:
    """Declarations must not be promoted beyond what the manifest proves."""

    report = ManifestAnalysisService().analyze(
        build_inventory(FIXTURES), FIXTURES
    )

    origins = {item.origin for item in report.relationships}

    assert RelationshipOrigin.VERIFIED_COMMUNICATION not in origins
    assert RelationshipOrigin.DECLARED_DEPENDENCY in origins
    assert RelationshipOrigin.CONFIGURED_ENDPOINT in origins
    assert RelationshipOrigin.API_DEFINITION in origins


def test_service_keeps_no_secret_material_in_the_report() -> None:
    report = ManifestAnalysisService().analyze(
        build_inventory(FIXTURES), FIXTURES
    )

    blob = json.dumps(report.to_dict())

    for secret in (
        "hunter2",
        "c3VwZXJzZWNyZXQ=",
        "YWJjMTIz",
        "plaintext-secret",
        "configmap-secret-value",
    ):
        assert secret not in blob


def test_service_reports_evidence_for_every_finding() -> None:
    report = ManifestAnalysisService().analyze(
        build_inventory(FIXTURES), FIXTURES
    )

    assert report.resources and report.relationships

    for resource in report.resources:
        assert resource.evidence, resource.name

        for evidence in resource.evidence:
            assert evidence.method is not None
            assert evidence.location.path

    for relationship in report.relationships:
        assert relationship.evidence, relationship.type.value


def test_writer_produces_a_single_versioned_file(tmp_path: Path) -> None:
    report = ManifestAnalysisService().analyze(
        build_inventory(FIXTURES), FIXTURES
    )

    written = write_manifest_analysis(report, tmp_path)

    assert written.name == MANIFEST_ANALYSIS_FILE_NAME
    assert [item.name for item in tmp_path.iterdir()] == [MANIFEST_ANALYSIS_FILE_NAME]

    payload = json.loads(written.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "1.0.0"
    assert payload["generator"]["name"] == "manifest_analysis"
    assert payload["repository"]["id"] == "fixture"


def test_writer_replaces_an_existing_report_atomically(tmp_path: Path) -> None:
    service = ManifestAnalysisService()
    inventory = build_inventory(FIXTURES)

    first = write_manifest_analysis(service.analyze(inventory, FIXTURES), tmp_path)
    second = write_manifest_analysis(service.analyze(inventory, FIXTURES), tmp_path)

    assert first == second
    assert [item.name for item in tmp_path.iterdir()] == [MANIFEST_ANALYSIS_FILE_NAME]


def test_run_for_ingested_reads_the_existing_inventory(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from app.domain.repository import IngestedRepository

    source = tmp_path / "repo" / "source"
    source.mkdir(parents=True)
    (source / "docker-compose.yaml").write_text(
        "services:\n  web:\n    image: nginx:1.27\n", encoding="utf-8"
    )

    ingested = IngestedRepository(
        id="repo-1",
        url="https://example.com/team/repo.git",
        branch="main",
        commit="a" * 40,
        path=source,
        ingested_at=datetime.now(timezone.utc),
    )

    # The inventory stage runs first, as it would in the pipeline.
    RepositoryInventoryService().run_for_ingested(ingested)

    written, report = ManifestAnalysisService().run_for_ingested(ingested)

    assert written.parent == source.parent
    assert written.name == MANIFEST_ANALYSIS_FILE_NAME
    assert not (source / MANIFEST_ANALYSIS_FILE_NAME).exists()

    assert report.repository.id == "repo-1"
    assert [item.path for item in report.results] == ["docker-compose.yaml"]
    assert report.summary.resource_count > 0


def test_run_for_ingested_requires_an_inventory(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from app.domain.repository import IngestedRepository

    source = tmp_path / "repo" / "source"
    source.mkdir(parents=True)

    ingested = IngestedRepository(
        id="repo-1",
        url="https://example.com/team/repo.git",
        branch="main",
        commit="a" * 40,
        path=source,
        ingested_at=datetime.now(timezone.utc),
    )

    with pytest.raises(AnalysisInputError):
        ManifestAnalysisService().run_for_ingested(ingested)


def test_load_inventory_rejects_a_malformed_inventory(tmp_path: Path) -> None:
    path = tmp_path / "repository_inventory.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(AnalysisInputError):
        load_inventory(path)


def test_load_inventory_rejects_an_unexpected_structure(tmp_path: Path) -> None:
    path = tmp_path / "repository_inventory.json"
    path.write_text(json.dumps({"files": [{"path": "x.yaml"}]}), encoding="utf-8")

    with pytest.raises(AnalysisInputError):
        load_inventory(path)


def test_analysis_respects_the_file_size_limit() -> None:
    service = ManifestAnalysisService(max_bytes=16)
    inventory = build_inventory(FIXTURES)

    report = service.analyze(inventory, FIXTURES)

    oversized = [
        item
        for item in report.results
        if item.status is ParseStatus.SKIPPED
        and any("analysis limit" in d.message for d in item.diagnostics)
    ]

    assert oversized
