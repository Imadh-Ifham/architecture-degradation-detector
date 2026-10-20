"""M8 - the published graph, the three stores, and the trap in the edge key.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    The first test in this file is the acceptance test for the whole
    component's integration, and it is written as the exact call the consuming
    component makes rather than an approximation of it.

    The second asserts the *failure*: read with the library's current default
    the document yields nodes, no edges and no exception. A test that proves
    the trap exists is what stops the keyword being tidied away by somebody
    who cannot see why it is there.

    Everything runs over the real corpus with the model unreachable, which is
    the ladder's last rung: every governed fact decided by the deterministic
    table, nothing audited, and a confidence that says so. It is the case
    where an honest document matters most, because nothing in it came from a
    model at all.
"""

import json
from pathlib import Path

import networkx as nx
import pytest

from app.components.architecture_validation.architect_review import ArchitectReviewService
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
from app.components.architecture_validation.service import ArchitectureValidationService
from app.components.architecture_validation.validation_reasoning import (
    ValidationReasoningService,
)
from app.domain.model_access import ModelUnavailable
from app.domain.validated_architecture import (
    NODE_LINK_EDGE_KEY,
    SizeUnitConflict,
    ValidationBucket,
)
from app.infrastructure.ai import (
    TASK_PRIMARY_VERDICT,
    TASK_VERIFICATION,
    AISettings,
    ConfiguredAIClient,
    VerdictCache,
    load_prompt,
)
from app.infrastructure.validated_graph import LATEST_FILENAME, ValidatedGraphFileStore
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.recovery_gateway import SnapshotFileReader

from .corpus import FIXTURES, REPOSITORY, SNAPSHOTS, WorkspaceReader

RELEASE = "v0.10.0"


class Unreachable:
    """A provider with nothing behind it, which is rung five of the ladder."""

    def complete(self, *args, **kwargs):
        raise ModelUnavailable("no provider in this test")


def unreachable_client() -> ConfiguredAIClient:
    return ConfiguredAIClient(
        Unreachable(),
        settings=AISettings(ai_api_key="not-a-real-key"),
        cache=VerdictCache("unused", enabled=False),
    )


def pipeline(root: Path, recorder=None, projection=None, publisher=None):
    """The whole component, with the model unreachable and a real file store."""

    client = unreachable_client()
    store = publisher if publisher is not None else ValidatedGraphFileStore(root)
    return ArchitectureValidationService(
        architecture_reader=SnapshotFileReader(SNAPSHOTS),
        normalization=ObservationNormalizationService(),
        knowledge=DecisionKnowledgeService(
            WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
        ),
        evidence=EvidenceRetrievalService(WorkspaceReader()),
        reasoning=ValidationReasoningService(
            client, load_prompt("primary_verdict.v1.md"), (TASK_PRIMARY_VERDICT,),
            provider="none", allow_arbiter_only=True,
        ),
        verification=IndependentVerificationService(
            client, load_prompt("critical_reframing.v1.md"), TASK_VERIFICATION,
            provider="none",
        ),
        classification=ClassificationService(),
        review=ArchitectReviewService(),
        publishing=GraphPublishingService(store, recorder, projection),
    )


@pytest.fixture
def published(tmp_path):
    """One completed run, published, with the document beside its reference."""

    run = pipeline(tmp_path).run(repository_id=REPOSITORY, release_id=RELEASE)
    reference = Path(run.published_ref)
    return run, json.loads(reference.read_text(encoding="utf-8")), reference


class TestTheHandover:
    """What the consuming component actually does with the file."""

    def test_the_published_file_round_trips_through_networkx(self, published):
        """Exactly what C3 does. If this fails, the integration fails."""

        _, document, _ = published

        graph = nx.node_link_graph(document, edges="links")

        assert graph.number_of_nodes() == 12
        assert graph.number_of_edges() == 15

    def test_the_wrong_edge_key_raises_on_the_installed_version(self, published):
        """The trap, measured rather than repeated - and it is not what four
        of this project's documents say it is.

        Every one of them, this component's own domain docstring included,
        says a key mismatch *does not raise* and silently yields a graph with
        no edges at all. On the installed NetworkX that is false: reading a
        `links` document as `edges` raises `KeyError`, and so does the
        reverse, and so does a consumer who passes nothing and gets the
        default. Checked in both directions before this test was written.

        The rule does not change - the document is written under `links` and a
        reader must say so - but the failure is immediate and correctly
        attributed rather than a plausible empty answer computed over for
        weeks. That is better news than the documents claim, and it is only
        knowable by running it.
        """

        _, document, _ = published

        with pytest.raises(KeyError):
            nx.node_link_graph(document, edges="edges")

        with pytest.raises(KeyError):
            nx.node_link_graph(document)

        assert nx.node_link_graph(document, edges="links").number_of_edges() == 15

    def test_the_installed_library_still_defaults_to_the_key_we_do_not_use(self):
        """Why the keyword is written by hand in the domain model.

        Asserted rather than pinned in `pyproject.toml`: the dependency is
        shared with two other components, so pinning it is a group decision
        and not this one's to make. A bump that changed the default would
        break the consumer silently; it breaks this instead.
        """

        import inspect

        default = inspect.signature(nx.node_link_data).parameters["edges"].default

        assert default == "edges"
        assert NODE_LINK_EDGE_KEY == "links"

    def test_no_findings_list_exists_anywhere_in_the_document(self, published):
        """The structural half of putting the verdict on the edge: if a list
        of verdicts sat beside the topology, a consumer could join them back
        on - and a join is a place where two sides can disagree about what the
        topology was."""

        _, document, _ = published

        assert set(document) == {"directed", "multigraph", "graph", "nodes", "links"}

    def test_every_verdict_rides_on_the_edge_it_describes(self, published):
        _, document, _ = published
        graph = nx.node_link_graph(document, edges="links")
        names = {data["name"]: node for node, data in graph.nodes(data=True)}

        edge = graph[names["frontend"]][names["cartservice"]]

        assert edge["bucket"] == ValidationBucket.CONFIRMED
        assert edge["governing_decision"] == "rule-frontend-cartservice"
        assert edge["source_tier"] == "tier_2_executable_config"
        assert edge["produced_by"] == "arbiter"

    def test_every_fact_appears_including_the_ones_no_model_saw(self, published):
        run, document, _ = published

        assert len(document["links"]) == len(run.facts)

    def test_the_superseded_decision_never_appears_as_governing(self, published):
        """An ownership boundary, asserted rather than trusted. The consumer
        has no business seeing `sa-shared-component` at v0.10.0, and a
        boundary protected by good intentions is not protected."""

        _, document, _ = published

        governing = {edge["governing_decision"] for edge in document["links"]}

        assert "sa-shared-component" not in governing

    def test_the_document_declares_its_schema_and_what_produced_it(self, published):
        _, document, _ = published
        graph = document["graph"]

        assert graph["schema_version"] == "1.2.0"
        assert graph["run"]["mode"] == "reconstruction"
        assert graph["release_order_key"] == [0, 0, 10, 0, 0, 4, 0, 1, 0]

    def test_a_release_with_no_establishable_date_publishes_null(self, published):
        """Nothing is invented. A plausible wrong date orders the consumer's
        timeline wrongly and cannot be told apart from a right one."""

        _, document, _ = published

        assert document["graph"]["released_at"] is None
        assert document["graph"]["released_at_source"] is None

    def test_a_date_the_caller_supplied_travels_with_its_source(self, tmp_path):
        from datetime import UTC, datetime

        cut = datetime(2025, 4, 1, tzinfo=UTC)
        run = pipeline(tmp_path).run(
            repository_id=REPOSITORY,
            release_id=RELEASE,
            released_at=cut,
            released_at_source="caller",
        )
        document = json.loads(Path(run.published_ref).read_text(encoding="utf-8"))

        assert document["graph"]["released_at"] == cut.isoformat()
        assert document["graph"]["released_at_source"] == "caller"


class TestTheDocumentAgreeingWithItself:
    """Two statements about one fact have to match, or one of them is wrong."""

    def test_the_node_rollups_agree_with_the_edges_they_count(self, published):
        _, document, _ = published
        graph = nx.node_link_graph(document, edges="links")

        for node, data in graph.nodes(data=True):
            outgoing = [d["bucket"] for _, _, d in graph.out_edges(node, data=True)]
            rollup = data["validation_rollup"]
            assert rollup["confirmed"] == outgoing.count("confirmed")
            assert rollup["needs_review"] == outgoing.count("needs_review")

    def test_the_rollups_sum_to_the_facts_rather_than_to_double_them(self, published):
        """Counted at the subject end only. A dependency is a statement about
        the element that reaches out, so counting it at both ends would report
        one finding twice."""

        _, document, _ = published

        counted = sum(
            sum(node["validation_rollup"].values()) for node in document["nodes"]
        )

        assert counted == len(document["links"])

    def test_the_summary_equals_the_stage_counts_it_came_from(self, published):
        run, document, _ = published
        summary = document["graph"]["summary"]
        classification = next(
            s for s in run.stages if s.name == "classification"
        ).counts

        assert summary["facts"] == classification["facts"]
        assert summary["review"] == classification["review"]
        assert summary["validation_confidence"] == run.validation_confidence

    def test_the_confidence_is_bounded_and_equals_the_mean_of_the_facts(self, published):
        run, document, _ = published
        published_value = document["graph"]["validation_confidence"]

        assert 0.0 <= published_value <= 1.0
        assert published_value == pytest.approx(
            sum(fact.confidence for fact in run.facts) / len(run.facts), abs=1e-4
        )

    def test_every_element_appears_even_with_no_dependencies(self, published):
        """The new service at a release that nothing points at yet is an
        observation, and dropping unconnected elements would delete it."""

        _, document, _ = published
        named = {node["name"] for node in document["nodes"]}

        assert "shoppingassistantservice" in named
        assert len(document["nodes"]) == 12


class TestTheFileStore:
    """The two properties the consumer's fail-safe rests on."""

    def test_the_run_specific_file_and_latest_both_land(self, published):
        _, _, reference = published
        latest = reference.parent / LATEST_FILENAME

        assert reference.is_file()
        assert latest.is_file()
        assert json.loads(latest.read_text()) == json.loads(reference.read_text())

    def test_no_partial_file_is_left_behind(self, published):
        """Written to a temporary name in the same directory and moved with
        `os.replace`, so a reader gets the old document whole or the new one
        whole - never a half-written one, which would parse as a release with
        no dependencies."""

        _, _, reference = published

        leftovers = [p.name for p in reference.parent.iterdir() if ".partial" in p.name]

        assert leftovers == []

    def test_an_incomplete_run_publishes_nothing_and_leaves_latest_alone(
        self, tmp_path
    ):
        """The fail-safe. A run that did not finish must not replace a graph
        that did, and the screen then shows the older release and says so."""

        service = pipeline(tmp_path)
        first = service.run(repository_id=REPOSITORY, release_id=RELEASE)

        # A fact-producing stage stalls, which is the only kind of
        # incompleteness that can cost the document a fact.
        stalled = pipeline(tmp_path)
        stalled._evidence = _Raising()
        second = stalled.run(repository_id=REPOSITORY, release_id=RELEASE)

        latest = Path(first.published_ref).parent / LATEST_FILENAME

        assert second.published_ref is None
        assert json.loads(latest.read_text())["graph"]["run"]["run_id"] == first.run_id

    def test_a_failed_file_write_fails_the_run(self, tmp_path):
        """The one write that is a promise.

        It fails the run by raising, which is what a stage that raises does
        today: recording the failure on the stage and returning the run is
        UI-13 and is not built. Asserted as it behaves rather than as it will
        behave, so this test does not quietly pass once that lands.
        """

        service = pipeline(tmp_path, publisher=_FailingPublisher())

        with pytest.raises(OSError, match="not writable"):
            service.run(repository_id=REPOSITORY, release_id=RELEASE)

    def test_a_release_whose_size_unit_changed_is_refused(self, tmp_path):
        """A series measured in lines here and bytes there is a graph of
        nothing, with no error anywhere, because both are numbers."""

        store = ValidatedGraphFileStore(tmp_path)
        store.publish(_sized_document("loc"))

        with pytest.raises(SizeUnitConflict):
            store.publish(_sized_document("bytes", release="v0.11.0"))

    def test_a_release_measuring_nothing_is_not_a_conflict(self, tmp_path):
        """Most releases report no size at all, because recovery does not
        supply one yet."""

        store = ValidatedGraphFileStore(tmp_path)
        store.publish(_sized_document("loc"))

        store.publish(_sized_document(None, release="v0.11.0"))


class TestTheTwoStoresThatMayFail:
    """The file is the contract. The record and the projection are not."""

    def test_an_unconfigured_store_is_not_a_warning(self, published):
        """A run on a laptop with no databases wrote one store. Warning about
        two it was never asked to write would make the warning meaningless."""

        run, _, _ = published
        stage = next(s for s in run.stages if s.name == "graph_publishing")

        assert stage.note == "written to file"
        assert stage.warnings == ()

    def test_a_failed_record_warns_by_name_and_the_file_still_landed(self, tmp_path):
        service = pipeline(tmp_path, recorder=_FailingRecorder())

        result = service.run(repository_id=REPOSITORY, release_id=RELEASE)
        stage = next(s for s in result.stages if s.name == "graph_publishing")

        assert Path(result.published_ref).is_file()
        assert any("record" in warning for warning in stage.warnings)

    def test_a_failed_projection_warns_by_name_and_is_not_a_clean_pass(self, tmp_path):
        """*The graph view is empty* and *the graph store was unreachable
        during the run that filled it* are indistinguishable from a canvas.
        One is a finding about the architecture; the other is a fault."""

        service = pipeline(tmp_path, projection=_FailingProjection())

        result = service.run(repository_id=REPOSITORY, release_id=RELEASE)
        stage = next(s for s in result.stages if s.name == "graph_publishing")

        assert Path(result.published_ref).is_file()
        assert any("projection" in warning for warning in stage.warnings)
        assert stage.note == "written to file"

    def test_both_stores_are_named_when_both_took_it(self, tmp_path):
        recorder, projection = _Recording(), _Recording()

        service = pipeline(tmp_path, recorder=recorder, projection=projection)
        result = service.run(repository_id=REPOSITORY, release_id=RELEASE)
        stage = next(s for s in result.stages if s.name == "graph_publishing")

        assert stage.note == "written to file, record, projection"
        assert recorder.calls == 1
        assert projection.documents[0].release_id == RELEASE


class TestTheProjection:
    """Asserted against a fake session, because the Cypher is the thing worth
    checking and a running database is not required to check it."""

    def test_the_projection_merges_a_release_its_elements_and_its_edges(self, tmp_path):
        from app.infrastructure.neo4j.validated_graph_projection import (
            Neo4jGraphProjection,
        )

        session = _FakeSession()
        projection = Neo4jGraphProjection(lambda: session)

        pipeline(tmp_path, projection=projection).run(
            repository_id=REPOSITORY, release_id=RELEASE
        )

        assert session.counts("MERGE (release:Release") == 1
        assert session.counts("MERGE (element:Element") == 12
        assert session.counts("MERGE (source)-[dependency:VALIDATED_DEPENDENCY") == 15

    def test_the_stale_sweep_runs_last_so_a_reader_never_sees_an_empty_release(
        self, tmp_path
    ):
        """Deleting the subgraph first and rebuilding it would leave a window
        where the release has no dependencies - a valid-looking answer rather
        than an error."""

        from app.infrastructure.neo4j.validated_graph_projection import (
            Neo4jGraphProjection,
        )

        session = _FakeSession()
        pipeline(tmp_path, projection=Neo4jGraphProjection(lambda: session)).run(
            repository_id=REPOSITORY, release_id=RELEASE
        )

        sweep = session.index("DELETE dependency")
        last_merge = session.index("MERGE (source)-[dependency", last=True)

        assert sweep > last_merge

    def test_a_re_run_replaces_its_own_edges_rather_than_adding_to_them(self, tmp_path):
        """Two runs leave two sets of edges on one pair of nodes. Nothing
        errors, the graph still draws, and every count read off it doubles -
        which is worse than a missing count because it looks like data."""

        from app.infrastructure.neo4j.validated_graph_projection import (
            SWEEP_STALE_EDGES,
        )

        assert "dependency.run_id <> $run_id" in SWEEP_STALE_EDGES
        assert "DELETE dependency" in SWEEP_STALE_EDGES

    def test_the_release_chain_is_ordered_by_the_key_and_never_by_the_tag(self):
        """Compared as text `v0.10.0` sorts before `v0.9.0`, and a backwards
        chain is how a superseded decision governs the release that replaced
        it."""

        from app.infrastructure.neo4j.validated_graph_projection import (
            LINK_PREVIOUS_RELEASE,
        )

        assert "release_sort_key" in LINK_PREVIOUS_RELEASE
        assert "release_id <" not in LINK_PREVIOUS_RELEASE


class TestTheRecordIsRebuildableFromTheFile:
    """What makes two degradable writes honest rather than careless."""

    def test_every_published_fact_can_be_found_in_the_document(self, published):
        """If the rows could not be rebuilt from the file, a store that was
        down during a run would be data loss and the write order would be
        wrong."""

        run, document, _ = published

        from_file = {
            (edge["fact_id"], edge["bucket"], edge["confidence"])
            for edge in document["links"]
        }
        from_run = {
            (fact.fact_id, str(fact.bucket), fact.confidence) for fact in run.facts
        }

        assert from_file == from_run

    def test_the_run_record_itself_is_in_the_document(self, published):
        run, document, _ = published
        graph = document["graph"]

        assert graph["run"]["run_id"] == run.run_id
        assert graph["repository_id"] == run.repository_id
        assert graph["validation_confidence"] == run.validation_confidence


# ---- doubles -------------------------------------------------------------


class _Raising:
    def assemble(self, *args, **kwargs):
        raise NotImplementedError


class _FailingPublisher:
    def publish(self, document):
        raise OSError("the artifacts directory is not writable")


class _FailingRecorder:
    def record(self, run, document):
        raise RuntimeError("could not connect to the database")


class _FailingProjection:
    def project(self, document):
        raise RuntimeError("the graph store refused the connection")


class _Recording:
    def __init__(self) -> None:
        self.calls = 0
        self.documents = []

    def record(self, run, document):
        self.calls += 1
        self.documents.append(document)

    def project(self, document):
        self.calls += 1
        self.documents.append(document)


class _FakeSession:
    """Records the Cypher it was handed, in order."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def run(self, statement, **_):
        self.statements.append(statement)
        return self

    def counts(self, fragment: str) -> int:
        return sum(1 for statement in self.statements if fragment in statement)

    def index(self, fragment: str, last: bool = False) -> int:
        found = [i for i, s in enumerate(self.statements) if fragment in s]
        assert found, f"no statement contains {fragment!r}"
        return found[-1] if last else found[0]


def _sized_document(unit, release="v0.10.0"):
    """A one-element document measuring size in `unit`, or not at all."""

    from datetime import datetime

    from app.domain.validated_architecture import (
        RunMode,
        ValidatedArchitectureGraph,
        ValidatedNode,
        ValidationRollup,
        ValidationRunStamp,
    )

    return ValidatedArchitectureGraph(
        repository_id=REPOSITORY,
        release_id=release,
        architecture_style="microservices",
        nodes=(
            ValidatedNode(
                "svc:a", "a", "service", ValidationRollup(),
                size=10.0 if unit else None, size_unit=unit,
            ),
        ),
        edges=(),
        stamp=ValidationRunStamp(
            run_id=f"run-{release}",
            generated_at=datetime(2026, 10, 19),
            mode=RunMode.RECONSTRUCTION,
            reasoner_model=None,
            verifier_model=None,
        ),
        validation_confidence=0.5,
    )


class TestTheReviewQueueIsNotInThePipeline:
    """M7's requirement, asserted where the document is: a queue that refuses
    costs the run nothing, and the proof is that the document does not change.

    A stage record saying `completed` proves nothing about whether the queue
    is on the critical path. Two identical documents do.
    """

    def run_with(self, root, queue):
        service = pipeline(root)
        service._review = ArchitectReviewService(queue, None)
        return service.run(repository_id=REPOSITORY, release_id=RELEASE)

    def test_a_queue_that_refuses_does_not_fail_the_run(self, tmp_path):
        result = self.run_with(tmp_path, _RefusingQueue())
        stage = next(s for s in result.stages if s.name == "architect_review")

        assert result.status == "completed"
        assert result.published_ref is not None
        assert any("review queue failed" in w for w in stage.warnings)
        assert stage.counts["needing_review"] > 0

    def test_the_published_document_is_identical_with_the_queue_broken(self, tmp_path):
        """The structural half. If the document differed, the queue would be
        in the pipeline whatever the stage record said."""

        working = self.run_with(tmp_path / "ok", _RecordingQueue())
        broken = self.run_with(tmp_path / "broken", _RefusingQueue())

        assert _without_run_identity(working) == _without_run_identity(broken)

    def test_an_unconfigured_queue_is_a_note_and_not_a_warning(self, tmp_path):
        result = self.run_with(tmp_path, None)
        stage = next(s for s in result.stages if s.name == "architect_review")

        assert stage.warnings == ()
        assert "no queue is configured" in (stage.note or "")

    def test_a_working_queue_takes_exactly_the_facts_routed_to_review(self, tmp_path):
        queue = _RecordingQueue()

        result = self.run_with(tmp_path, queue)
        stage = next(s for s in result.stages if s.name == "architect_review")
        reviewed = [f for f in result.facts if f.route == "review"]

        assert stage.counts["queued"] == len(reviewed)
        assert {i.fact_id for i in queue.items} == {f.fact_id for f in reviewed}


def _without_run_identity(result) -> dict:
    """The published document with the two fields that are a run's identity
    removed, since those differ between any two runs by design."""

    document = json.loads(Path(result.published_ref).read_text(encoding="utf-8"))
    document["graph"]["run"].pop("run_id")
    document["graph"]["run"].pop("generated_at")
    document["graph"]["summary"].pop("model_calls", None)
    return document


class _RecordingQueue:
    def __init__(self) -> None:
        self.items = []

    def enqueue(self, item):
        self.items.append(item)
        return item.item_id

    def get(self, item_id):
        return next((i for i in self.items if i.item_id == item_id), None)

    def pending(self):
        return list(self.items)

    def resolve(self, decision):
        return None


class _RefusingQueue:
    def enqueue(self, item):
        raise RuntimeError("no route to the database")

    def get(self, item_id):
        raise RuntimeError("no route to the database")

    def pending(self):
        raise RuntimeError("no route to the database")

    def resolve(self, decision):
        raise RuntimeError("no route to the database")
