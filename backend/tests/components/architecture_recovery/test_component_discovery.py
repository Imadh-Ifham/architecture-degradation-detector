"""Tests for the component discovery subcomponent.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Covers discovery accuracy *and* incorrect merges: it is as important that
    unrelated components stay separate as that expected components are found.

    Each fixture repository is run through the real inventory and manifest
    analysis stages first, so these are end-to-end tests of the pipeline from a
    working tree. No network access or live clone is required.
"""

import json
from pathlib import Path

import pytest

from app.components.architecture_recovery.component_discovery import (
    COMPONENT_DISCOVERY_FILE_NAME,
    ArtifactRole,
    AssociationConfidence,
    AssociationType,
    ComponentDiscoveryService,
    ComponentType,
    DiscoveryInputError,
    MergeRule,
    load_component_discovery,
    write_component_discovery,
)
from app.components.architecture_recovery.manifest_analysis import (
    ManifestAnalysisService,
)
from app.components.architecture_recovery.repository_inventory import (
    RepositoryInventoryService,
)
from app.components.architecture_recovery.repository_inventory.models import (
    RepositoryRef,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "component_discovery"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def build(fixture: str):
    """Run the full pipeline over a fixture and return the discovery report."""

    root = FIXTURES / fixture
    inventory = RepositoryInventoryService().build(
        root, RepositoryRef(id=fixture, branch="main", commit="a" * 40)
    )
    analysis = ManifestAnalysisService().analyze(inventory, root)

    return ComponentDiscoveryService().discover(inventory, analysis)


def document(fixture: str) -> dict:
    """Return the serialised discovery report for a fixture."""

    return build(fixture).to_dict()


def component_named(payload: dict, name: str) -> dict:
    """Return the component with the given name, failing when absent."""

    for component in payload["components"]:
        if component["name"] == name:
            return component

    present = sorted(item["name"] for item in payload["components"])
    raise AssertionError(f"component '{name}' not found; present: {present}")


def components_named(payload: dict, name: str) -> list[dict]:
    """Return every component with the given name."""

    return [item for item in payload["components"] if item["name"] == name]


def artifacts_of(payload: dict, component: dict) -> list[dict]:
    """Return the artifacts belonging to a component."""

    wanted = set(component["artifact_ids"])

    return [item for item in payload["artifacts"] if item["id"] in wanted]


def associations_of(payload: dict, component: dict) -> set[str]:
    """Return the association types a component uses."""

    return {item["association"] for item in artifacts_of(payload, component)}


def rules_of(component: dict) -> set[str]:
    """Return the merge rules recorded as a component's evidence."""

    return {item["rule"] for item in component["evidence"] if item["rule"]}


# --------------------------------------------------------------------------- #
# 1. A simple application: one deployment and one source project
# --------------------------------------------------------------------------- #


def test_simple_app_is_one_component() -> None:
    payload = document("simple_app")

    assert payload["summary"]["component_count"] == 1

    component = component_named(payload, "orders")

    assert component["type"] == ComponentType.SERVICE.value
    assert component["root_path"] == "services/orders"
    assert component["languages"] == ["go"]


def test_simple_app_associates_all_three_artifacts() -> None:
    payload = document("simple_app")
    component = component_named(payload, "orders")

    assert associations_of(payload, component) == {
        AssociationType.DEPLOYED_AS.value,
        AssociationType.IMPLEMENTED_BY.value,
        AssociationType.DEFINED_BY.value,
    }

    roles = {item["role"] for item in artifacts_of(payload, component)}

    assert roles == {
        ArtifactRole.DEPLOYMENT.value,
        ArtifactRole.IMPLEMENTATION.value,
        ArtifactRole.DEFINITION.value,
    }


# --------------------------------------------------------------------------- #
# 2. A Compose service with a Dockerfile and build context
# --------------------------------------------------------------------------- #


def test_compose_service_dockerfile_project_and_manifest_are_one_component() -> None:
    """The four artifacts describe one logical component, not four."""

    payload = document("compose_service")

    assert payload["summary"]["component_count"] == 1

    component = component_named(payload, "web")

    assert component["type"] == ComponentType.SERVICE.value
    assert component["artifact_count"] == 4
    assert associations_of(payload, component) == {
        AssociationType.DEPLOYED_AS.value,
        AssociationType.BUILT_FROM.value,
        AssociationType.IMPLEMENTED_BY.value,
        AssociationType.DEFINED_BY.value,
    }


def test_compose_build_context_is_direct_evidence() -> None:
    payload = document("compose_service")
    component = component_named(payload, "web")

    assert MergeRule.BUILD_CONTEXT_CONTAINMENT.value in rules_of(component)
    assert component["confidence"] == AssociationConfidence.DIRECT.value


def test_dockerfile_records_its_build_stages() -> None:
    payload = document("compose_service")
    component = component_named(payload, "web")

    dockerfile = next(
        item for item in artifacts_of(payload, component) if item["kind"] == "dockerfile"
    )

    assert dockerfile["attributes"]["stages"] == ["build", "stage-1"]
    assert dockerfile["attributes"]["stage_count"] == 2
    # Base images are recorded but are not identity evidence.
    assert "node:20" in dockerfile["attributes"]["base_images"]


# --------------------------------------------------------------------------- #
# 3. Kubernetes workloads and their Services
# --------------------------------------------------------------------------- #


def test_kubernetes_service_does_not_become_a_component() -> None:
    payload = document("k8s_workload_and_service")

    assert payload["summary"]["component_count"] == 1

    component = component_named(payload, "backend")

    assert component["type"] == ComponentType.SERVICE.value


def test_kubernetes_services_attach_to_their_workload() -> None:
    """Both Services and the ConfigMap stay artifacts, not components."""

    payload = document("k8s_workload_and_service")
    component = component_named(payload, "backend")

    attached = {
        item["name"]
        for item in artifacts_of(payload, component)
        if item["kind"] == "kubernetes_service"
    }

    assert attached == {"backend", "backend-external"}

    names = {item["name"] for item in payload["components"]}

    assert "backend-external" not in names
    assert "backend-config" not in names


def test_attached_service_evidence_explains_why() -> None:
    payload = document("k8s_workload_and_service")
    component = component_named(payload, "backend")

    details = [item["detail"] for item in component["evidence"]]

    assert any("exposes this component's workload" in detail for detail in details)


# --------------------------------------------------------------------------- #
# 4. A repository containing multiple services
# --------------------------------------------------------------------------- #


def test_multiple_services_are_discovered_separately() -> None:
    payload = document("multi_service")

    assert payload["summary"]["component_count"] == 3
    assert sorted(item["name"] for item in payload["components"]) == [
        "api",
        "cache",
        "worker",
    ]


def test_multi_service_keeps_languages_apart() -> None:
    payload = document("multi_service")

    assert component_named(payload, "api")["languages"] == ["python"]
    assert component_named(payload, "worker")["languages"] == ["go"]


def test_image_only_service_has_no_location() -> None:
    """A service built from an image has no source project to point at."""

    payload = document("multi_service")

    assert component_named(payload, "cache")["root_path"] is None


# --------------------------------------------------------------------------- #
# 5. Source projects with no deployment manifests
# --------------------------------------------------------------------------- #


def test_source_only_repository_yields_applications() -> None:
    payload = document("source_only")

    assert payload["summary"]["by_type"] == {ComponentType.APPLICATION.value: 2}

    for component in payload["components"]:
        assert component["confidence"] == AssociationConfidence.DIRECT.value
        assert associations_of(payload, component) == {
            AssociationType.IMPLEMENTED_BY.value,
            AssociationType.DEFINED_BY.value,
        }


# --------------------------------------------------------------------------- #
# 6. Artifacts whose component identity cannot be determined
# --------------------------------------------------------------------------- #


def test_orphan_artifacts_are_unresolved_not_invented_as_components() -> None:
    payload = document("orphan_artifacts")

    assert payload["components"] == []
    assert payload["summary"]["unresolved_count"] == 3

    kinds = {item["kind"] for item in payload["unresolved"]}

    assert kinds == {"dockerfile", "protobuf_service", "openapi_document"}


def test_unresolved_artifacts_carry_a_reason() -> None:
    payload = document("orphan_artifacts")

    for item in payload["unresolved"]:
        assert item["reason"]
        assert item["evidence"]


# --------------------------------------------------------------------------- #
# 7. Conflicting and ambiguous evidence
# --------------------------------------------------------------------------- #


def test_same_name_in_unrelated_locations_is_not_merged() -> None:
    """A shared name alone must not merge two distinct projects."""

    payload = document("conflicting")

    frontends = components_named(payload, "frontend")

    assert len(frontends) == 2

    roots = sorted(item["root_path"] for item in frontends)

    assert roots == ["one/frontend", "shared/frontend"]


def test_duplicate_identity_is_reported() -> None:
    payload = document("conflicting")

    assert payload["summary"]["duplicate_identity_count"] == 1
    assert payload["summary"]["ambiguous_count"] == 1

    ambiguity = payload["ambiguous"][0]

    assert ambiguity["kind"] == "duplicate_identity"
    assert len(ambiguity["candidate_component_ids"]) == 2


def test_unrelated_dockerfile_stays_unresolved() -> None:
    payload = document("conflicting")

    assert [item["path"] for item in payload["unresolved"]] == ["shared/Dockerfile"]


def test_selector_matching_two_workloads_is_ambiguous() -> None:
    """A Service that selects several workloads is not attached to just one."""

    payload = document("ambiguous_service")

    assert sorted(item["name"] for item in payload["components"]) == ["alpha", "beta"]

    ambiguity = next(
        item for item in payload["ambiguous"] if item["kind"] == "kubernetes_service"
    )

    assert ambiguity["name"] == "shared-api"
    assert len(ambiguity["candidate_component_ids"]) == 2


# --------------------------------------------------------------------------- #
# 10. Sensitive values
# --------------------------------------------------------------------------- #


def test_sensitive_values_never_reach_the_output() -> None:
    payload = document("sensitive")
    blob = json.dumps(payload)

    for secret in ("supersecret", "tokenvalue123", "postgres://user:pw@db:5432/app"):
        assert secret not in blob


def test_sensitive_repository_details_are_still_discovered() -> None:
    """Redaction must not cost the structural findings."""

    payload = document("sensitive")

    assert payload["summary"]["component_count"] == 1

    component = component_named(payload, "app")

    assert component["artifact_count"] == 4


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_output_is_deterministic_across_runs() -> None:
    for fixture in ("multi_service", "conflicting", "compose_service", "k8s_workload_and_service"):
        first = document(fixture)
        second = document(fixture)

        first.pop("generated_at")
        second.pop("generated_at")

        assert first == second, fixture


def test_identifiers_are_stable_and_content_addressed() -> None:
    payload = document("multi_service")
    identifiers = [item["id"] for item in payload["components"]]

    assert len(identifiers) == len(set(identifiers))

    for identifier in identifiers:
        assert identifier.startswith("component:")

    for artifact in payload["artifacts"]:
        assert artifact["id"].startswith("artifact:")


def test_every_referenced_artifact_exists_and_is_owned_once() -> None:
    payload = document("multi_service")
    known = {item["id"] for item in payload["artifacts"]}
    referenced = [
        artifact_id
        for component in payload["components"]
        for artifact_id in component["artifact_ids"]
    ]

    assert set(referenced) <= known
    assert len(referenced) == len(set(referenced))


def test_every_component_and_artifact_carries_evidence() -> None:
    payload = document("multi_service")

    for component in payload["components"]:
        assert component["evidence"]

    for artifact in payload["artifacts"]:
        assert artifact["evidence"]
        assert artifact["evidence"][0]["confidence"] in ("direct", "heuristic")


# --------------------------------------------------------------------------- #
# 8. Missing or malformed upstream artifacts
# --------------------------------------------------------------------------- #


def test_missing_inventory_is_an_input_error(tmp_path: Path) -> None:
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

    with pytest.raises(DiscoveryInputError):
        ComponentDiscoveryService().run_for_ingested(ingested)


def test_malformed_inventory_is_an_input_error(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from app.domain.repository import IngestedRepository

    workspace = tmp_path / "repo"
    source = workspace / "source"
    source.mkdir(parents=True)
    (workspace / "repository_inventory.json").write_text("{ not json", encoding="utf-8")

    ingested = IngestedRepository(
        id="repo-1",
        url="https://example.com/team/repo.git",
        branch="main",
        commit="a" * 40,
        path=source,
        ingested_at=datetime.now(timezone.utc),
    )

    with pytest.raises(DiscoveryInputError):
        ComponentDiscoveryService().run_for_ingested(ingested)


def test_malformed_manifest_analysis_is_an_input_error(tmp_path: Path) -> None:
    from app.components.architecture_recovery.manifest_analysis import (
        AnalysisArtifactError,
        load_analysis_report,
    )

    path = tmp_path / "manifest_analysis.json"
    path.write_text(json.dumps({"resources": "not a list"}), encoding="utf-8")

    with pytest.raises(AnalysisArtifactError):
        load_analysis_report(path)


def test_missing_manifest_analysis_is_an_input_error(tmp_path: Path) -> None:
    from app.components.architecture_recovery.manifest_analysis import (
        AnalysisArtifactError,
        load_analysis_report,
    )

    with pytest.raises(AnalysisArtifactError):
        load_analysis_report(tmp_path / "absent.json")


def test_one_bad_manifest_does_not_lose_the_other_components() -> None:
    """An unparseable file must not invalidate the components that were found."""

    payload = document("ambiguous_service")

    assert len(payload["components"]) == 2
    assert payload["summary"]["ambiguous_count"] == 1


# --------------------------------------------------------------------------- #
# Output artifact and loaders
# --------------------------------------------------------------------------- #


def test_writer_produces_one_versioned_artifact(tmp_path: Path) -> None:
    report = build("multi_service")

    written = write_component_discovery(report, tmp_path)

    assert written.name == COMPONENT_DISCOVERY_FILE_NAME
    assert [item.name for item in tmp_path.iterdir()] == [
        COMPONENT_DISCOVERY_FILE_NAME
    ]

    payload = load_component_discovery(written)

    assert payload["schema_version"] == "1.0.0"
    assert payload["generator"]["name"] == "component_discovery"
    assert payload["repository"]["id"] == "multi_service"
    assert payload["options"]["identity_policy"]


def test_writer_replaces_an_existing_report(tmp_path: Path) -> None:
    report = build("multi_service")

    first = write_component_discovery(report, tmp_path)
    second = write_component_discovery(report, tmp_path)

    assert first == second
    assert [item.name for item in tmp_path.iterdir()] == [
        COMPONENT_DISCOVERY_FILE_NAME
    ]


def test_run_for_ingested_reads_the_upstream_artifacts(tmp_path: Path) -> None:
    """The disk path must agree with the in-memory path."""

    from datetime import datetime, timezone

    from app.domain.repository import IngestedRepository

    source = FIXTURES / "multi_service"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ingested = IngestedRepository(
        id="multi_service",
        url="https://example.com/team/repo.git",
        branch="main",
        commit="a" * 40,
        path=workspace / "source",
        ingested_at=datetime.now(timezone.utc),
    )
    ingested.path.mkdir()

    # Populate the workspace exactly as the running pipeline would.
    inventory = RepositoryInventoryService().build(
        source, RepositoryRef(id="multi_service")
    )
    analysis = ManifestAnalysisService().analyze(inventory, source)

    from app.components.architecture_recovery.manifest_analysis import (
        write_manifest_analysis,
    )
    from app.components.architecture_recovery.repository_inventory import (
        write_inventory,
    )

    write_inventory(inventory, workspace)
    write_manifest_analysis(analysis, workspace)

    written, report = ComponentDiscoveryService().run_for_ingested(ingested)

    assert written.parent == workspace
    assert written.name == COMPONENT_DISCOVERY_FILE_NAME
    assert report.repository.id == "multi_service"

    summary = report.summary
    expected = build("multi_service").summary

    assert summary.component_count == expected.component_count
    assert summary.by_type == expected.by_type
    assert sorted(item.name for item in report.components) == ["api", "cache", "worker"]


def test_no_component_is_derived_from_a_name_alone() -> None:
    """A contract whose name matches nothing must not fabricate a component."""

    payload = document("orphan_artifacts")

    assert payload["components"] == []


def test_summary_counts_agree_with_the_collections() -> None:
    for fixture in ("multi_service", "conflicting", "orphan_artifacts"):
        payload = document(fixture)
        summary = payload["summary"]

        assert summary["component_count"] == len(payload["components"])
        assert summary["artifact_count"] == len(payload["artifacts"])
        assert summary["unresolved_count"] == len(payload["unresolved"])
        assert summary["ambiguous_count"] == len(payload["ambiguous"])

        direct = sum(
            1
            for item in payload["artifacts"]
            if item["confidence"] == AssociationConfidence.DIRECT.value
        )

        assert summary["direct_association_count"] == direct
