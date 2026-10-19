"""Tests for the source code analysis subcomponent.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Covers source-level call evidence and the false dependencies the stage must
    avoid. Each fixture repository is run through the real inventory, manifest
    analysis, component discovery and dependency resolution stages first, so the
    tests exercise the same evidence the application produces.

    No network access or live clone is required.
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.components.architecture_recovery.component_discovery import (
    ComponentDiscoveryService,
    write_component_discovery,
)
from app.components.architecture_recovery.dependency_resolution import (
    DependencyResolutionService,
    write_dependency_resolution,
)
from app.components.architecture_recovery.manifest_analysis import (
    ManifestAnalysisService,
)
from app.components.architecture_recovery.repository_inventory import (
    RepositoryInventoryService,
    RepositoryRef,
    write_inventory,
)
from app.components.architecture_recovery.source_code_analysis import (
    SOURCE_CODE_ANALYSIS_FILE_NAME,
    EvidenceStrength,
    EvidenceType,
    FindingType,
    SourceCodeAnalysisInputError,
    SourceCodeAnalysisService,
)
from app.domain.repository import IngestedRepository

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "source_code_analysis"


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
    dependencies = DependencyResolutionService().resolve(discovery, analysis)
    report = SourceCodeAnalysisService().analyze(
        inventory, discovery, dependencies, root
    )

    return inventory, analysis, discovery, dependencies, report


def build_report(fixture: str):
    """Return only the source code analysis report for a fixture."""

    return build_pipeline(fixture)[4]


def finding(report, finding_type, source: str, target: str):
    """Return one finding, failing with the actual findings when absent."""

    for item in report.findings:
        if (
            item.finding_type is finding_type
            and item.source_component_name == source
            and item.target_component_name == target
        ):
            return item

    present = [
        (item.finding_type.value, item.source_component_name, item.target_component_name)
        for item in report.findings
    ]
    raise AssertionError(
        f"finding {finding_type.value} {source} -> {target} not found; present: {present}"
    )


# --------------------------------------------------------------------------- #
# 1-4. Go gRPC evidence
# --------------------------------------------------------------------------- #


def test_go_grpc_invocation_resolves_to_a_component() -> None:
    report = build_report("go_grpc")

    products = finding(
        report,
        FindingType.GRPC_SERVICE_CALL,
        "frontend",
        "productcatalogservice",
    )

    assert products.status.value == "resolved"
    assert products.evidence_strength is EvidenceStrength.OBSERVED_INVOCATION
    assert products.resolution_method == "component_alias"

    cart = finding(
        report, FindingType.GRPC_SERVICE_CALL, "frontend", "cartservice"
    )

    assert any(
        item.method == "GetCart" and item.evidence_type is EvidenceType.GRPC_CLIENT_INVOCATION
        for item in cart.evidence
    )


def test_generated_and_standalone_client_files_are_skipped() -> None:
    report = build_report("go_grpc")
    messages = " ".join(diagnostic.message for diagnostic in report.diagnostics)

    assert report.summary.skipped_file_count >= 2
    assert "generated_file" in messages
    assert "standalone_client_file" in messages

    # The standalone Python client constructs a RecommendationService stub for
    # localhost; it must not become a frontend -> recommendationservice edge.
    assert all(item.target_component_name != "recommendationservice" for item in report.findings)


def test_imports_do_not_create_findings() -> None:
    report = build_report("go_grpc")

    assert all(
        not evidence.path.endswith("imports.go")
        for item in report.findings
        for evidence in item.evidence
    )


def test_unresolved_service_name_is_preserved() -> None:
    report = build_report("go_grpc")

    candidate = next(
        item for item in report.unresolved if item.target_reference == "MissingService"
    )

    assert candidate.status.value == "unresolved"
    assert candidate.reason
    assert candidate.evidence


# --------------------------------------------------------------------------- #
# 5-6. HTTP evidence
# --------------------------------------------------------------------------- #


def test_http_call_resolves_through_a_configured_environment_key() -> None:
    report = build_report("http_app")

    result = finding(
        report,
        FindingType.HTTP_SERVICE_CALL,
        "frontend",
        "shoppingassistantservice",
    )

    assert result.resolution_method == "configured_env_key"
    assert result.evidence_strength is EvidenceStrength.OBSERVED_INVOCATION
    assert result.corroborates_dependency_relationship_id
    assert any(item.method == "POST" for item in result.evidence)


def test_http_call_resolves_through_the_only_configured_endpoint() -> None:
    report = build_report("http_app")

    result = finding(
        report, FindingType.HTTP_SERVICE_CALL, "loadgenerator", "frontend"
    )

    assert result.resolution_method == "single_configured_endpoint"
    assert result.corroborates_dependency_relationship_id
    assert len(result.evidence) >= 2


def test_literal_unknown_host_is_not_resolved_to_the_only_endpoint() -> None:
    report = build_report("http_app")

    candidate = next(
        item
        for item in report.unresolved
        if item.target_reference == "unknown.example"
    )

    assert candidate.source_component_name == "frontend"
    assert candidate.reason
    assert all(
        not (
            item.source_component_name == "frontend"
            and item.target_component_name == "shoppingassistantservice"
            and any("unknown.example" in (evidence.detail or "") for evidence in item.evidence)
        )
        for item in report.findings
    )


# --------------------------------------------------------------------------- #
# 7-8. Cache evidence and negative HTTP matching
# --------------------------------------------------------------------------- #


def test_cache_client_usage_resolves_to_an_infrastructure_target() -> None:
    report = build_report("csharp_cache")

    result = finding(
        report, FindingType.CACHE_CLIENT_USAGE, "cartservice", "redis-cart"
    )

    assert result.evidence_strength is EvidenceStrength.OBSERVED_INVOCATION
    assert result.resolution_method == "infrastructure_target"
    assert result.corroborates_dependency_relationship_id
    assert any(
        item.evidence_type is EvidenceType.CACHE_CLIENT_CONSTRUCTION
        for item in result.evidence
    )
    assert any(
        item.evidence_type is EvidenceType.CACHE_CLIENT_INVOCATION
        for item in result.evidence
    )


def test_cache_operations_are_not_mistaken_for_http_calls() -> None:
    report = build_report("csharp_cache")

    assert report.summary.by_finding_type == {
        FindingType.CACHE_CLIENT_USAGE.value: 1
    }
    assert all(
        item.finding_type is FindingType.CACHE_CLIENT_USAGE
        for item in report.findings
    )


# --------------------------------------------------------------------------- #
# 9-11. Ambiguity, aggregation and corroboration
# --------------------------------------------------------------------------- #


def test_ambiguous_service_name_is_preserved() -> None:
    report = build_report("ambiguous_target")

    assert report.ambiguous
    candidate = next(
        item for item in report.ambiguous if item.target_reference == "PaymentService"
    )

    assert candidate.status.value == "ambiguous"
    assert len(set(candidate.candidate_component_ids)) == 2
    assert all(
        not (
            item.finding_type is FindingType.GRPC_SERVICE_CALL
            and item.target_component_name in {"paymentservice-one", "paymentservice-two"}
        )
        for item in report.findings
    )


def test_multiple_call_sites_are_aggregated() -> None:
    report = build_report("http_app")

    result = finding(
        report, FindingType.HTTP_SERVICE_CALL, "loadgenerator", "frontend"
    )
    methods = {item.method for item in result.evidence}

    assert {"GET", "POST"} <= methods
    assert (
        sum(
            1
            for item in report.findings
            if item.source_component_name == "loadgenerator"
            and item.target_component_name == "frontend"
        )
        == 1
    )


def test_findings_corroborate_dependency_resolution_relationships() -> None:
    _, _, _, dependencies, report = build_pipeline("http_app")

    relationship_ids = {
        relationship.id for relationship in dependencies.relationships
    }

    assert report.summary.corroborated_count == 2
    assert all(
        item.corroborates_dependency_relationship_id in relationship_ids
        for item in report.findings
    )


# --------------------------------------------------------------------------- #
# 12-14. Safety, determinism and persistence
# --------------------------------------------------------------------------- #


def test_sensitive_source_text_is_not_leaked() -> None:
    report = build_report("go_grpc")
    blob = json.dumps(report.to_dict())

    assert "supersecret-source-value" not in blob


def test_repeated_runs_produce_deterministic_output() -> None:
    first = build_report("go_grpc").to_dict()
    second = build_report("go_grpc").to_dict()

    first.pop("generated_at")
    second.pop("generated_at")

    assert first == second


def test_report_is_written_beside_the_upstream_artifacts(tmp_path: Path) -> None:
    inventory, _, discovery, dependencies, _ = build_pipeline("go_grpc")

    path, report = SourceCodeAnalysisService().run(
        inventory, discovery, dependencies, FIXTURES / "go_grpc", tmp_path
    )

    assert path.name == SOURCE_CODE_ANALYSIS_FILE_NAME
    assert path.parent == tmp_path
    assert path.is_file()

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"]
    assert payload["summary"]["resolved_count"] == report.summary.resolved_count


# --------------------------------------------------------------------------- #
# 15. Missing upstream artifacts
# --------------------------------------------------------------------------- #


def test_missing_inventory_raises_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(SourceCodeAnalysisInputError, match="No repository inventory"):
        SourceCodeAnalysisService().run_for_ingested(_ingested(tmp_path))


def test_missing_component_discovery_raises_an_input_error(tmp_path: Path) -> None:
    inventory, _, _, _, _ = build_pipeline("go_grpc")
    write_inventory(inventory, tmp_path)

    with pytest.raises(SourceCodeAnalysisInputError, match="No readable component"):
        SourceCodeAnalysisService().run_for_ingested(_ingested(tmp_path))


def test_missing_dependency_resolution_raises_an_input_error(tmp_path: Path) -> None:
    inventory, _, discovery, _, _ = build_pipeline("go_grpc")
    write_inventory(inventory, tmp_path)
    write_component_discovery(discovery, tmp_path)

    with pytest.raises(SourceCodeAnalysisInputError, match="No readable dependency"):
        SourceCodeAnalysisService().run_for_ingested(_ingested(tmp_path))


def test_run_for_ingested_reuses_the_written_upstream_artifacts(
    tmp_path: Path,
) -> None:
    inventory, _, discovery, dependencies, expected = build_pipeline("go_grpc")
    write_inventory(inventory, tmp_path)
    write_component_discovery(discovery, tmp_path)
    write_dependency_resolution(dependencies, tmp_path)

    source = tmp_path / "source"
    shutil.copytree(FIXTURES / "go_grpc", source)

    path, report = SourceCodeAnalysisService().run_for_ingested(_ingested(tmp_path))

    assert path.name == SOURCE_CODE_ANALYSIS_FILE_NAME
    assert report.summary.resolved_count == expected.summary.resolved_count
    assert report.summary.unresolved_count == expected.summary.unresolved_count


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #


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
