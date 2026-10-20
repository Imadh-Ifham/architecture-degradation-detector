"""Tests for the dependency resolution subcomponent.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Covers accurate resolution *and* the false dependencies the resolver must
    avoid. Each fixture repository is run through the real inventory, manifest
    analysis and component discovery stages first, so these exercise the same
    evidence the application produces.

    No network access or live clone is required.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.components.architecture_recovery.component_discovery import (
    ComponentDiscoveryService,
    write_component_discovery,
)
from app.components.architecture_recovery.dependency_resolution import (
    DEPENDENCY_RESOLUTION_FILE_NAME,
    ArtifactInput,
    ComponentIndex,
    ComponentInput,
    DependencyResolutionInputError,
    DependencyResolutionService,
    EvidenceSource,
    InfrastructureKind,
    RelationshipType,
    ResolutionConfidence,
    ResolutionStatus,
    TargetClass,
)
from app.components.architecture_recovery.manifest_analysis import (
    Endpoint,
    ExtractionMethod,
    ManifestAnalysisReport,
    ManifestAnalysisService,
    ManifestAnalysisSummary,
    ResourceKind,
    SourceLocation,
    write_manifest_analysis,
)
from app.components.architecture_recovery.repository_inventory import (
    RepositoryInventoryService,
    RepositoryRef,
)
from app.domain.repository import IngestedRepository

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "dependency_resolution"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def build_pipeline(fixture: str):
    """Run the real pipeline over a fixture and return every stage's result."""

    root = FIXTURES / fixture
    inventory = RepositoryInventoryService().build(
        root, RepositoryRef(id=fixture, branch="main", commit="a" * 40)
    )
    analysis = ManifestAnalysisService().analyze(inventory, root)
    discovery = ComponentDiscoveryService().discover(inventory, analysis)
    report = DependencyResolutionService().resolve(discovery, analysis)

    return inventory, analysis, discovery, report


def build_report(fixture: str):
    """Return only the dependency resolution report for a fixture."""

    return build_pipeline(fixture)[3]


def relationship(report, relationship_type, source: str, target: str):
    """Return one relationship, failing with the actual edges when absent."""

    for item in report.relationships:
        if (
            item.type is relationship_type
            and item.source_component_name == source
            and item.target_component_name == target
        ):
            return item

    present = [
        (item.type.value, item.source_component_name, item.target_component_name)
        for item in report.relationships
    ]
    raise AssertionError(
        f"relationship {relationship_type.value} {source} -> {target} not found; "
        f"present: {present}"
    )


# --------------------------------------------------------------------------- #
# 1-3. Configured endpoints and infrastructure targets
# --------------------------------------------------------------------------- #


def test_configured_endpoint_resolves_to_a_known_component() -> None:
    report = build_report("compose_app")

    resolved = relationship(
        report, RelationshipType.CONFIGURED_ENDPOINT, "frontend", "checkout"
    )

    assert resolved.status is ResolutionStatus.RESOLVED
    assert resolved.confidence is ResolutionConfidence.DECLARED
    assert resolved.target_component_id
    assert resolved.target_component_id != resolved.source_component_id


def test_hostname_and_port_are_preserved_in_evidence() -> None:
    report = build_report("compose_app")

    resolved = relationship(
        report, RelationshipType.CONFIGURED_ENDPOINT, "frontend", "checkout"
    )

    endpoints = {item.endpoint for item in resolved.evidence if item.endpoint}

    assert "checkout:5050" in endpoints
    assert "http://checkout:5050" in endpoints


def test_a_declared_protocol_is_carried_on_the_relationship() -> None:
    """The endpoint's scheme travels with the edge, not only inside its detail.

    A consumer asking "how do these two talk" should not have to parse an
    evidence string to find out, and a transport written down in a manifest is
    a fact about the relationship rather than about one line of one file.
    """

    report = build_report("compose_app")

    resolved = relationship(
        report, RelationshipType.CONFIGURED_ENDPOINT, "frontend", "checkout"
    )

    assert "http" in resolved.protocols
    assert "http://checkout:5050" in resolved.endpoints
    assert 5050 in resolved.ports


def test_a_relationship_with_no_configured_endpoint_claims_no_protocol() -> None:
    """A declared dependency is not a call, so nothing is known about transport."""

    report = build_report("compose_app")

    declared = [
        item
        for item in report.relationships
        if item.type is RelationshipType.DECLARED_DEPENDENCY
    ]

    assert declared
    assert all(item.protocols == [] for item in declared)


def test_port_disambiguates_two_candidate_components() -> None:
    """A hostname shared by two components is resolved only when the port matches."""

    analysis = ManifestAnalysisReport(
        generated_at=datetime.now(UTC),
        repository=RepositoryRef(id="ports"),
        options={},
        summary=ManifestAnalysisSummary(),
        resources=[
            _service_resource("resource:a", "paymentservice", "a.yaml"),
            _service_resource("resource:b", "paymentservice", "b.yaml"),
        ],
        endpoints=[
            Endpoint(
                id="endpoint:a",
                location=SourceLocation("a.yaml"),
                port=50051,
                protocol="tcp",
                source_resource_id="resource:a",
                scope="service",
            ),
            Endpoint(
                id="endpoint:b",
                location=SourceLocation("b.yaml"),
                port=8080,
                protocol="tcp",
                source_resource_id="resource:b",
                scope="service",
            ),
        ],
    )

    index = ComponentIndex.build(
        components=[
            ComponentInput(
                id="component:a",
                name="paymentservice",
                type="service",
                artifact_ids=("artifact:a",),
            ),
            ComponentInput(
                id="component:b",
                name="paymentservice",
                type="service",
                artifact_ids=("artifact:b",),
            ),
        ],
        artifacts=[
            ArtifactInput(
                id="artifact:a",
                role="deployment",
                kind="kubernetes_service",
                name="paymentservice",
                path="a.yaml",
                resource_id="resource:a",
            ),
            ArtifactInput(
                id="artifact:b",
                role="deployment",
                kind="kubernetes_service",
                name="paymentservice",
                path="b.yaml",
                resource_id="resource:b",
            ),
        ],
        analysis=analysis,
    )

    matches, method = index.lookup("paymentservice", 50051)

    assert method == "host_port_disambiguation"
    assert [match.component_id for match in matches] == ["component:a"]


def test_infrastructure_endpoint_resolves_to_a_cache_target() -> None:
    report = build_report("compose_app")

    resolved = relationship(
        report, RelationshipType.INFRASTRUCTURE_DEPENDENCY, "checkout", "redis-cart"
    )

    assert resolved.target_class is TargetClass.INFRASTRUCTURE
    assert resolved.target_infrastructure_kind is InfrastructureKind.CACHE
    assert any(item.type == "container_image" for item in resolved.evidence)


# --------------------------------------------------------------------------- #
# 4-5. Unresolved and ambiguous targets
# --------------------------------------------------------------------------- #


def test_unresolved_hostname_is_preserved() -> None:
    report = build_report("compose_app")

    candidate = next(
        item
        for item in report.unresolved
        if item.target_reference == "unknown-service:9999"
    )

    assert candidate.status is ResolutionStatus.UNRESOLVED
    assert candidate.host == "unknown-service"
    assert candidate.port == 9999
    assert candidate.evidence
    assert candidate.evidence[0].endpoint == "unknown-service:9999"


def test_endpoint_matching_multiple_candidates_is_ambiguous() -> None:
    report = build_report("ambiguous_target")

    assert report.relationships == []
    assert len(report.ambiguous) == 1

    candidate = report.ambiguous[0]

    assert candidate.status is ResolutionStatus.AMBIGUOUS
    assert candidate.target_reference == "paymentservice:50051"
    assert len(set(candidate.candidate_component_ids)) == 2
    assert set(candidate.candidate_component_names) == {"paymentservice"}


# --------------------------------------------------------------------------- #
# 6-8. Negative tests: declarations and contracts are not communication
# --------------------------------------------------------------------------- #


def test_compose_startup_dependency_is_not_application_communication() -> None:
    report = build_report("compose_app")

    declared = relationship(
        report, RelationshipType.DECLARED_DEPENDENCY, "frontend", "checkout"
    )

    assert declared.type is RelationshipType.DECLARED_DEPENDENCY
    assert any("depends_on" in item.detail for item in declared.evidence)
    assert "verified_communication" not in {
        item.type.value for item in report.relationships
    }


def test_kubernetes_service_selection_is_not_an_application_dependency() -> None:
    report = build_report("k8s_app")

    assert all(
        item.type is not RelationshipType.RESOURCE_SELECTION
        for item in report.relationships
    )
    assert all(
        item.source_component_id != item.target_component_id
        for item in report.relationships
    )

    # The configured address still resolves, and the Service selector did not
    # add a second, false edge between the same pair.
    configured = relationship(
        report, RelationshipType.CONFIGURED_ENDPOINT, "frontend", "checkout"
    )
    assert configured.target_infrastructure_kind is None

    infrastructure = relationship(
        report, RelationshipType.INFRASTRUCTURE_DEPENDENCY, "checkout", "redis-cart"
    )
    assert infrastructure.target_infrastructure_kind is InfrastructureKind.CACHE


def test_dockerfile_build_time_endpoint_is_not_a_runtime_dependency() -> None:
    report = build_report("compose_app")

    references = {
        item.target_reference for item in [*report.unresolved, *report.ambiguous]
    }

    assert not any(
        reference and "registry.internal" in reference for reference in references
    )
    assert "registry.internal" not in json.dumps(
        [item.to_dict() for item in [*report.unresolved, *report.ambiguous]]
    )


def test_shared_protobuf_messages_do_not_create_cross_component_edges() -> None:
    report = build_report("shared_contracts")

    assert report.relationships == []
    assert report.unresolved == []
    assert report.ambiguous == []


# --------------------------------------------------------------------------- #
# 9-10. Aggregation and type preservation
# --------------------------------------------------------------------------- #


def test_multiple_evidence_sources_are_aggregated() -> None:
    report = build_report("compose_app")

    resolved = relationship(
        report, RelationshipType.CONFIGURED_ENDPOINT, "frontend", "checkout"
    )

    manifest_evidence = [
        item for item in resolved.evidence if item.source is EvidenceSource.MANIFEST_ANALYSIS
    ]
    keys = {item.key for item in manifest_evidence if item.key}

    assert {"CHECKOUT_SERVICE_ADDR", "CHECKOUT_STATUS_URL"} <= keys
    assert any(
        item.source is EvidenceSource.COMPONENT_DISCOVERY
        for item in resolved.evidence
    )
    assert report.summary.duplicate_evidence_count >= 1


def test_different_relationship_types_are_preserved_between_the_same_pair() -> None:
    report = build_report("compose_app")

    types = {
        item.type
        for item in report.relationships
        if item.source_component_name == "frontend"
        and item.target_component_name == "checkout"
    }

    assert types == {
        RelationshipType.CONFIGURED_ENDPOINT,
        RelationshipType.DECLARED_DEPENDENCY,
    }


# --------------------------------------------------------------------------- #
# 11. Missing or malformed upstream artifacts
# --------------------------------------------------------------------------- #


def test_missing_upstream_artifacts_raise_an_input_error(tmp_path: Path) -> None:
    repository = _ingested(tmp_path)

    with pytest.raises(DependencyResolutionInputError, match="No readable component"):
        DependencyResolutionService().run_for_ingested(repository)


def test_malformed_component_discovery_raises_an_input_error(tmp_path: Path) -> None:
    repository = _ingested(tmp_path)
    (tmp_path / "component_discovery.json").write_text("{", encoding="utf-8")

    with pytest.raises(DependencyResolutionInputError, match="No readable component"):
        DependencyResolutionService().run_for_ingested(repository)


def test_missing_manifest_analysis_raises_an_input_error(tmp_path: Path) -> None:
    _, _, discovery, _ = build_pipeline("compose_app")
    write_component_discovery(discovery, tmp_path)

    with pytest.raises(DependencyResolutionInputError, match="No manifest analysis"):
        DependencyResolutionService().run_for_ingested(_ingested(tmp_path))


def test_component_document_without_components_raises_an_input_error(
    tmp_path: Path,
) -> None:
    repository = _ingested(tmp_path)
    (tmp_path / "component_discovery.json").write_text("{}", encoding="utf-8")

    analysis = ManifestAnalysisService().analyze(
        RepositoryInventoryService().build(
            FIXTURES / "compose_app", RepositoryRef(id="compose_app")
        ),
        FIXTURES / "compose_app",
    )
    write_manifest_analysis(analysis, tmp_path)

    with pytest.raises(DependencyResolutionInputError, match="must contain"):
        DependencyResolutionService().run_for_ingested(repository)


# --------------------------------------------------------------------------- #
# 12-14. Safety, determinism and artifact output
# --------------------------------------------------------------------------- #


def test_sensitive_values_are_not_leaked() -> None:
    payload = build_report("compose_app").to_dict()
    blob = json.dumps(payload)

    assert "hunter2" not in blob
    assert "supersecret" not in blob

    for relationship_item in payload["relationships"]:
        for evidence in relationship_item["evidence"]:
            assert "hunter2" not in json.dumps(evidence)
            assert "supersecret" not in json.dumps(evidence)

    for candidate in [*payload["unresolved"], *payload["ambiguous"]]:
        assert "supersecret" not in json.dumps(candidate)

    # The endpoint survives with its credentials stripped.
    assert "postgres://db:5432" in {
        item["target_reference"] for item in payload["unresolved"]
    }


def test_repeated_runs_produce_deterministic_output() -> None:
    first = build_report("compose_app").to_dict()
    second = build_report("compose_app").to_dict()

    first.pop("generated_at")
    second.pop("generated_at")

    assert first == second


def test_run_for_ingested_reuses_the_written_upstream_artifacts(
    tmp_path: Path,
) -> None:
    _, analysis, discovery, _ = build_pipeline("compose_app")
    write_component_discovery(discovery, tmp_path)
    write_manifest_analysis(analysis, tmp_path)

    path, report = DependencyResolutionService().run_for_ingested(_ingested(tmp_path))

    assert path.name == DEPENDENCY_RESOLUTION_FILE_NAME
    assert report.summary.resolved_relationship_count == 6
    assert report.summary.unresolved_count == 3


def test_report_is_written_beside_the_upstream_artifacts(tmp_path: Path) -> None:
    _, analysis, discovery, _ = build_pipeline("compose_app")

    path, report = DependencyResolutionService().run(discovery, analysis, tmp_path)

    assert path.name == DEPENDENCY_RESOLUTION_FILE_NAME
    assert path.parent == tmp_path
    assert path.is_file()

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"]
    assert payload["summary"]["resolved_relationship_count"] == len(
        payload["relationships"]
    )
    assert payload["summary"]["resolved_relationship_count"] == len(
        report.relationships
    )


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #


def _service_resource(identifier: str, name: str, path: str):
    from app.components.architecture_recovery.manifest_analysis import DeclaredResource

    return DeclaredResource(
        id=identifier,
        kind=ResourceKind.KUBERNETES_SERVICE,
        name=name,
        location=SourceLocation(path),
        analyzer="kubernetes",
        method=ExtractionMethod.YAML,
    )


def _ingested(workspace: Path) -> IngestedRepository:
    source = workspace / "source"
    source.mkdir(parents=True, exist_ok=True)

    return IngestedRepository(
        id="fixture",
        url="https://example.com/team/repo.git",
        branch="main",
        commit="a" * 40,
        path=source,
        ingested_at=datetime.now(UTC),
    )
