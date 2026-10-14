"""Architecture validation endpoint tests.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Checks the three things a client depends on: that the pipeline description
    is served from the component rather than restated in the transport layer,
    that a run returns its stage records even while most stages are stubs, and
    that the generated documentation describes what the routes really do.

    The service under test is the real one with a reader over the committed
    inventory fixtures, so these exercise the same wiring the application uses
    and not a rehearsal of it.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.validations import get_validation_service
from app.components.architecture_validation import (
    PIPELINE,
    ArchitectureValidationService,
)
from app.components.architecture_validation.architect_review import (
    ArchitectReviewService,
)
from app.components.architecture_validation.classification import ClassificationService
from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
)
from app.components.architecture_validation.evidence_retrieval import (
    EvidenceRetrievalService,
)
from app.components.architecture_validation.graph_publishing import (
    GraphPublishingService,
)
from app.components.architecture_validation.independent_verification import (
    IndependentVerificationService,
)
from app.components.architecture_validation.intent_extraction import (
    IntentExtractionService,
)
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.components.architecture_validation.service import STAGE_ORDER
from app.components.architecture_validation.validation_reasoning import (
    ValidationReasoningService,
)
from app.infrastructure.recovery_gateway.snapshot_file_reader import (
    SnapshotFileReader,
)
from app.main import app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "validation"
SUBJECT = FIXTURES / "subject"
SNAPSHOTS = Path(__file__).resolve().parents[2] / "data" / "snapshots"


class WorkspaceReader:
    """Reads the generated subject tree in place of an ingested checkout."""

    def read_text(self, repository_id, release_id, path):
        return (SUBJECT / release_id / path).read_text(encoding="utf-8")

    def list_paths(self, repository_id, release_id, pattern):
        root = SUBJECT / release_id
        return sorted(
            str(match.relative_to(root)).replace("\\", "/")
            for match in root.glob(pattern)
        )


@pytest.fixture
def client():
    """A client whose validation service reads the committed fixtures.

    Only the two readers are substituted. Every subcomponent is the real one,
    which is what makes the run below a genuine report of how far the component
    has been built.
    """

    service = ArchitectureValidationService(
        architecture_reader=SnapshotFileReader(SNAPSHOTS),
        normalization=ObservationNormalizationService(),
        intent=IntentExtractionService(),
        knowledge=DecisionKnowledgeService(),
        evidence=EvidenceRetrievalService(),
        reasoning=ValidationReasoningService(),
        verification=IndependentVerificationService(),
        classification=ClassificationService(),
        review=ArchitectReviewService(),
        publishing=GraphPublishingService(),
    )
    app.dependency_overrides[get_validation_service] = lambda: service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


class TestPipelineEndpoint:
    """The stage list a client renders before any run exists."""

    def test_it_returns_every_stage_in_run_order(self, client):
        body = client.get("/validations/pipeline").json()

        assert [stage["name"] for stage in body["stages"]] == list(STAGE_ORDER)
        assert body["stage_count"] == len(STAGE_ORDER)

    def test_it_reports_how_many_stages_are_built(self, client):
        """So a client shows build progress without hard-coding it."""

        body = client.get("/validations/pipeline").json()

        assert body["implemented_count"] == sum(1 for s in PIPELINE if s.implemented)
        assert 0 < body["implemented_count"] < body["stage_count"]

    def test_every_stage_carries_what_the_screen_renders(self, client):
        stage = client.get("/validations/pipeline").json()["stages"][0]

        assert set(stage) == {
            "name",
            "order",
            "role",
            "research_module",
            "uses_model",
            "implemented",
        }
        assert stage["role"].endswith(".")


class TestRunEndpoint:
    """A run reports what each stage did, finished or not."""

    def test_a_run_returns_a_record_for_every_stage(self, client):
        response = client.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        )

        assert response.status_code == 200
        body = response.json()
        assert [stage["name"] for stage in body["stages"]] == list(STAGE_ORDER)

    def test_the_implemented_stage_reports_real_counts(self, client):
        body = client.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        ).json()
        normalisation = body["stages"][0]

        assert normalisation["status"] == "completed"
        assert normalisation["counts"]["facts"] > 0
        assert normalisation["duration_ms"] >= 0

    def test_a_stage_record_publishes_exactly_the_documented_fields(self, client):
        """The run's stage shape is a published contract, so it is pinned.

        A field added here without being added to the documentation is a
        client reading a shape nobody described; a field removed is a client
        reading nothing. Either way the test is the cheaper way to find out.
        """

        stage = client.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        ).json()["stages"][0]

        assert set(stage) == {
            "name",
            "status",
            "counts",
            "duration_ms",
            "note",
            "warnings",
        }

    def test_normalisation_publishes_its_identity_counters(self, client):
        """Both are zero on this snapshot, and publishing the zero is the
        point: it is the measured answer to "could your canonicalisation have
        merged two services", not a claim that it could not."""

        counts = client.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        ).json()["stages"][0]["counts"]

        assert counts["identity_collisions"] == 0
        assert counts["merged_facts"] == 0

    def test_a_run_with_stages_still_stubbed_is_reported_as_incomplete(self, client):
        """A client must never read a partial run as a finished one."""

        body = client.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        ).json()

        assert body["status"] == "incomplete"
        assert body["model_calls"] == 0
        assert body["published_ref"] is None
        assert any(stage["status"] == "pending" for stage in body["stages"])

    def test_an_unknown_release_is_a_conflict_rather_than_a_server_error(self, client):
        """No recording for that release is the caller's to fix, not a fault."""

        response = client.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "v9.9.9"},
        )

        assert response.status_code == 409
        assert "snapshot" in response.json()["detail"].lower()

    def test_a_release_is_required(self, client):
        response = client.post(
            "/validations", json={"repository_id": "online-boutique", "release_id": ""}
        )

        assert response.status_code == 422

    def test_an_unorderable_release_is_refused_against_the_field(self, client):
        """Rejected before anything is read, and attached to the field.

        A release that cannot be placed in order leaves no temporal claim to
        make, so there is nothing to gain by reading a snapshot for it first -
        and "no snapshot for that release" would be the wrong explanation.
        """

        response = client.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "2024-Q3"},
        )

        assert response.status_code == 422
        problem = response.json()["detail"][0]
        assert problem["loc"] == ["body", "release_id"]
        assert "2024-Q3" in problem["msg"]


class TestGeneratedDocumentation:
    """What /docs shows has to match what the routes do.

    The schema is generated from the models, so these check the parts that are
    written by hand and would otherwise drift: the failures a route declares,
    and the example body that makes the page usable without reading the code.
    """

    def test_the_run_route_declares_the_failures_it_can_return(self, client):
        responses = client.get("/openapi.json").json()["paths"]["/validations"]["post"][
            "responses"
        ]

        assert sorted(responses) == ["200", "409", "422"]
        assert all(responses[code]["description"] for code in responses)

    def test_the_request_body_carries_a_working_example(self, client):
        """So the documentation page can be driven as it stands.

        An example that is not the repository and release this component is
        developed against is an example that stops working, which is worse
        than none."""

        schema = client.get("/openapi.json").json()["components"]["schemas"]
        example = schema["ValidationRunRequest"]["examples"][0]

        assert client.post("/validations", json=example).status_code == 200

    def test_every_route_in_this_router_has_a_summary(self, client):
        paths = client.get("/openapi.json").json()["paths"]

        for path, operations in paths.items():
            if not path.startswith("/validations"):
                continue
            for method, operation in operations.items():
                assert operation.get("summary"), f"{method.upper()} {path}"
