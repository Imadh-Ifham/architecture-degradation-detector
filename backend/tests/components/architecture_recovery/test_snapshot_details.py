"""Snapshot detail projection tests.

Description:
    The projection joins evidence onto a stored snapshot. What matters is that
    it only ever restates what the artifacts say: a protocol is reported when
    a manifest declared it or a source finding observed it, and reported as
    unknown otherwise. A dependency between two components proves neither.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.components.architecture_recovery.snapshot_details import SnapshotDetails
from app.domain.architecture_snapshot import (
    AnalysisRun,
    ArchitectureSnapshot,
    IdentityBasis,
    OrderSource,
    ReleaseMetadata,
    SnapshotElement,
    SnapshotEvidence,
    SnapshotRelationship,
    SnapshotStatus,
)


def snapshot(
    relationships: tuple[SnapshotRelationship, ...] = (),
) -> ArchitectureSnapshot:
    """A minimal two-element snapshot over the ids the artifacts will use."""

    return ArchitectureSnapshot(
        snapshot_id="snapshot:test",
        status=SnapshotStatus.COMPLETE,
        release=ReleaseMetadata(
            repository_id="repo-1",
            commit_sha="a" * 40,
            release_tag="v1.0.0",
        ),
        run=AnalysisRun(
            analysis_id="analysis:1",
            analysis_timestamp=datetime(2026, 10, 20, tzinfo=UTC),
            configuration_key="cfg",
        ),
        order_timestamp=datetime(2026, 10, 20, tzinfo=UTC),
        order_source=OrderSource.RELEASE_DATE,
        elements=(
            SnapshotElement(
                id="component:frontend",
                name="frontend",
                kind="application",
                identity_basis=IdentityBasis.DIRECT,
                confidence="direct",
                evidence=(
                    SnapshotEvidence(
                        stage="component_discovery",
                        type="component",
                        declared=True,
                        references=("component:frontend",),
                    ),
                ),
            ),
            SnapshotElement(
                id="component:cart",
                name="cart",
                kind="service",
                identity_basis=IdentityBasis.DIRECT,
                confidence="direct",
            ),
        ),
        relationships=relationships,
    )


def edge(*references: str) -> SnapshotRelationship:
    return SnapshotRelationship(
        id="dependency:1",
        source_id="component:frontend",
        target_id="component:cart",
        kind="service_dependency",
        evidence=(
            SnapshotEvidence(
                stage="dependency_resolution",
                type="configured_endpoint",
                declared=True,
                references=references or ("dependency:1",),
            ),
        ),
    )


def write(directory: Path, name: str, payload: dict) -> None:
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


class TestProtocols:
    def test_a_declared_endpoint_protocol_is_reported_as_declared(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            "dependency_resolution.json",
            {
                "relationships": [
                    {
                        "id": "dependency:1",
                        "type": "configured_endpoint",
                        "protocols": ["tcp"],
                        "endpoints": ["cart:7070"],
                        "ports": [7070],
                        "confidence": "declared",
                        "resolution_method": "kubernetes_service_selector",
                        "evidence": [],
                    }
                ]
            },
        )

        document = SnapshotDetails(tmp_path).build(snapshot((edge(),)))

        relationship = document["relationships"][0]

        assert relationship["protocols"] == ["tcp"]
        assert relationship["protocol_source"] == "declared"
        assert relationship["endpoints"] == ["cart:7070"]
        assert relationship["ports"] == [7070]

    def test_a_typed_source_finding_supplies_the_protocol(self, tmp_path: Path) -> None:
        """The finding type states the protocol; nothing is guessed from it."""

        write(
            tmp_path,
            "source_code_analysis.json",
            {
                "findings": [
                    {
                        "id": "finding:1",
                        "finding_type": "http_service_call",
                        "evidence_strength": "observed_invocation",
                        "language": "go",
                        "target_reference": "cart:7070",
                        "evidence": [
                            {
                                "evidence_type": "http_client_invocation",
                                "strength": "observed_invocation",
                                "path": "src/frontend/handlers.go",
                                "line": 42,
                                "detail": "http.Get(...)",
                                "language": "go",
                            }
                        ],
                    }
                ]
            },
        )

        document = SnapshotDetails(tmp_path).build(snapshot((edge("finding:1"),)))

        relationship = document["relationships"][0]

        assert relationship["protocols"] == ["http"]
        assert relationship["protocol_source"] == "source"
        assert relationship["endpoints"] == []
        assert relationship["source_evidence"][0]["path"] == "src/frontend/handlers.go"
        assert relationship["source_findings"][0]["type"] == "http_service_call"

    def test_a_declared_protocol_wins_over_an_observed_one(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            "dependency_resolution.json",
            {
                "relationships": [
                    {"id": "dependency:1", "protocols": ["tcp"], "evidence": []}
                ]
            },
        )
        write(
            tmp_path,
            "source_code_analysis.json",
            {"findings": [{"id": "finding:1", "finding_type": "grpc_service_call"}]},
        )

        relationship = SnapshotDetails(tmp_path).build(
            snapshot((edge("dependency:1", "finding:1"),))
        )["relationships"][0]

        assert relationship["protocols"] == ["tcp"]
        assert relationship["protocol_source"] == "declared"

    def test_no_evidence_at_all_is_reported_as_unknown(self, tmp_path: Path) -> None:
        relationship = SnapshotDetails(tmp_path).build(snapshot((edge(),)))[
            "relationships"
        ][0]

        assert relationship["protocols"] == []
        assert relationship["protocol_source"] == "unknown"
        assert relationship["resolution"] is None

    def test_a_port_without_a_protocol_does_not_become_one(
        self, tmp_path: Path
    ) -> None:
        """A number is not a claim about what runs on it."""

        write(
            tmp_path,
            "dependency_resolution.json",
            {
                "relationships": [
                    {"id": "dependency:1", "ports": [7070], "evidence": []}
                ]
            },
        )

        relationship = SnapshotDetails(tmp_path).build(snapshot((edge(),)))[
            "relationships"
        ][0]

        assert relationship["protocols"] == []
        assert relationship["protocol_source"] == "unknown"
        assert relationship["ports"] == [7070]


class TestMissingEvidence:
    def test_no_clone_reports_every_artifact_absent(self) -> None:
        document = SnapshotDetails(None).build(snapshot())

        assert [item["present"] for item in document["artifacts"]] == [
            False,
            False,
            False,
            False,
            False,
        ]

        # The elements still arrive, with nothing joined onto them.
        assert len(document["elements"]) == 2
        assert document["elements"][0]["files"] == []
        assert document["elements"][0]["artifacts"] == []

    def test_an_unreadable_artifact_is_absent_rather_than_fatal(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "component_discovery.json").write_text("{not json", encoding="utf-8")

        document = SnapshotDetails(tmp_path).build(snapshot())

        present = {item["name"]: item["present"] for item in document["artifacts"]}

        assert present["component_discovery"] is False
        assert document["elements"][0]["name"] == "frontend"

    def test_an_element_discovery_never_saw_is_still_described(
        self, tmp_path: Path
    ) -> None:
        write(tmp_path, "component_discovery.json", {"components": [], "artifacts": []})

        document = SnapshotDetails(tmp_path).build(snapshot())
        frontend = document["elements"][0]

        assert frontend["detected"]["type"] is None
        assert frontend["snapshot_evidence"][0]["type"] == "component"


class TestJoining:
    def test_files_and_languages_come_from_the_inventory(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path,
            "component_discovery.json",
            {
                "components": [
                    {
                        "id": "component:frontend",
                        "name": "frontend",
                        "type": "application",
                        "confidence": "direct",
                        "root_path": "src/frontend",
                        "languages": ["go"],
                        "file_count": 2,
                        "inventory_component_id": "inventory:frontend",
                        "artifact_ids": ["artifact:go-mod"],
                        "evidence": [
                            {
                                "source": "go.mod",
                                "type": "build_unit",
                                "detail": "go module",
                                "confidence": "direct",
                                "rule": "build_manifest_owns_directory",
                            }
                        ],
                    }
                ],
                "artifacts": [
                    {
                        "id": "artifact:go-mod",
                        "role": "build",
                        "kind": "go_module",
                        "path": "src/frontend/go.mod",
                        "confidence": "direct",
                    }
                ],
            },
        )
        write(
            tmp_path,
            "repository_inventory.json",
            {
                "files": [
                    {
                        "path": "src/frontend/go.mod",
                        "name": "go.mod",
                        "category": "build_manifest",
                        "language": None,
                        "component_id": "inventory:frontend",
                        "size_bytes": 40,
                    },
                    {
                        "path": "src/frontend/main.go",
                        "name": "main.go",
                        "category": "source_code",
                        "language": "go",
                        "component_id": "inventory:frontend",
                        "size_bytes": 120,
                    },
                ]
            },
        )

        frontend = SnapshotDetails(tmp_path).build(snapshot())["elements"][0]

        assert frontend["detected"]["root_path"] == "src/frontend"
        assert frontend["detected"]["method"] == "build_manifest_owns_directory"
        assert [item["path"] for item in frontend["artifacts"]] == [
            "src/frontend/go.mod"
        ]
        assert frontend["source_file_count"] == 1
        assert frontend["languages"] == ["go"]
        assert len(frontend["files"]) == 2

    def test_the_snapshot_ids_are_the_join_key(self, tmp_path: Path) -> None:
        """Element ids and evidence references are what the artifacts are keyed by."""

        write(
            tmp_path,
            "component_discovery.json",
            {
                "components": [
                    {"id": "component:cart", "name": "cart", "type": "service"}
                ]
            },
        )

        document = SnapshotDetails(tmp_path).build(snapshot())

        cart = next(item for item in document["elements"] if item["id"] == "component:cart")

        assert cart["detected"]["type"] == "service"
