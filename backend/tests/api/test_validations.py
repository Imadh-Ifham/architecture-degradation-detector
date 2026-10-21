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

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.validations import get_architecture_reader, get_validation_service
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
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.components.architecture_validation.service import STAGE_ORDER
from app.components.architecture_validation.validation_reasoning import (
    ValidationReasoningService,
)
from app.infrastructure.ai import (
    TASK_PRIMARY_VERDICT,
    TASK_PRIMARY_VERDICT_FALLBACK,
    TASK_PRIMARY_VERDICT_LOCAL,
    TASK_VERIFICATION,
    AISettings,
    ConfiguredAIClient,
    VerdictCache,
    load_prompt,
)
from app.infrastructure.ai.providers.fake import FakeProvider
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.git.workspace_artifact_reader import ArtifactUnavailableError
from app.infrastructure.recovery_gateway.snapshot_file_reader import (
    SnapshotFileReader,
)
from app.infrastructure.validated_graph import ValidatedGraphFileStore
from app.main import app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "validation"
ARTIFACTS = Path(tempfile.mkdtemp(prefix="c2-api-artifacts-"))
"""Where these runs publish, which is not the project's artifacts tree.

A real file store rather than none: the route is exercised as it is wired, and
publishing is now part of what a run does.
"""
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


def unreachable_reasoner():
    """The real reasoning stage over a provider that cannot answer.

    The suite must never depend on a key or a network: a test that starts
    making real calls the day somebody fills in `.env` is a test that fails
    for reasons unrelated to the code. A provider that cannot answer is the
    one state every machine is guaranteed to be in, and it exercises the rung
    the demonstration's rollback rests on - a verdict from the deterministic
    table, badged as having had no model behind it.
    """

    settings = AISettings(ai_api_key="not-a-real-key")
    client = ConfiguredAIClient(
        FakeProvider(fail_times=99),
        settings=settings,
        cache=VerdictCache("unused", enabled=False),
    )
    return ValidationReasoningService(
        client,
        load_prompt("primary_verdict.v1.md"),
        (
            TASK_PRIMARY_VERDICT,
            TASK_PRIMARY_VERDICT_FALLBACK,
            TASK_PRIMARY_VERDICT_LOCAL,
        ),
        provider="fake",
    )


def unreachable_verifier():
    """The real verification stage over a provider that cannot answer.

    The same reason as the reasoner's: the suite must never depend on a key or
    a network. It exercises the path this unit is on the cut list for - a
    verification that could not run, published as `None`, which classification
    has to treat as uncertain rather than as agreement.
    """

    client = ConfiguredAIClient(
        FakeProvider(fail_times=99),
        settings=AISettings(ai_api_key="not-a-real-key"),
        cache=VerdictCache("unused", enabled=False),
    )
    return IndependentVerificationService(
        client,
        load_prompt("critical_reframing.v1.md"),
        TASK_VERIFICATION,
        provider="fake",
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
        knowledge=DecisionKnowledgeService(
            WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
        ),
        evidence=EvidenceRetrievalService(WorkspaceReader()),
        reasoning=unreachable_reasoner(),
        verification=unreachable_verifier(),
        classification=ClassificationService(),
        review=ArchitectReviewService(),
        publishing=GraphPublishingService(ValidatedGraphFileStore(ARTIFACTS)),
    )
    app.dependency_overrides[get_validation_service] = lambda: service
    # The decision-sources route reads the architecture through its own
    # dependency rather than through the service, so pinning the service
    # alone would leave that route on whatever the environment configures.
    app.dependency_overrides[get_architecture_reader] = lambda: SnapshotFileReader(
        SNAPSHOTS
    )

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
        assert body["implemented_count"] == body["stage_count"] == 8

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

    def test_a_run_over_the_whole_pipeline_is_reported_as_completed(self, client):
        """It asserted `incomplete` while a stage was a stub, and then that
        `published_ref` was not part of the claim once publishing stopped
        depending on the review queue. Eight of eight are now built, so the
        honest assertion is the one it was waiting to be able to make.

        What it still protects is the half that matters: a client must never
        read a partial run as a finished one, so every stage reports a status
        and none of them is left pending.
        """

        body = client.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        ).json()

        assert body["status"] == "completed"
        assert body["model_calls"] == 0
        assert body["published_ref"] is not None
        assert not any(stage["status"] == "pending" for stage in body["stages"])

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

class TestTheDecisionGate:
    """Nothing to validate against is a refusal, and the refusal is guidance.

    The one output this component must never produce is a graph in which
    nothing is contradicted because nothing was ever checked - it is true,
    worthless, and reads exactly like a clean validation of a healthy system.
    """

    def test_a_mode_with_no_decisions_is_refused_rather_than_run(self, client):
        response = client.post(
            "/validations",
            json={
                "repository_id": "online-boutique",
                "release_id": "v0.10.0",
                "decision_mode": "repo_adr",
            },
        )

        assert response.status_code == 409

    def test_the_refusal_carries_every_mode_yield_and_a_recommendation(self, client):
        """A block that does not say what to do instead is a block somebody
        works around."""

        detail = client.post(
            "/validations",
            json={
                "repository_id": "online-boutique",
                "release_id": "v0.10.0",
                "decision_mode": "repo_adr",
            },
        ).json()["detail"]

        assert "repo_adr" in detail and "combined" in detail
        assert "choose 'combined'" in detail

    def test_the_default_mode_produces_a_run(self, client):
        """`combined` is the only mode that yields anything on a repository
        holding no decision records, which is most of them."""

        body = client.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        ).json()

        assert body["decision_mode"] == "combined"

    def test_the_run_reports_how_many_decisions_were_in_force(self, client):
        body = client.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        ).json()
        knowledge = next(
            stage for stage in body["stages"] if stage["name"] == "decision_knowledge"
        )

        assert knowledge["status"] == "completed"
        assert knowledge["counts"]["in_force"] == 26
        assert "mode combined" in knowledge["note"]

    def test_an_unknown_mode_is_refused_against_the_field(self, client):
        """A mode is a closed set, so a typo is a bad field rather than a
        conflict with anything."""

        response = client.post(
            "/validations",
            json={
                "repository_id": "online-boutique",
                "release_id": "v0.10.0",
                "decision_mode": "whatever-we-can-find",
            },
        )

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "decision_mode"]


class TestTheDecisionSourcesRoute:
    """What each mode would supply, read before anything is chosen."""

    def test_a_zero_beside_a_source_carries_that_source_own_words(self, client):
        """A count of zero is not self-explanatory.

        Zero beside the source that reads written decisions can mean the
        repository holds none, or that it holds many and none of them states a
        checkable constraint. The mode's own `reason` cannot carry that: it is
        empty whenever another source supplied something, which is exactly the
        mode where the distinction matters.
        """

        modes = {
            row["mode"]: row
            for row in client.get(
                "/validations/decision-sources",
                params={"repository_id": "online-boutique", "release_id": "v0.10.0"},
            ).json()["modes"]
        }

        assert modes["combined"]["by_source"]["repo_adr"] == 0
        assert modes["combined"]["reason"] is None, "another source supplied 25"
        assert "no decision records" in modes["combined"]["source_notes"]["repo_adr"]


class TestTheDecisionRecordsRoute:
    """The rules behind a count, so the count can be checked."""

    def test_every_rule_names_the_file_it_was_read_from(self, client):
        """A reconstructed rule's whole claim is that somebody can open the
        line it came from. A number on a screen is an assertion until then."""

        body = client.get(
            "/validations/decision-records",
            params={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        ).json()

        assert len(body["records"]) == 26
        assert all(record["source_ref"] for record in body["records"])
        assert all(
            record["source"] == "config_scan" for record in body["records"]
        ), "this repository keeps no written decisions, so all 25 are reconstructed"

    def test_the_rules_match_the_count_the_picker_showed(self, client):
        """Two answers to one question is how a picker promises records that
        never arrive. The listing reads the same sources the same way."""

        params = {"repository_id": "online-boutique", "release_id": "v0.10.0"}
        modes = {
            row["mode"]: row
            for row in client.get(
                "/validations/decision-sources", params=params
            ).json()["modes"]
        }
        listed = client.get(
            "/validations/decision-records", params={**params, "mode": "combined"}
        ).json()

        assert len(listed["records"]) == modes["combined"]["records"]

    def test_an_unknown_mode_is_refused_by_name(self, client):
        response = client.get(
            "/validations/decision-records",
            params={
                "repository_id": "online-boutique",
                "release_id": "v0.10.0",
                "mode": "whatever_we_can_find",
            },
        )

        assert response.status_code == 400
        assert "whatever_we_can_find" in response.json()["detail"]

    def test_every_mode_is_reported_with_its_yield(self, client):
        body = client.get(
            "/validations/decision-sources",
            params={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        ).json()
        modes = {row["mode"]: row for row in body["modes"]}

        assert set(modes) == {"repo_adr", "external_adr", "combined"}
        assert modes["combined"]["records"] == 26
        assert modes["combined"]["by_source"] == {"repo_adr": 0, "config_scan": 26}
        # The breakdown beside the total, because the total on its own is the
        # number a reader carries away and the one most easily overstated:
        # the declared operations are extracted, dated and held, and no
        # observed dependency carries an operation for them to govern.
        assert modes["combined"]["by_constraint"]["declared_rpc"] > 0
        assert modes["combined"]["governing"] < modes["combined"]["records"]
        assert modes["combined"]["governing"] == sum(
            count
            for kind, count in modes["combined"]["by_constraint"].items()
            if kind != "declared_rpc"
        )

    def test_the_empty_mode_says_why_it_is_empty(self, client):
        """The research finding, on the screen: this repository keeps no
        decision records, and the adapter that establishes that ran."""

        modes = {
            row["mode"]: row
            for row in client.get(
                "/validations/decision-sources",
                params={"repository_id": "online-boutique", "release_id": "v0.10.0"},
            ).json()["modes"]
        }

        assert modes["repo_adr"]["ran"] is True
        assert modes["repo_adr"]["records"] == 0
        assert modes["repo_adr"]["reason"]

    def test_a_mode_that_cannot_run_is_not_reported_as_empty(self, client):
        """Not configured and found nothing are different answers, and
        presenting them the same way is how someone picks the wrong mode."""

        modes = {
            row["mode"]: row
            for row in client.get(
                "/validations/decision-sources",
                params={"repository_id": "online-boutique", "release_id": "v0.10.0"},
            ).json()["modes"]
        }

        assert modes["external_adr"]["ran"] is False

    def test_the_recommendation_is_the_mode_with_the_most_to_offer(self, client):
        body = client.get(
            "/validations/decision-sources",
            params={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        ).json()

        assert body["recommended"] == "combined"

    def test_an_unknown_release_is_a_conflict_rather_than_an_empty_report(
        self, client
    ):
        """There is no recorded architecture, so there are no manifests to
        scan - which is a conflict with the state of the workspace rather
        than a repository that declares nothing."""

        response = client.get(
            "/validations/decision-sources",
            params={"repository_id": "online-boutique", "release_id": "v9.9.9"},
        )

        assert response.status_code == 409


class TestARepositoryNobodyIngested:
    """The first thing anyone tries, and it used to be a 500.

    Running a validation before the repository has been cloned is a user
    error, not a fault here - so it is a conflict with the state of the
    workspace, carrying the sentence that says what to do about it. It reached
    the client as an unhandled exception until the manual test guide walked
    through the route and hit it.
    """

    @pytest.fixture
    def client_without_a_checkout(self):
        class NoCheckout:
            def read_text(self, repository_id, release_id, path):
                raise ArtifactUnavailableError(
                    f"No workspace checkout for '{repository_id}'. Ingest it first."
                )

            def list_paths(self, repository_id, release_id, pattern):
                raise ArtifactUnavailableError(
                    f"No workspace checkout for '{repository_id}'. Ingest it first."
                )

        service = ArchitectureValidationService(
            architecture_reader=SnapshotFileReader(SNAPSHOTS),
            normalization=ObservationNormalizationService(),
            knowledge=DecisionKnowledgeService(
                NoCheckout(), JsonlDecisionStore(FIXTURES / "decisions")
            ),
            evidence=EvidenceRetrievalService(NoCheckout()),
            reasoning=unreachable_reasoner(),
            verification=unreachable_verifier(),
            classification=ClassificationService(),
            review=ArchitectReviewService(),
            publishing=GraphPublishingService(ValidatedGraphFileStore(ARTIFACTS)),
        )
        app.dependency_overrides[get_validation_service] = lambda: service
        app.dependency_overrides[get_architecture_reader] = lambda: SnapshotFileReader(
            SNAPSHOTS
        )

        with TestClient(app) as test_client:
            yield test_client

        app.dependency_overrides.clear()

    def test_a_run_says_to_ingest_the_repository_rather_than_failing(
        self, client_without_a_checkout
    ):
        response = client_without_a_checkout.post(
            "/validations",
            json={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        )

        assert response.status_code == 409
        assert "Ingest it first" in response.json()["detail"]

    def test_the_decision_sources_route_says_the_same_thing(
        self, client_without_a_checkout
    ):
        """Asked before a run, so it is the route most likely to be hit first."""

        response = client_without_a_checkout.get(
            "/validations/decision-sources",
            params={"repository_id": "online-boutique", "release_id": "v0.10.0"},
        )

        assert response.status_code == 409
        assert "Ingest it first" in response.json()["detail"]


class TestTheValidatedReleasesRoute:
    """Which releases have been judged, answered from the store.

    It exists because a screen was answering it from memory. The pipeline
    decided whether anything had been judged from the runs the browser session
    happened to have started, so a refresh made validated releases read as
    unjudged - and the detect phase, rendered only once something is judged,
    disappeared with them while its input sat published on disk.
    """

    def store(self, monkeypatch, root):
        from app.api import validations as module

        monkeypatch.setattr(
            module, "get_graph_file_store", lambda: ValidatedGraphFileStore(root)
        )

    def publish(self, root, repository: str, release: str) -> None:
        """A release counts as validated when its `latest` document exists."""

        directory = root / repository / release
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "latest.graph.json").write_text("{}", encoding="utf-8")

    def test_it_lists_every_release_with_a_published_graph(
        self, client, monkeypatch, tmp_path
    ):
        self.store(monkeypatch, tmp_path)
        self.publish(tmp_path, "repo-1", "v0.8.1")
        self.publish(tmp_path, "repo-1", "v0.10.0")

        response = client.get("/validations/validated", params={"repository_id": "repo-1"})

        assert response.status_code == 200
        assert response.json() == {"releases": ["v0.10.0", "v0.8.1"]}

    def test_a_directory_without_a_document_is_not_a_validated_release(
        self, client, monkeypatch, tmp_path
    ):
        """A run that failed before publishing leaves the directory behind.
        Counting it would put the detect phase on screen with nothing to read."""

        self.store(monkeypatch, tmp_path)
        self.publish(tmp_path, "repo-1", "v0.8.1")
        (tmp_path / "repo-1" / "v0.9.0").mkdir(parents=True)

        response = client.get("/validations/validated", params={"repository_id": "repo-1"})

        assert response.json() == {"releases": ["v0.8.1"]}

    def test_a_repository_with_nothing_validated_is_an_empty_list(
        self, client, monkeypatch, tmp_path
    ):
        """Not a 404. "Nothing has been validated" is an answer the screen
        acts on, and a repository nobody ingested is the same answer."""

        self.store(monkeypatch, tmp_path)

        response = client.get(
            "/validations/validated", params={"repository_id": "never-ingested"}
        )

        assert response.status_code == 200
        assert response.json() == {"releases": []}

    def test_one_repository_does_not_report_another_s_releases(
        self, client, monkeypatch, tmp_path
    ):
        self.store(monkeypatch, tmp_path)
        self.publish(tmp_path, "repo-1", "v0.8.1")
        self.publish(tmp_path, "repo-2", "v1.0.0")

        response = client.get("/validations/validated", params={"repository_id": "repo-2"})

        assert response.json() == {"releases": ["v1.0.0"]}
