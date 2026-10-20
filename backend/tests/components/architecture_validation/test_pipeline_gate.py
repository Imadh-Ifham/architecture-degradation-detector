"""The foundation phase gate: the pipeline runs end to end.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Runs a whole validation run with every subcomponent except normalisation
    behind a stub, and checks the wiring.

    This is the cheapest test in the project and the one with the best return.
    A pipeline that runs with its subcomponents stubbed proves the orchestration
    is correct *before* any logic exists that could hide a wiring bug - and
    once it passes, the eight subcomponents can be built in any order, because
    each one is dropped into a frame already known to work.

    It also pins the two behaviours the demo's claims rest on: that an
    uncovered fact reaches its bucket with **zero** model calls, and that a
    skipped stage says it was skipped rather than reporting a completed pass
    over nothing.

    The normalisation subcomponent is real here rather than stubbed, because it
    is built - so this doubles as the first end-to-end check of the recorded
    inventory fixtures.
"""

import ast
import inspect
import json
import re
import shutil
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from app.components.architecture_validation.architect_review import (
    ArchitectReviewService,
)
from app.infrastructure.validated_graph import ValidatedGraphFileStore
from app.components.architecture_validation.graph_publishing.models import (
    PublishedGraph,
)
from app.components.architecture_validation.classification import (
    ClassificationService,
    Route,
)
from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
    DecisionStageOutcome,
)
from app.components.architecture_validation.evidence_retrieval import (
    EvidenceRetrievalService,
)
from app.components.architecture_validation.evidence_retrieval._neighbourhood import (
    MAX_NEIGHBOURS,
)
from app.components.architecture_validation.graph_publishing import (
    GraphPublishingService,
)
from app.components.architecture_validation.independent_verification import (
    IndependentVerificationService,
)
from app.components.architecture_validation.independent_verification._prompt import (
    render as render_challenge,
)
from app.components.architecture_validation.independent_verification._prompt import (
    verification_schema,
)
from app.components.architecture_validation.models import (
    ArbiterAgreement,
    ArbiterCheck,
    ClassifiedFact,
    EvidencePackage,
    EvidenceRole,
    GuardFailure,
    Objection,
    ObjectionKind,
    PrimaryVerdict,
    Resolution,
    ScoreTrace,
    SourceTier,
    StageStatus,
    Verdict,
    VerdictSource,
    Verification,
    VerificationArm,
    VerificationMode,
    VerificationOutcome,
)
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.components.architecture_validation.pipeline import IMPLEMENTED_STAGES
from app.components.architecture_validation.service import (
    FACT_PRODUCING_STAGES,
    STAGE_ORDER,
    ArchitectureValidationService,
)
from app.components.architecture_validation.validation_reasoning import (
    ValidationReasoningService,
)
from app.components.architecture_validation.validation_reasoning._arbiter import decide
from app.components.architecture_validation.validation_reasoning._prompt import (
    render,
    verdict_schema,
)
from app.domain.recovered_architecture import (
    ArchitectureStyle,
    ElementKind,
    EvidenceQuality,
    RecoveredArchitecture,
    RecoveryProvenance,
    StyleSource,
)
from app.infrastructure.ai import (
    TASK_PRIMARY_VERDICT,
    TASK_PRIMARY_VERDICT_FALLBACK,
    TASK_PRIMARY_VERDICT_LOCAL,
    TASK_VERIFICATION,
    AISettings,
    ConfiguredAIClient,
    VerdictCache,
    capabilities_for,
    load_prompt,
)
from app.infrastructure.ai.providers.fake import FakeProvider
from app.infrastructure.ai.providers.openai_compatible import strictify
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.recovery_gateway.fixture_reader import (
    FixtureArchitectureReader,
)
from app.infrastructure.recovery_gateway.snapshot_file_reader import (
    SnapshotFileReader,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"
SUBJECT = FIXTURES / "subject"
SNAPSHOTS = Path(__file__).resolve().parents[3] / "data" / "snapshots"


class StubKnowledge:
    """Resolves the first fact and leaves every other one uncovered.

    One governing decision and the rest uncovered is the realistic shape for a
    repository with partial recorded intent, and it exercises both the
    reasoning path and the short-circuit in one run.
    """

    def __init__(self, resolve_first: bool = True) -> None:
        self.resolve_first = resolve_first
        self.calls = 0
        self.established = 0

    def establish(self, request, mode) -> DecisionStageOutcome:
        """Stand in for the stage's first half: collect, gate, append.

        A stub has to answer the same question the real one does, so the gate
        cannot be bypassed by not implementing it.
        """

        self.established += 1
        return DecisionStageOutcome(
            mode=mode,
            release_id=request.release_id,
            records=1,
            in_force=1,
            recorded=0,
            closed=0,
            unchanged=1,
            reconstructed=1,
        )

    def rules_without_facts(self, repository_id, release_id, facts):
        return ()

    def resolve(self, fact, repository_id) -> Resolution:
        self.calls += 1
        if self.resolve_first and self.calls == 1:
            return Resolution(governing=_decision(), candidates=("np-1",))
        return Resolution(governing=None, uncovered=True)


class StubEvidence:
    def __init__(self) -> None:
        self.calls = 0

    def assemble(self, fact, resolution, architecture) -> EvidencePackage:
        self.calls += 1
        return EvidencePackage(
            fact_id=fact.fact_id,
            subject=fact.subject.name,
            relationship=fact.relationship,
            object=fact.object.name,
            release_id=fact.release_id,
            evidence_hash="hash-1",
            items=(),
        )


class StubReasoning:
    def __init__(self) -> None:
        self.calls = 0
        self.arbiter_checks = []

    def judge(self, package, arbiter) -> PrimaryVerdict:
        self.calls += 1
        self.arbiter_checks.append(arbiter)
        return PrimaryVerdict(
            fact_id=package.fact_id,
            verdict=Verdict.CONFIRMS,
            reasoning="stub",
            cited_evidence_refs=("ev:1",),
            model_id="fake/deterministic-1",
            prompt_version="primary_verdict.v1",
            evidence_hash=package.evidence_hash,
            cached=False,
        )


class StubVerification:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, verdict, package) -> Verification:
        self.calls += 1
        return Verification(
            fact_id=verdict.fact_id,
            outcome=VerificationOutcome.AGREE,
            mechanism="critical-reframing",
            reasoning="stub",
            model_id="fake/verifier-1",
            prompt_version="critical_reframing.v1",
            cached=False,
        )


class StubClassification:
    def classify(self, fact, resolution, verdict, verification,
                 verification_mode=None) -> ClassifiedFact:
        reasoned = verdict is not None
        return ClassifiedFact(
            fact_id=fact.fact_id,
            bucket="confirmed" if reasoned else "uncovered",
            confidence=0.9 if reasoned else 0.0,
            score_trace=ScoreTrace(terms={}, total=0.9 if reasoned else 0.0),
            route="publish" if reasoned else "review",
            governing_decision=resolution.governing.decision_id if resolution.governing else None,
            source_tier=SourceTier.EXECUTABLE_CONFIG if reasoned else None,
            evidence_refs=("ev:1",) if reasoned else (),
            # The number the whole short-circuit claim rests on.
            model_calls=2 if reasoned else 0,
        )


class StubReview:
    def __init__(self) -> None:
        self.queued: list = []

    def enqueue(self, facts, repository_id="", release_id="") -> tuple[str, ...]:
        self.queued.extend(facts)
        return tuple(f"review-{index}" for index, _ in enumerate(facts))


class StubPublishing:
    def __init__(self) -> None:
        self.published = None

    def publish(self, run, architecture) -> PublishedGraph:
        self.published = run
        return PublishedGraph(
            reference=f"artifacts/validated/{run.release_id}.graph.json",
            stores=("file",),
        )


def _decision():
    from app.components.architecture_validation.models import (
        ConstraintKind,
        DecisionRecord,
        EvidenceStrength,
        ExtractionMethod,
    )

    return DecisionRecord(
        decision_id="np-checkoutservice",
        subject="checkoutservice",
        constraint=ConstraintKind.MAY_CALL,
        object="paymentservice",
        valid_from="v0.9.0",
        valid_to=None,
        source="config_scan",
        source_repository="online-boutique",
        source_tier=SourceTier.EXECUTABLE_CONFIG,
        source_strength=EvidenceStrength.AUTHORITATIVE,
        source_ref="kustomize/components/network-policies/network-policy-checkoutservice.yaml",
        extraction_method=ExtractionMethod.RECONSTRUCTED,
        extracted_at=datetime(2026, 10, 14),
    )


class WorkspaceReader:
    """Reads the committed subject fixture tree for one release."""

    def read_text(self, repository_id, release_id, path):
        return (SUBJECT / release_id / path).read_text(encoding="utf-8")

    def list_paths(self, repository_id, release_id, pattern):
        root = SUBJECT / release_id
        return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.glob(pattern))


def build(release="v0.10.0", resolve_first=True):
    """Assemble the pipeline with one real subcomponent and seven stubs."""

    stubs = {
        "knowledge": StubKnowledge(resolve_first=resolve_first),
        "evidence": StubEvidence(),
        "reasoning": StubReasoning(),
        "verification": StubVerification(),
        "classification": StubClassification(),
        "review": StubReview(),
        "publishing": StubPublishing(),
    }
    service = ArchitectureValidationService(
        architecture_reader=SnapshotFileReader(SNAPSHOTS),
        normalization=ObservationNormalizationService(),
        **stubs,
    )
    return service, stubs


class TestTheGate:
    """P0's exit condition."""

    def test_the_pipeline_runs_end_to_end_with_every_subcomponent_stubbed(self):
        service, _ = build()

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        assert result.status == "completed"
        assert [stage.name for stage in result.stages] == list(STAGE_ORDER)
        assert result.run_id
        assert result.published_ref == "artifacts/validated/v0.10.0.graph.json"

    def test_every_stage_reports_a_status_and_a_duration(self):
        service, _ = build()

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        for stage in result.stages:
            assert stage.status in set(StageStatus)
            assert stage.duration_ms >= 0

    def test_the_run_totals_its_model_calls(self):
        service, _ = build()

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        assert result.model_calls == sum(fact.model_calls for fact in result.facts)


class TestShortCircuit:
    """The behaviour two of the demo's claims rest on."""

    def test_an_uncovered_fact_reaches_its_bucket_with_zero_model_calls(self):
        service, stubs = build()

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        uncovered = [fact for fact in result.facts if fact.bucket == "uncovered"]
        assert uncovered, "the stub leaves every fact after the first uncovered"
        assert all(fact.model_calls == 0 for fact in uncovered)

    def test_reasoning_is_never_called_for_an_uncovered_fact(self):
        """The call does not happen, rather than happening and being discarded."""

        service, stubs = build()

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        reasoned = [fact for fact in result.facts if fact.bucket != "uncovered"]
        assert stubs["reasoning"].calls == len(reasoned)
        assert stubs["evidence"].calls == len(reasoned)

    def test_a_run_with_no_governing_decision_makes_no_model_calls_at_all(self):
        service, stubs = build(resolve_first=False)

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        assert result.model_calls == 0
        assert stubs["reasoning"].calls == 0
        assert stubs["verification"].calls == 0

    def test_a_stage_that_did_nothing_says_it_was_skipped(self):
        """Not completed-with-zero: a stage that had nothing to do is a
        different outcome from one that ran and found nothing."""

        service, _ = build(resolve_first=False)

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")
        stages = {stage.name: stage for stage in result.stages}

        assert stages["validation_reasoning"].status is StageStatus.SKIPPED
        assert "no fact had a governing decision" in stages["validation_reasoning"].note
        assert stages["independent_verification"].status is StageStatus.SKIPPED

    def test_facts_routed_for_review_are_queued(self):
        service, stubs = build()

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        assert len(stubs["review"].queued) == len(
            [fact for fact in result.facts if fact.route == "review"]
        )


class TestAgainstTheRecordedInventory:
    """The fixtures are recordings of the recovery component's own output."""

    @pytest.mark.parametrize("release", ["v0.9.0", "v0.10.0"])
    def test_the_recorded_inventory_translates_and_normalises(self, release):
        service, _ = build(release=release)

        result = service.run(repository_id="online-boutique", release_id=release)

        normalisation = result.stages[0]
        assert normalisation.status is StageStatus.COMPLETED
        assert normalisation.counts["facts"] > 0
        assert normalisation.counts["relationships"] > 0

    def test_the_recorded_inventory_carries_no_style_and_the_run_infers_it(self):
        """Recovery supplies no style field today, so the gateway reports its
        absence and the normaliser answers - labelled as its own answer, never
        as recovery's."""

        architecture = FixtureArchitectureReader(FIXTURES).read("online-boutique", "v0.10.0")

        assert architecture.style_source is StyleSource.INFERRED_BY_C2
        assert all(
            element.kind is ElementKind.SERVICE for element in architecture.elements
        )

        outcome = ObservationNormalizationService().normalise(architecture)

        assert outcome.style_resolved == ArchitectureStyle.MICROSERVICES
        assert outcome.style_source == StyleSource.INFERRED_BY_C2

    def test_the_inventory_itself_still_carries_no_element_relationships(self):
        """The finding this whole input layer exists for."""

        architecture = FixtureArchitectureReader(FIXTURES).read("online-boutique", "v0.10.0")

        assert architecture.has_element_relationships is False

    def test_the_new_release_adds_the_service_the_diff_showed(self):
        reader = FixtureArchitectureReader(FIXTURES)

        previous = {e.name for e in reader.read("online-boutique", "v0.9.0").elements}
        current = {e.name for e in reader.read("online-boutique", "v0.10.0").elements}

        assert current - previous == {"shoppingassistantservice"}

    def test_the_recorded_dependencies_match_the_real_manifests(self):
        """checkoutservice declares six, and they are the six in the manifest.

        Read off the recorded snapshot rather than produced here: the
        dependencies are recovery's to supply, and the recording is what the
        methodology sanctions while its extraction is unfinished.
        """

        architecture = SnapshotFileReader(SNAPSHOTS).read("online-boutique", "v0.10.0")

        outcome = ObservationNormalizationService().normalise(architecture)

        checkout = {
            fact.object.name
            for fact in outcome.facts
            if fact.subject.name == "checkoutservice"
        }
        assert checkout == {
            "productcatalogservice",
            "shippingservice",
            "paymentservice",
            "emailservice",
            "currencyservice",
            "cartservice",
        }

    def test_the_new_service_has_no_network_policy_covering_it(self):
        """The real governance gap the release diff exposed, as a test.

        v0.10.0 adds shoppingassistantservice. The network policy set did not
        change, and it holds a default-deny plus one policy per service - so
        the new service is governed by nothing.
        """

        policies = WorkspaceReader().list_paths(
            "online-boutique", "v0.10.0", "kustomize/components/network-policies/*.yaml"
        )

        assert any("deny-all" in path for path in policies)
        assert not any("shoppingassistant" in path for path in policies)


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


ARTIFACTS = Path(tempfile.mkdtemp(prefix="c2-gate-artifacts-"))
"""Where the gate's runs publish, which is not the project's artifacts tree.

A real file store rather than a stub, because M8 is built and the thing worth
asserting is that a run writes a document a consumer can load. Under the OS
temporary directory so a test run never touches the published artifacts of a
real one.
"""


def build_whole(release="v0.10.0"):
    """Assemble the pipeline from the real subcomponents, all eight of them.

    This is what the API wires today, so it is the configuration the run
    endpoint is actually exercised in. The knowledge model reads the recorded
    decision corpus, which is the same log a live run accumulates - read
    through the same port, so nothing here is a special case.

    It was called `build_unimplemented` while stages were still stubs, and the
    name stopped being true when M7 landed: every stage here is real, the two
    databases are simply not configured, and a stage that writes to a store it
    was not given reports that rather than failing.
    """

    return ArchitectureValidationService(
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


class TestStagesNotBuiltYet:
    """An eight-stage component has to be runnable before stage eight exists.

    **That premise has been served and is now spent**, and the class is kept
    with its name because the history is the point: for seven weeks these
    tests were the reason the component could be demonstrated at all while
    half of it was a stub. Every stage is now built, so what they assert has
    changed - a run completes - and the one property that must outlive the
    premise is kept alive by *constructing* the condition rather than waiting
    for one: `test_a_stage_that_did_not_run_says_so` injects a stage that
    raises, because the guarantee has to hold for the next person who adds
    one.
    """

    def test_a_run_now_completes_end_to_end(self):
        """What the class was built to make possible, arrived at.

        It asserted `incomplete` for seven weeks, which was the honest answer
        while a stage was a stub. Eight of eight are built, the two databases
        are simply not configured, and the run completes.
        """

        result = build_whole().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )

        assert result.status == "completed"
        assert [stage.name for stage in result.stages] == list(STAGE_ORDER)
        assert result.published_ref is not None

    def test_the_implemented_stage_still_reports_what_it_did(self):
        result = build_whole().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )
        stages = {stage.name: stage for stage in result.stages}
        normalisation = stages["observation_normalization"]

        assert normalisation.status is StageStatus.COMPLETED
        assert normalisation.counts["facts"] > 0

    def test_a_stage_that_did_not_run_says_so(self):
        """A stub reporting a completed pass is the one failure mode that
        makes the whole board worthless.

        There is no unimplemented stage left, so the condition is constructed:
        a reasoning stage that raises `NotImplementedError` is exactly what
        every stage looked like a week ago, and the guarantee has to hold for
        whoever adds the ninth.
        """

        service = build_whole()
        service._reasoning = _NotBuilt()

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")
        stages = {stage.name: stage for stage in result.stages}

        assert result.status == "incomplete"
        assert stages["validation_reasoning"].status is StageStatus.PENDING
        assert stages["validation_reasoning"].note == "not implemented yet"
        assert not any(stages["validation_reasoning"].counts.values())

    def test_a_run_with_no_model_reachable_costs_nothing_and_still_publishes(self):
        """It published nothing while M8 was unwritten, and the assertion has
        expired rather than been loosened.

        Publishing is gated on the six stages that produce facts, not on the
        run as a whole. The only stage still unbuilt is the review queue,
        which is downstream of every fact - so the document carries the whole
        release and withholding it would make M8 undemonstrable until M7
        exists, which is exactly what this component is built not to need.

        What it still asserts is the part that was always the point: a run
        with no model reachable costs nothing and says so.
        """

        result = build_whole().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )

        assert result.model_calls == 0
        assert result.status == "completed"
        assert result.published_ref is not None

    def test_a_subcomponent_that_breaks_is_not_reported_as_unbuilt(self):
        """Pending means nobody has written it. A stage that raises anything
        else has a defect, and hiding that in the same bucket would make the
        board lie."""

        class BrokenKnowledge(StubKnowledge):
            def resolve(self, fact, repository_id):
                raise ValueError("index is corrupt")

        service, stubs = build()
        service._knowledge = BrokenKnowledge()

        with pytest.raises(ValueError, match="index is corrupt"):
            service.run(repository_id="online-boutique", release_id="v0.10.0")

    def test_no_facts_means_no_stage_claims_to_have_completed(self):
        """Found by running the live wiring: recovery's inventory carries no
        dependencies yet, so normalisation produces nothing - and five stages
        that were never called were reporting themselves completed. A board of
        green stages over a run that validated nothing is the same lie as a
        stub reporting a completed pass."""

        empty = RecoveredArchitecture(
            repository_id="online-boutique",
            release_id="v0.10.0",
            style=ArchitectureStyle.MICROSERVICES,
            style_source=StyleSource.C1,
            elements=(),
            relationships=(),
            provenance=RecoveryProvenance("snapshot_file_reader", "1.0.0", "test"),
        )
        service, _ = build()
        service._architecture_reader = _Fixed(empty)

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")
        stages = {stage.name: stage for stage in result.stages}

        assert stages["observation_normalization"].status is StageStatus.COMPLETED
        for name in (
            "decision_knowledge",
            "evidence_retrieval",
            "validation_reasoning",
            "independent_verification",
            "classification",
        ):
            assert stages[name].status is StageStatus.SKIPPED, name
            assert stages[name].note

    def test_normalisation_says_recovery_supplied_no_dependencies(self):
        """The warning that tells a reader why the run was empty, rather than
        leaving them to infer it from a row of zeros."""

        architecture = SnapshotFileReader(SNAPSHOTS).read("online-boutique", "v0.10.0")
        stripped = replace(architecture, relationships=())

        outcome = ObservationNormalizationService().normalise(stripped)

        assert outcome.facts == ()
        assert any("no element-to-element dependencies" in w for w in outcome.warnings)


class _Fixed:
    """An architecture reader that returns one prepared architecture."""

    def __init__(self, architecture) -> None:
        self._architecture = architecture

    def read(self, repository_id, release_id):
        return self._architecture


class TestTheM1Gate:
    """The stage gate for M1, as one executable checklist.

    Every row of `01_TARGETED_ARCHITECTURE.md` §9 that does not depend on
    recovery's graph, asserted against the **recorded snapshot of recovery's
    real output** rather than against an invented architecture. Several of
    these are also covered in detail elsewhere; the point of having them here
    is that the checklist stops being a list somebody ticks and becomes a list
    the suite ticks.

    Two rows are deliberately absent and belong to O7: the statement count per
    read, and the element ceiling. Both need the graph reader, and recovery's
    graph does not exist yet.
    """

    RELEASES = ("v0.9.0", "v0.10.0")

    def outcome(self, release):
        from app.core.config import settings
        from app.infrastructure.recovery_gateway import SnapshotFileReader

        architecture = SnapshotFileReader(settings.snapshot_root).read(
            "online-boutique", release
        )
        return ObservationNormalizationService().normalise(architecture)

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_recorded_snapshot_normalises_completely(self, release):
        outcome = self.outcome(release)

        assert len(outcome.facts) == len(outcome.architecture.relationships)
        assert outcome.relationship_count == len(outcome.architecture.relationships)

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_fact_carries_an_orderable_release_key(self, release):
        outcome = self.outcome(release)

        assert outcome.release_sort_key
        assert all(fact.release_sort_key == outcome.release_sort_key for fact in outcome.facts)

    def test_the_two_demonstration_releases_order_correctly(self):
        assert self.outcome("v0.10.0").release_sort_key > self.outcome("v0.9.0").release_sort_key

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_fact_says_whose_answer_the_style_was(self, release):
        outcome = self.outcome(release)

        assert outcome.style_source == StyleSource.INFERRED_BY_C2
        assert all(fact.style_source == outcome.style_source for fact in outcome.facts)

    @pytest.mark.parametrize("release", RELEASES)
    def test_no_identity_collision_and_nothing_merged(self, release):
        outcome = self.outcome(release)

        assert outcome.identity_collisions == ()
        assert outcome.merged_fact_count == 0

    @pytest.mark.parametrize("release", RELEASES)
    def test_no_relationship_label_was_absorbed(self, release):
        outcome = self.outcome(release)

        assert outcome.absorbed_labels == ()

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_fact_keeps_the_original_label_beside_the_canonical_one(self, release):
        outcome = self.outcome(release)

        assert all(fact.attributes.get("observed_as") for fact in outcome.facts)

    @pytest.mark.parametrize("release", RELEASES)
    def test_no_directory_group_became_an_element(self, release):
        """A directory can never be governed by an architectural decision, so
        counting one as an element would count it as ungoverned - inflating the
        single number that is easiest to misread."""

        outcome = self.outcome(release)

        assert all(
            element.kind in (ElementKind.SERVICE, ElementKind.MODULE)
            for element in outcome.architecture.elements
        )

    @pytest.mark.parametrize("release", RELEASES)
    def test_an_inferred_input_stays_marked_inferred(self, release):
        """*"We do not accuse on inferred structure"* has to be true in code.

        The recording holds elements recovery only inferred, and the quality of
        the facts touching them has to still say so by the time classification
        sees them - that is what the confidence ceiling is applied to.
        """

        outcome = self.outcome(release)
        inferred = {
            element.id
            for element in outcome.architecture.elements
            if element.quality is EvidenceQuality.INFERRED
        }

        assert inferred, f"{release} has no inferred elements; this test proves nothing"

        qualities = {str(fact.quality) for fact in outcome.facts}
        assert qualities <= {"confirmed", "inferred"}
        assert all(fact.quality for fact in outcome.facts)

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_same_release_normalised_twice_gives_identical_ids(self, release):
        """Content addressing. Two runs can be compared without matching on
        position, which a counter could never support - and it is also what
        makes a re-run after a failure free rather than merely fast."""

        first, again = self.outcome(release), self.outcome(release)

        assert [fact.fact_id for fact in first.facts] == [
            fact.fact_id for fact in again.facts
        ]

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_fact_is_traceable_back_to_the_input(self, release):
        """The row-to-edge link the screen needs. A fact whose ends cannot be
        found in the snapshot it came from could not be drawn on it."""

        outcome = self.outcome(release)
        known = {element.id for element in outcome.architecture.elements}

        for fact in outcome.facts:
            assert fact.subject.id in known
            assert fact.object.id in known
            assert fact.subject.canonical and fact.object.canonical
            assert fact.subject.name and fact.object.name

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_input_is_returned_beside_the_output(self, release):
        """So the before and the after can be shown together, which is the
        clearest thing this subcomponent has to put on a screen."""

        outcome = self.outcome(release)

        assert outcome.architecture.release_id == release
        assert outcome.architecture.elements

    def test_the_dependency_stand_in_is_gone(self):
        """The last row of the checklist, and the only one about where a file
        is rather than what it does. Recovery ships its own element-to-element
        dependencies now, so the module that derived them is deleted."""

        from pathlib import Path

        stand_in = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "infrastructure"
            / "recovery_gateway"
            / "c1_dependency_stand_in.py"
        )

        assert not stand_in.exists()

class TestTheM2Gate:
    """The stage gate for M2, as one executable checklist.

    Every row of `03_decision_knowledge/01_TARGETED_ARCHITECTURE.md` §9,
    asserted over **both** committed releases and against the recorded
    decision corpus rather than an invented one. Most are covered in detail in
    `test_decision_sources.py`, `test_decision_knowledge.py` and
    `test_supersession.py`; the point of repeating them here is that the
    checklist stops being a list somebody ticks and becomes one the suite
    ticks.

    No row of it is deferred. M2 needs nothing recovery has not already
    shipped.
    """

    RELEASES = ("v0.9.0", "v0.10.0")
    REPOSITORY = "online-boutique"

    def service(self, store=None):
        from app.infrastructure.decision_log import JsonlDecisionStore

        return DecisionKnowledgeService(
            WorkspaceReader(), store or JsonlDecisionStore(FIXTURES / "decisions")
        )

    def request_for(self, release):
        from datetime import UTC, datetime

        from app.components.architecture_validation.decision_knowledge import (
            SourceRequest,
        )
        from app.infrastructure.recovery_gateway import SnapshotFileReader

        architecture = SnapshotFileReader(SNAPSHOTS).read(self.REPOSITORY, release)
        return SourceRequest(
            code_repository_id=self.REPOSITORY,
            release_id=release,
            extracted_at=datetime(2026, 10, 15, 9, 0, tzinfo=UTC),
            manifest_paths=architecture.manifest_paths,
        )

    def facts(self, release):
        from app.infrastructure.recovery_gateway import SnapshotFileReader

        architecture = SnapshotFileReader(SNAPSHOTS).read(self.REPOSITORY, release)
        return ObservationNormalizationService().normalise(architecture).facts

    # ---- the boundary ----

    def test_the_subcomponent_cannot_reach_the_filesystem(self):
        """Asserted per module in the architecture-rules suite. Repeated here
        as a row of the checklist, because it is the one that stops this unit
        doing recovery's job the way M1's did."""

        from pathlib import Path

        component = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "components"
            / "architecture_validation"
            / "decision_knowledge"
        )

        for module in component.rglob("*.py"):
            body = module.read_text(encoding="utf-8")
            for forbidden in ("open(", "Path(", "pathlib", "json.dump"):
                assert forbidden not in body, f"{module.name} names {forbidden}"

    def test_the_pipeline_is_the_eight_stages_the_proposal_describes(self):
        from app.components.architecture_validation import PIPELINE

        assert len(PIPELINE) == 8
        assert "decision_knowledge" in IMPLEMENTED_STAGES

    # ---- what the sources find ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_scan_reconstructs_the_whole_policy_set(self, release):
        from app.components.architecture_validation.decision_knowledge.sources import (
            ConfigurationScan,
        )
        from app.components.architecture_validation.models import ConstraintKind

        records = ConfigurationScan(WorkspaceReader()).collect(
            self.request_for(release)
        ).records
        kinds = {}
        for record in records:
            kinds[record.constraint] = kinds.get(record.constraint, 0) + 1

        assert kinds[ConstraintKind.MAY_CALL] == 17
        assert kinds[ConstraintKind.MUST_NOT_CALL] == 1
        assert kinds[ConstraintKind.DECLARED_RPC] == 7

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_record_can_be_pointed_at(self, release):
        from app.components.architecture_validation.decision_knowledge.sources import (
            ConfigurationScan,
        )

        for record in ConfigurationScan(WorkspaceReader()).collect(
            self.request_for(release)
        ).records:
            assert (SUBJECT / release / record.source_ref).exists()

    @pytest.mark.parametrize("release", RELEASES)
    def test_tier_one_runs_and_reports_nothing_found(self, release):
        available = self.service().availability(self.request_for(release))

        assert available["repo_adr"].ran is True
        assert available["repo_adr"].records == 0
        assert available["repo_adr"].reason
        assert available["external_adr"].ran is False

    # ---- the log ----

    def test_a_rule_that_vanishes_has_its_interval_closed(self, tmp_path):
        from app.infrastructure.decision_log import JsonlDecisionStore

        service = self.service(JsonlDecisionStore(tmp_path))
        for release in self.RELEASES:
            service.establish(self.request_for(release), "combined")

        overlay = service.history(self.REPOSITORY).versions_of(
            "*", "must_call_via", "kustomize/components/service-accounts"
        )

        assert overlay[0].valid_from == "v0.9.0"
        assert overlay[0].valid_to == "v0.10.0"

    def test_appending_the_same_scan_twice_leaves_the_log_unchanged(self, tmp_path):
        from app.infrastructure.decision_log import JsonlDecisionStore

        store = JsonlDecisionStore(tmp_path)
        service = self.service(store)
        service.establish(self.request_for("v0.10.0"), "combined")
        before = store.replay(self.REPOSITORY)

        service.establish(self.request_for("v0.10.0"), "combined")

        assert store.replay(self.REPOSITORY) == before

    def test_replaying_the_log_twice_gives_the_same_state(self):
        service = self.service()

        assert (
            service.history(self.REPOSITORY).versions
            == service.history(self.REPOSITORY).versions
        )

    def test_the_committed_corpus_still_reproduces(self, tmp_path):
        """A fixture that has drifted from the code is worse than no fixture:
        every test over it passes and none of them mean anything."""


        from app.infrastructure.decision_log import JsonlDecisionStore

        store = JsonlDecisionStore(tmp_path)
        service = self.service(store)
        for release in self.RELEASES:
            service.establish(self.request_for(release), "combined")

        recorded = [
            json.loads(line)
            for line in (FIXTURES / "decisions" / "online-boutique.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]

        assert store.replay(self.REPOSITORY) == recorded

    # ---- the resolver ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_observed_dependency_is_governed(self, release):
        from app.components.architecture_validation.models import ConstraintKind

        service = self.service()
        resolutions = [
            service.resolve(fact, self.REPOSITORY) for fact in self.facts(release)
        ]

        assert len(resolutions) == 15
        assert all(r.governing is not None for r in resolutions)
        assert all(
            r.governing.constraint is ConstraintKind.MAY_CALL for r in resolutions
        )

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_three_outcomes_are_mutually_exclusive(self, release):
        service = self.service()

        for fact in self.facts(release):
            resolution = service.resolve(fact, self.REPOSITORY)
            answered = [
                resolution.governing is not None,
                resolution.uncovered,
                resolution.ambiguous,
            ]
            assert answered.count(True) == 1

    def test_the_identity_rule_in_force_differs_between_the_releases(self):
        index = self.service().history(self.REPOSITORY)
        shared = index.versions_of(
            "*", "must_call_via", "kustomize/components/service-accounts"
        )
        inline = index.versions_of(
            "*", "must_call_via", "inline ServiceAccount beside the workload"
        )

        assert shared[0].covers("v0.9.0") and not shared[0].covers("v0.10.0")
        assert inline[0].covers("v0.10.0") and not inline[0].covers("v0.9.0")

    # ---- the gate ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_an_empty_mode_refuses_the_run_and_names_the_yields(self, release):
        from app.components.architecture_validation.decision_knowledge import (
            NoDecisionsAvailable,
        )

        with pytest.raises(NoDecisionsAvailable) as refused:
            self.service().establish(self.request_for(release), "repo_adr")

        assert refused.value.yields == {
            "repo_adr": 0,
            "external_adr": 0,
            "combined": 26,
        }

    def test_a_chosen_mode_that_yields_nothing_scans_nothing(self, tmp_path):
        from app.components.architecture_validation.decision_knowledge import (
            NoDecisionsAvailable,
        )
        from app.infrastructure.decision_log import JsonlDecisionStore

        store = JsonlDecisionStore(tmp_path)

        with pytest.raises(NoDecisionsAvailable):
            self.service(store).establish(self.request_for("v0.10.0"), "repo_adr")

        assert store.replay(self.REPOSITORY) == []

    # ---- what the run reports ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_stage_reports_what_rests_on_what(self, release, tmp_path):
        """On this repository nothing was declared and everything was
        reconstructed, which is the finding the whole design answers.

        Against its own store, because `establish` writes. A test that
        appends to the committed corpus would leave the next test reading a
        history this one invented - which is exactly what happened the first
        time this was written.
        """

        from app.infrastructure.decision_log import JsonlDecisionStore

        service = self.service(JsonlDecisionStore(tmp_path))
        outcome = service.establish(self.request_for(release), "combined")

        assert outcome.declared == 0
        assert outcome.reconstructed == 26
        assert outcome.in_force == 26

    def test_running_against_the_recorded_corpus_writes_nothing(self):
        """Both releases are already in it, so the pipeline re-reading them is
        a no-op. That is what makes the corpus usable as a fixture *and* what
        proves a re-run of a failed validation changes no history."""

        corpus = FIXTURES / "decisions" / "online-boutique.jsonl"
        before = corpus.read_bytes()

        service = self.service()
        for release in self.RELEASES:
            service.establish(self.request_for(release), "combined")

        assert corpus.read_bytes() == before

    @pytest.mark.parametrize("release", RELEASES)
    def test_a_rule_with_no_observed_dependency_is_counted(self, release):
        """One permission exists for a dependency recovery never reported. A
        finding about the architecture, so it is named rather than dropped."""

        unmatched = self.service().rules_without_facts(
            self.REPOSITORY, release, self.facts(release)
        )

        assert unmatched == ("rule-cartservice-redis",)

class TestTheM3Gate:
    """The stage gate for M3, as one executable checklist.

    Every row of `04_evidence_retrieval/01_TARGETED_ARCHITECTURE.md` §9,
    asserted over **both** committed releases and against the recorded
    decision corpus. Most are covered in detail in
    `test_evidence_retrieval.py`; the point of repeating them here is that
    the checklist stops being a list somebody ticks and becomes one the suite
    ticks.

    This unit is the fence around the model, so two of these rows matter more
    than the others: that `refs` is exactly the item set, because it is the
    universe the citation guard checks against, and that the hash is both
    stable and sensitive, because it is the cache key and either failure is
    silent.
    """

    RELEASES = ("v0.9.0", "v0.10.0")
    REPOSITORY = "online-boutique"

    def knowledge(self):
        from app.components.architecture_validation.decision_knowledge import (
            DecisionKnowledgeService,
        )
        from app.infrastructure.decision_log import JsonlDecisionStore

        return DecisionKnowledgeService(
            WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
        )

    def evidence(self):
        from app.components.architecture_validation.evidence_retrieval import (
            EvidenceRetrievalService,
        )

        return EvidenceRetrievalService(WorkspaceReader())

    def architecture(self, release):
        return SnapshotFileReader(SNAPSHOTS).read(self.REPOSITORY, release)

    def packages(self, release):
        """Every package one release produces, through the real pipeline."""

        architecture = self.architecture(release)
        facts = ObservationNormalizationService().normalise(architecture).facts
        store, evidence = self.knowledge(), self.evidence()

        return [
            evidence.assemble(
                fact, store.resolve(fact, self.REPOSITORY), architecture
            )
            for fact in facts
        ]

    # ---- the boundary ----

    def test_the_subcomponent_cannot_reach_the_filesystem(self):
        """It quotes lines out of a repository and may not open one. The
        reading happens in an adapter, behind the port M2's sources already
        read through."""

        from pathlib import Path

        component = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "components"
            / "architecture_validation"
            / "evidence_retrieval"
        )

        for module in component.rglob("*.py"):
            body = module.read_text(encoding="utf-8")
            for forbidden in ("open(", "Path(", "pathlib", "os.path"):
                assert forbidden not in body, f"{module.name} names {forbidden}"

    def test_no_module_names_a_model_a_provider_or_a_prompt(self):
        """The fence cannot be built by the thing it fences. This unit decides
        what a model may see and must not know which model that is."""

        from pathlib import Path

        component = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "components"
            / "architecture_validation"
            / "evidence_retrieval"
        )

        for module in component.rglob("*.py"):
            body = module.read_text(encoding="utf-8").lower()
            for forbidden in ("anthropic", "openai", "gpt", "prompt_version", "AIClient"):
                assert forbidden.lower() not in body, (
                    f"{module.name} names {forbidden}"
                )

    # ---- what a citation can be checked against ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_item_is_citable_and_refs_is_exactly_the_item_set(self, release):
        """`refs` is the universe of legal citations. If an item had no
        reference the model could not cite it; if two shared one, a citation
        would be ambiguous - and the guard's answer would mean nothing."""

        for package in self.packages(release):
            assert all(item.ref for item in package.items)
            assert len(package.refs) == len(package.items)

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_package_names_the_fact_it_is_for(self, release):
        architecture = self.architecture(release)
        facts = ObservationNormalizationService().normalise(architecture).facts

        for fact, package in zip(facts, self.packages(release)):
            assert package.fact_id == fact.fact_id

    # ---- what can be shown to a person ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_a_quoted_item_is_exactly_the_lines_its_span_names(self, release):
        """Not a paraphrase, and not the whole file. The three lines of an
        item are the rule, its location, and the quote - and the quote has to
        be what is actually there."""

        for package in self.packages(release):
            for item in package.items:
                if item.span is None:
                    continue
                document = (
                    (SUBJECT / release / item.span.path)
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                quoted = document[item.span.start_line - 1 : item.span.end_line]

                assert item.text.splitlines()[2:] == quoted

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_span_resolves_to_a_line_the_file_actually_has(self, release):
        for package in self.packages(release):
            for item in package.items:
                if item.span is None:
                    continue
                located = SUBJECT / release / item.span.path

                assert located.exists()
                assert item.span.end_line <= len(
                    located.read_text(encoding="utf-8").splitlines()
                )

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_rule_is_always_the_first_item_and_always_present(self, release):
        """A verdict can rest on the rule alone, so it is kept longest and
        read first."""

        for package in self.packages(release):
            assert package.items[0].role is EvidenceRole.RULE

    # ---- the size of a question ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_neighbourhood_is_one_hop_and_never_exceeds_eight(self, release):
        for package in self.packages(release):
            context = [
                item
                for item in package.items
                if item.role is EvidenceRole.STRUCTURAL_CONTEXT
            ]

            assert len(context) <= MAX_NEIGHBOURS

    @pytest.mark.parametrize("release", RELEASES)
    def test_no_package_is_truncated_at_the_default_budget(self, release):
        """If the default budget were already biting, every verdict in the
        demonstration would rest on a weakened question."""

        for package in self.packages(release):
            assert package.truncated is False
            assert package.dropped_roles == ()

    def test_a_package_over_its_budget_keeps_the_rule_and_says_what_it_lost(self):
        fact = ObservationNormalizationService().normalise(
            self.architecture("v0.10.0")
        ).facts[0]
        resolution = self.knowledge().resolve(fact, self.REPOSITORY)

        package = self.evidence().assemble(
            fact, resolution, self.architecture("v0.10.0"), budget=1
        )

        assert package.truncated is True
        assert package.items[0].role is EvidenceRole.RULE
        assert EvidenceRole.STRUCTURAL_CONTEXT in package.dropped_roles

    # ---- the cache key ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_same_release_assembles_identically_twice(self, release):
        """Items, order and hashes. An order that varied between runs would
        miss the verdict cache without saying so."""

        first = self.packages(release)
        again = self.packages(release)

        assert [[item.ref for item in p.items] for p in first] == [
            [item.ref for item in p.items] for p in again
        ]
        assert [p.evidence_hash for p in first] == [p.evidence_hash for p in again]

    @pytest.mark.parametrize("release", RELEASES)
    def test_fifteen_facts_are_fifteen_distinct_questions(self, release):
        """If two facts hashed alike, one would be answered with the other's
        cached verdict - and nothing in the output would say so."""

        packages = self.packages(release)

        assert len(packages) == 15
        assert len({package.evidence_hash for package in packages}) == 15

    def test_the_two_releases_ask_different_questions_about_the_same_pairs(self):
        """The release is part of the question. Otherwise a verdict about
        v0.9.0 would be served from v0.10.0's cache, and the whole temporal
        claim would be answered once and reused."""

        earlier = {package.evidence_hash for package in self.packages("v0.9.0")}
        later = {package.evidence_hash for package in self.packages("v0.10.0")}

        assert not earlier & later


def _rule_ref(prompt: str) -> str:
    """The reference of the rule item in a rendered prompt.

    Falls back to a reference that exists nowhere, so a package rendered
    without a rule is caught by Guard B rather than quietly accepted.
    """

    for line in prompt.splitlines():
        if line.startswith("[") and line.endswith("] rule"):
            return line[1:].split("]")[0]
    return "ADR-999"


class CitingProvider(FakeProvider):
    """A fake that cites the rule it was actually shown.

    One canned answer resolves for exactly one of the fifteen packages, which
    would make a corpus-wide gate a statement about a single fact. Reading the
    reference out of the prompt is the least a model has to do to get past
    Guard B, and it makes the run below fifteen real questions.
    """

    def complete(
        self,
        model_id: str,
        prompt: str,
        schema: dict,
        strict: bool = True,
        temperature: float = 0.0,
        seed: int | None = 42,
    ) -> dict:
        self._responses = {
            "reasoning": "the rule in this package names the dependency",
            "cited_evidence_refs": [_rule_ref(prompt)],
            "verdict": "confirms",
        }
        return super().complete(model_id, prompt, schema, strict, temperature, seed)


class TestTheM4Gate:
    """The stage gate for M4, as one executable checklist.

    Every row of `05_validation_reasoning/01_TARGETED_ARCHITECTURE.md` §9,
    asserted over **both** committed releases, beside the gates for M1, M2 and
    M3. Most rows are covered in detail in `test_validation_reasoning.py`; the
    point of repeating them here is that the checklist stops being a list
    somebody ticks and becomes one the suite ticks.

    Two rows carry more weight than the rest, and both are about a check that
    did not happen looking like one that passed. A phantom citation is
    perfectly schema-valid, so Guard B is the entire grounding guarantee. And
    a verdict the deterministic table produced on its own is a real verdict
    with no model behind it - if that is not badged, a run with a dead key is
    indistinguishable from a successful one.
    """

    RELEASES = ("v0.9.0", "v0.10.0")
    REPOSITORY = "online-boutique"
    TASKS = (
        TASK_PRIMARY_VERDICT,
        TASK_PRIMARY_VERDICT_FALLBACK,
        TASK_PRIMARY_VERDICT_LOCAL,
    )

    # ---- the pieces, wired the way the composition root wires them ----

    def template(self):
        return load_prompt("primary_verdict.v1.md")

    def reasoner(self, provider, cache=None):
        settings = AISettings(ai_api_key="not-a-real-key")
        client = ConfiguredAIClient(
            provider,
            settings=settings,
            cache=cache or VerdictCache("unused", enabled=False),
        )
        return ValidationReasoningService(
            client, self.template(), self.TASKS, provider="fake"
        )

    def pipeline(self, provider, cache=None):
        """The real first four stages, with the four after them stubbed.

        Which is what makes this a gate on M4 rather than on the whole
        component: every fact of a release reaches the reasoner, and nothing
        downstream of it is real enough to hide a mistake.
        """

        return ArchitectureValidationService(
            architecture_reader=SnapshotFileReader(SNAPSHOTS),
            normalization=ObservationNormalizationService(),
            knowledge=DecisionKnowledgeService(
                WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
            ),
            evidence=EvidenceRetrievalService(WorkspaceReader()),
            reasoning=self.reasoner(provider, cache),
            verification=StubVerification(),
            classification=StubClassification(),
            review=StubReview(),
            publishing=StubPublishing(),
        )

    def architecture(self, release):
        return SnapshotFileReader(SNAPSHOTS).read(self.REPOSITORY, release)

    def governed(self, release):
        """Every fact of one release with the decision that governs it."""

        architecture = self.architecture(release)
        facts = ObservationNormalizationService().normalise(architecture).facts
        store = DecisionKnowledgeService(
            WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
        )
        for fact in facts:
            resolution = store.resolve(fact, self.REPOSITORY)
            if resolution.governing is not None:
                yield fact, resolution

    def packages(self, release):
        architecture = self.architecture(release)
        evidence = EvidenceRetrievalService(WorkspaceReader())
        return [
            evidence.assemble(fact, resolution, architecture)
            for fact, resolution in self.governed(release)
        ]

    def stage(self, result, name="validation_reasoning"):
        return next(stage for stage in result.stages if stage.name == name)

    # ---- the boundary ----

    def test_the_subcomponent_names_no_model_no_provider_and_no_key(self):
        """It asks for a task and hands over a schema. The moment one of these
        words appears in it, it has started choosing a model or reaching for a
        credential."""

        folder = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "components"
            / "architecture_validation"
            / "validation_reasoning"
        )

        for module in folder.rglob("*.py"):
            body = module.read_text(encoding="utf-8").lower()
            for forbidden in ("httpx", "openai", "groq", "ai_api_key", "open("):
                assert forbidden not in body, f"{module.name} names {forbidden}"

    # ---- the question the model is asked ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_item_reaches_the_prompt_with_its_reference(self, release):
        """A model cites what it can name, so an item rendered without its
        reference may as well not be in the package."""

        template = self.template()
        for package in self.packages(release):
            rendered = render(template, package)
            for item in package.items:
                assert item.ref in rendered
                assert item.text.splitlines()[0] in rendered

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_prompt_never_carries_the_arbiters_answer(self, release):
        """Tell the model what the table decided and it agrees with it: the
        agreement rate goes to a hundred per cent, every measured number
        improves, and the only uncorrelated check in the component is gone."""

        template = self.template()
        for package in self.packages(release):
            rendered = render(template, package).lower()
            assert "arbiter" not in rendered
            assert "basis" not in rendered

    def test_the_renderer_takes_the_template_and_the_package_and_nothing_else(self):
        assert list(inspect.signature(render).parameters) == ["template", "package"]

    def test_the_schema_puts_the_reasoning_and_the_citations_first(self):
        """Constrained decoding fills the fields in declaration order, so this
        is what makes the verdict conditioned on the reasoning rather than
        defended by it afterwards."""

        properties = list(strictify(verdict_schema())["properties"])

        assert properties.index("reasoning") < properties.index("verdict")
        assert properties.index("cited_evidence_refs") < properties.index("verdict")
        assert strictify(verdict_schema())["required"] == properties

    # ---- what a guard refuses ----

    def test_a_citation_outside_the_package_is_refused_retried_and_degraded(self):
        """The most important row in this gate. `["ADR-999"]` is perfectly
        schema-valid, and nothing but this comparison can say it refers to
        nothing."""

        package = self.packages("v0.10.0")[0]
        phantom = {
            "reasoning": "ADR-999 forbids this",
            "cited_evidence_refs": ["ADR-999"],
            "verdict": "contradicts",
        }
        ai = FakeProvider([phantom, phantom])

        verdict = self.reasoner(ai).judge(
            package, ArbiterCheck(Verdict.CONFIRMS, "named as permitted")
        )

        assert verdict.verdict is Verdict.INSUFFICIENT_EVIDENCE
        assert verdict.verdict is not Verdict.CONTRADICTS
        assert GuardFailure.UNRESOLVED_CITATION in verdict.guard_failures
        assert verdict.retried is True
        assert ai.call_count == 2

    def test_a_malformed_answer_twice_never_becomes_a_verdict(self):
        package = self.packages("v0.10.0")[0]

        verdict = self.reasoner(FakeProvider(malformed_times=2)).judge(
            package, ArbiterCheck(Verdict.CONFIRMS, "named as permitted")
        )

        assert verdict.verdict is Verdict.INSUFFICIENT_EVIDENCE
        assert GuardFailure.MALFORMED in verdict.guard_failures

    def test_a_conclusion_resting_only_on_context_is_refused(self):
        package = next(
            p
            for p in self.packages("v0.10.0")
            if any(i.role is EvidenceRole.STRUCTURAL_CONTEXT for i in p.items)
        )
        neighbour = next(
            item.ref
            for item in package.items
            if item.role is EvidenceRole.STRUCTURAL_CONTEXT
        )
        answer = {
            "reasoning": "its neighbours look reasonable",
            "cited_evidence_refs": [neighbour],
            "verdict": "confirms",
        }

        verdict = self.reasoner(FakeProvider([answer, answer])).judge(
            package, ArbiterCheck(Verdict.CONFIRMS, "named as permitted")
        )

        assert verdict.verdict is Verdict.INSUFFICIENT_EVIDENCE
        assert GuardFailure.CONTEXT_ONLY_CITATION in verdict.guard_failures

    def test_a_verdict_resting_on_the_replaced_decision_is_refused(self):
        """The decision the resolver considered and correctly rejected is in
        the package as context. A verdict resting on it would be the single
        most embarrassing output this component could produce, and it would
        look entirely normal."""

        fact, resolution = next(self.governed("v0.10.0"))
        with_supersession = Resolution(
            governing=resolution.governing,
            superseded_ancestor="sa-shared-component",
            superseded=_superseded_record(),
        )
        package = EvidenceRetrievalService(WorkspaceReader()).assemble(
            fact, with_supersession, self.architecture("v0.10.0")
        )
        answer = {
            "reasoning": "sa-shared-component settles it",
            "cited_evidence_refs": ["sa-shared-component"],
            "verdict": "confirms",
        }

        verdict = self.reasoner(FakeProvider([answer, answer])).judge(
            package, ArbiterCheck(Verdict.CONFIRMS, "named as permitted")
        )

        assert verdict.verdict is Verdict.INSUFFICIENT_EVIDENCE
        assert GuardFailure.SUPERSEDED_AS_GOVERNING in verdict.guard_failures

    # ---- the three judges, over the whole corpus ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_arbiter_decides_or_abstains_for_every_governed_fact(self, release):
        """With a basis either way. An abstention with no reason would be a
        fact nothing checked, reported as though something had."""

        for fact, resolution in self.governed(release):
            check = decide(fact, resolution.governing)

            assert check.basis
            assert check.verdict in (None, Verdict.CONFIRMS, Verdict.CONTRADICTS)

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_verdict_of_a_whole_release_carries_its_provenance(self, release):
        """Two runs on two providers, or one strict and one best-effort, are
        not the same experiment - and provenance cannot be added to results
        that already exist."""

        reasoner = self.reasoner(CitingProvider())

        for fact, resolution in self.governed(release):
            package = EvidenceRetrievalService(WorkspaceReader()).assemble(
                fact, resolution, self.architecture(release)
            )
            verdict = reasoner.judge(package, decide(fact, resolution.governing))

            assert verdict.verdict is Verdict.CONFIRMS
            assert verdict.model_id and verdict.provider and verdict.prompt_version
            assert verdict.schema_mode == "strict"
            assert verdict.evidence_hash == package.evidence_hash
            assert verdict.produced_by is VerdictSource.MODEL
            assert verdict.arbiter_agreement is ArbiterAgreement.AGREED

    def test_a_model_disagreeing_with_a_decided_table_publishes_both(self):
        package = self.packages("v0.10.0")[0]
        mechanical = ArbiterCheck(Verdict.CONTRADICTS, "nothing names this pair")

        verdict = self.reasoner(CitingProvider()).judge(package, mechanical)

        assert verdict.verdict is Verdict.CONFIRMS
        assert verdict.arbiter_agreement is ArbiterAgreement.DISAGREED
        assert verdict.arbiter.basis in verdict.disagreement_note

    def test_a_fact_the_table_abstained_on_says_so_rather_than_agreeing(self):
        package = self.packages("v0.10.0")[0]

        verdict = self.reasoner(CitingProvider()).judge(
            package, ArbiterCheck(None, "the pair was inferred from prose")
        )

        assert verdict.arbiter_agreement is ArbiterAgreement.NOT_CHECKED

    def test_a_dead_provider_still_produces_a_badged_verdict(self):
        package = self.packages("v0.10.0")[0]

        verdict = self.reasoner(FakeProvider(fail_times=99)).judge(
            package, ArbiterCheck(Verdict.CONFIRMS, "named as permitted")
        )

        assert verdict.verdict is Verdict.CONFIRMS
        assert verdict.produced_by is VerdictSource.ARBITER
        assert verdict.model_id == "none"
        assert verdict.ladder_rung == 5

    def test_the_ladder_is_bounded_and_a_guard_failure_never_changes_model(self):
        package = self.packages("v0.10.0")[0]
        check = ArbiterCheck(Verdict.CONFIRMS, "named as permitted")

        unreachable = FakeProvider(fail_times=99)
        self.reasoner(unreachable).judge(package, check)

        phantom = {
            "reasoning": "ADR-999",
            "cited_evidence_refs": ["ADR-999"],
            "verdict": "confirms",
        }
        rejected = FakeProvider([phantom] * 4)
        self.reasoner(rejected).judge(package, check)

        assert unreachable.call_count <= 4
        assert len({call["model_id"] for call in rejected.calls}) == 1

    # ---- the run, and what it costs ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_a_run_calls_the_model_once_per_governed_fact_and_never_otherwise(
        self, release
    ):
        """The short-circuit M1 and M2 earned, still holding now that this
        stage exists: nothing uncovered, ambiguous or unresolved reaches a
        model at all."""

        ai = CitingProvider()
        expected = len(list(self.governed(release)))

        result = self.pipeline(ai).run(
            repository_id=self.REPOSITORY, release_id=release
        )
        counts = self.stage(result).counts

        assert ai.call_count == expected
        assert counts["verdicts"] == expected
        assert counts["from_model"] == expected
        assert counts["from_arbiter"] == 0

    def test_the_run_record_says_which_rung_each_verdict_came_from(self):
        """A run that fell to the arbiter and looked like a normal run would be
        the exact failure Rule 7 forbids, so the zero is published too."""

        result = self.pipeline(CitingProvider()).run(
            repository_id=self.REPOSITORY, release_id="v0.10.0"
        )
        counts = self.stage(result).counts

        assert counts["from_cache"] == 0
        assert counts["from_arbiter"] == 0
        assert counts["retried"] == 0
        assert counts["guard_rejections"] == 0
        assert counts["arbiter_agreed"] == 15

    def test_a_second_run_of_one_release_comes_entirely_from_the_cache(
        self, tmp_path
    ):
        """Reproducibility, demonstrated rather than asserted: the same
        question gets the same answer and costs nothing the second time."""

        ai = CitingProvider()
        cache = VerdictCache(tmp_path / "cache")

        first = self.pipeline(ai, cache).run(
            repository_id=self.REPOSITORY, release_id="v0.10.0"
        )
        calls_after_first = ai.call_count
        second = self.pipeline(ai, cache).run(
            repository_id=self.REPOSITORY, release_id="v0.10.0"
        )

        assert self.stage(first).counts["from_cache"] == 0
        assert self.stage(second).counts["from_cache"] == 15
        assert ai.call_count == calls_after_first

    def test_eight_of_eight_stages_are_implemented(self):
        """How far the component has got, asserted so that promoting a stage
        is a deliberate edit that shows up in a diff rather than a number that
        drifts.

        It has read five, six and seven in turn, and this is the last time it
        changes: the component has eight stages.
        """

        assert len(IMPLEMENTED_STAGES) == 8
        assert set(IMPLEMENTED_STAGES) == set(STAGE_ORDER)


def _superseded_record():
    """The decision `sa-inline-with-workload` replaced, as M2 recorded it."""

    from app.components.architecture_validation.models import (
        ConstraintKind,
        DecisionRecord,
        EvidenceStrength,
        ExtractionMethod,
    )

    return DecisionRecord(
        decision_id="sa-shared-component",
        subject="*",
        constraint=ConstraintKind.MUST_CALL_VIA,
        object="kustomize/components/service-accounts",
        valid_from="v0.9.0",
        valid_to="v0.10.0",
        source="config_scan",
        source_repository="online-boutique",
        source_tier=SourceTier.EXECUTABLE_CONFIG,
        source_strength=EvidenceStrength.AUTHORITATIVE,
        source_ref="kustomize/components/service-accounts",
        extraction_method=ExtractionMethod.RECONSTRUCTED,
        extracted_at=datetime(2026, 10, 15),
    )


class TestWhetherTheSecondModelWasAsked:
    """VER-9, VER-12 and VER-13. Three honest things a run can say.

    The two that must never collapse into one are `not_requested` and
    `unavailable`. The first is the architect's own decision and reflects on
    nothing. The second is a fault in the environment and may be the most
    important line in the result - so a single `skipped` covering both would
    throw away the only half anybody can act on.

    And neither of them is agreement, which is the trap underneath all of
    this: a falsy check that lumps a missing verification together with an
    approving one raises confidence on the basis of nothing.
    """

    def test_a_run_that_verified_says_so(self):
        service, _ = build()

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        assert result.verification_mode == VerificationMode.PERFORMED
        assert self.stage(result).status is StageStatus.COMPLETED

    def test_a_run_that_was_told_not_to_verify_says_that_instead(self):
        """VER-12. Published as a skip with *that* reason, never as an absent
        stage and never as a verdict that passed a check nobody ran."""

        service, _ = build()

        result = service.run(
            repository_id="online-boutique", release_id="v0.10.0", verify=False
        )

        assert result.verification_mode == VerificationMode.NOT_REQUESTED
        assert self.stage(result).status is StageStatus.SKIPPED
        assert "not requested" in self.stage(result).note

    def test_declining_verification_does_not_call_the_verifier_at_all(self):
        """The point of the flag is the model calls it does not make. A run
        that asked and discarded the answer would report the same mode while
        costing the same tokens."""

        service, stubs = build()

        service.run(
            repository_id="online-boutique", release_id="v0.10.0", verify=False
        )

        assert stubs["verification"].calls == 0

    def test_a_verifier_that_could_not_be_reached_says_that_instead(self):
        """VER-9. Not `performed` with a hole in it, and not `not_requested`:
        the environment failed, which is a different finding."""

        result = build_whole().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )

        assert result.verification_mode == VerificationMode.UNAVAILABLE
        assert self.stage(result).status is StageStatus.SKIPPED

    def test_an_unavailable_verifier_says_out_loud_that_this_is_not_agreement(self):
        """The sentence exists because an audience reads a missing check as an
        unfinished feature unless the output says it was refused - and the
        refusal is the design: substituting the reasoner would be the first
        model endorsing its own answer."""

        result = build_whole().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )
        note = self.stage(result).note

        assert "not" in note and "agreement" in note
        assert "reasoner was deliberately not used" in note

    def test_the_two_reasons_for_not_verifying_are_different_strings(self):
        """Asserted directly, because the whole of VER-D9 is that these two do
        not collapse - and a refactor that made them one string would leave
        every other test in this class passing."""

        service, _ = build()

        first = service.run(
            repository_id="online-boutique", release_id="v0.10.0", verify=False
        )
        second = build_whole().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )

        assert self.stage(first).note != self.stage(second).note
        assert first.verification_mode != second.verification_mode

    def test_a_release_with_nothing_to_verify_claims_neither(self):
        """Null rather than one of the three. An uncovered release did not
        decline the check and the check did not fail, so `not_requested` would
        blame the architect for a skip the architecture caused."""

        service, _ = build(resolve_first=False)

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        assert result.verification_mode is None
        assert self.stage(result).status is StageStatus.SKIPPED

    def test_an_unreachable_verifier_is_counted_apart_from_an_uncertain_one(self):
        """Summing them would make a dead free tier indistinguishable from a
        confused model, and the second is a result about the model while the
        first is a result about the afternoon."""

        result = build_whole().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )
        counts = self.stage(result).counts

        assert counts["verifications"] == 0
        assert counts["unavailable"] >= 1
        assert counts["uncertain"] == 0

    def test_a_verified_run_reports_what_the_second_model_said(self):
        service, _ = build()

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")
        counts = self.stage(result).counts

        assert counts["verifications"] == counts["agreed"] + counts["disagreed"] + (
            counts["uncertain"]
        )
        assert counts["unavailable"] == 0
        assert "objections" in counts

    def test_declining_verification_still_classifies_every_fact(self):
        """The flag halves the model work and changes nothing else. A run with
        `verify=false` that also stopped classifying would be a different
        feature."""

        service, _ = build()

        verified = service.run(repository_id="online-boutique", release_id="v0.10.0")
        declined = service.run(
            repository_id="online-boutique", release_id="v0.10.0", verify=False
        )

        assert len(declined.facts) == len(verified.facts)
        assert declined.status == verified.status

    @staticmethod
    def stage(result):
        return next(
            stage
            for stage in result.stages
            if stage.name == "independent_verification"
        )


def _is_a_difference_against_refs(node) -> bool:
    """Whether this expression is a set difference against something's `.refs`.

    Guard B identified by what it does rather than by its name, so a copy
    under a different name is still found. `set(refs) - package.refs` is the
    check; anything else subtracting from a `.refs` set is the same check
    written twice.
    """

    return (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Sub)
        and any(
            isinstance(side, ast.Attribute) and side.attr == "refs"
            for side in (node.left, node.right)
        )
    )


class TestTheM5Gate:
    """The stage gate for M5, as one executable checklist.

    Every row of `06_independent_verification/01_TARGETED_ARCHITECTURE.md` §9,
    asserted over **both** committed releases, beside the gates for M1 to M4.
    Most rows are covered in detail in `test_independent_verification.py`; the
    point of repeating them here is that the checklist stops being a list
    somebody ticks and becomes one the suite ticks.

    **Two rows carry more weight than the rest, and both are about a check
    that did not happen looking like one that passed.** An unreachable
    verifier must never fall back to the reasoner's model - that would be a
    `Verification` with a plausible model id on it, raising confidence while
    being the first model endorsing its own answer. And there must be exactly
    one definition of Guard B in the component, because two copies of a
    citation check is how one guarantee becomes two that disagree, and the
    drift stays invisible until a verdict passes one and fails the other.

    **One row of the eighteen cannot be asserted here yet**, and it is marked
    rather than quietly dropped - see `test_row_16_is_blocked_on_m6`.
    """

    RELEASES = ("v0.9.0", "v0.10.0")
    REPOSITORY = "online-boutique"

    # ---- the pieces, wired the way the composition root wires them ----

    def challenge(self):
        return load_prompt("critical_reframing.v1.md")

    def verifier(self, provider, cache=None):
        client = ConfiguredAIClient(
            provider,
            settings=AISettings(ai_api_key="not-a-real-key"),
            cache=cache or VerdictCache("unused", enabled=False),
        )
        return IndependentVerificationService(
            client, self.challenge(), TASK_VERIFICATION, provider="fake"
        )

    def pipeline(self, provider, cache=None, reasoning_provider=None):
        """The real first five stages, with the three after them stubbed.

        Which is what makes this a gate on M5 rather than on the whole
        component: every governed fact of a release reaches the verifier, and
        nothing downstream of it is real enough to hide a mistake.
        """

        return ArchitectureValidationService(
            architecture_reader=SnapshotFileReader(SNAPSHOTS),
            normalization=ObservationNormalizationService(),
            knowledge=DecisionKnowledgeService(
                WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
            ),
            evidence=EvidenceRetrievalService(WorkspaceReader()),
            reasoning=unreachable_reasoner(),
            verification=self.verifier(provider, cache),
            classification=StubClassification(),
            review=StubReview(),
            publishing=StubPublishing(),
        )

    def architecture(self, release):
        return SnapshotFileReader(SNAPSHOTS).read(self.REPOSITORY, release)

    def governed(self, release):
        architecture = self.architecture(release)
        facts = ObservationNormalizationService().normalise(architecture).facts
        store = DecisionKnowledgeService(
            WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
        )
        for fact in facts:
            resolution = store.resolve(fact, self.REPOSITORY)
            if resolution.governing is not None:
                yield fact, resolution

    def packages(self, release):
        architecture = self.architecture(release)
        evidence = EvidenceRetrievalService(WorkspaceReader())
        return [
            evidence.assemble(fact, resolution, architecture)
            for fact, resolution in self.governed(release)
        ]

    def primary(self, package, concluded=Verdict.CONFIRMS):
        """A verdict over a real package, as M4 would have produced it."""

        rule = next(
            item.ref
            for item in package.items
            if item.role in (EvidenceRole.RULE, EvidenceRole.PERMITTED_SET)
        )
        return PrimaryVerdict(
            fact_id=package.fact_id,
            verdict=concluded,
            reasoning="the governing rule names this pair",
            cited_evidence_refs=(rule,),
            model_id="fake/reasoner-1",
            prompt_version="primary_verdict@1",
            evidence_hash=package.evidence_hash,
            cached=False,
        )

    def challenged(self, outcome="agree", objections=()):
        return {
            "reasoning": "the cited rule does say what the verdict claims",
            "objections": [dict(objection) for objection in objections],
            "outcome": outcome,
        }

    def checked(self, package, outcome=VerificationOutcome.AGREE):
        """The verification M5 would have produced over the same package."""

        return Verification(
            fact_id=package.fact_id,
            outcome=outcome,
            mechanism="critical-reframing",
            reasoning="the cited rule does say what the verdict claims",
            model_id="fake/verifier-1",
            prompt_version="critical_reframing@1",
            cached=False,
            evidence_hash=package.evidence_hash,
        )

    def stage(self, result, name="independent_verification"):
        return next(stage for stage in result.stages if stage.name == name)

    # ---- row 1: the boundary ----

    def test_row_01_the_subcomponent_names_no_model_no_provider_and_no_key(self):
        """It asks for a task and hands over a schema. The moment one of these
        words appears in it, it has started choosing a model or reaching for a
        credential."""

        folder = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "components"
            / "architecture_validation"
            / "independent_verification"
        )

        for module in folder.rglob("*.py"):
            body = module.read_text(encoding="utf-8").lower()
            for forbidden in ("httpx", "openai", "groq", "qwen", "ai_api_key", "open("):
                assert forbidden not in body, f"{module.name} names {forbidden}"

    # ---- row 2: the configuration that is the whole experiment ----

    def test_row_02_the_verifier_is_a_different_model_and_takes_a_strict_schema(self):
        settings = AISettings(ai_api_key="not-a-real-key")

        assert settings.ai_verifier_model != settings.ai_reasoner_model
        assert capabilities_for(settings.ai_verifier_model).supports_strict_schema

    # ---- rows 3 and 4: what the verifier is and is not shown ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_row_03_the_prompt_shows_the_verdict_its_reasoning_and_its_refs(
        self, release
    ):
        for package in self.packages(release):
            verdict = self.primary(package)
            rendered = render_challenge(self.challenge(), package, verdict)

            assert verdict.verdict.value in rendered
            assert verdict.reasoning in rendered
            for ref in verdict.cited_evidence_refs:
                assert ref in rendered

    @pytest.mark.parametrize("release", RELEASES)
    def test_row_04_the_prompt_never_shows_the_arbiters_verdict(self, release):
        """Tell the verifier what the deterministic table concluded and it
        agrees with it. Every measured number improves and the only
        uncorrelated check in the component is gone."""

        for package in self.packages(release):
            rendered = render_challenge(
                self.challenge(), package, self.primary(package)
            ).lower()

            assert "arbiter" not in rendered
            assert "basis" not in rendered

    # ---- row 5: the schema, claiming nothing about generation order ----

    def test_row_05_the_schema_declares_objections_before_the_outcome(self):
        properties = list(strictify(verification_schema())["properties"])

        assert properties.index("objections") < properties.index("outcome")

    # ---- row 6: the hash that proves both passes saw one package ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_row_06_both_passes_ran_on_the_identical_evidence(self, release):
        ai = FakeProvider(responses=self.challenged())
        service = self.verifier(ai)

        for package in self.packages(release):
            verdict = self.primary(package)
            result = service.verify(verdict, package)

            assert result.evidence_hash == package.evidence_hash
            assert result.evidence_hash == verdict.evidence_hash

    # ---- rows 7 and 8: an objection has to point at something real ----

    def test_row_07_an_item_specific_objection_without_a_ref_is_refused(self):
        with pytest.raises(ValueError):
            Objection(ObjectionKind.CITATION_DOES_NOT_SUPPORT, None, "wrong")

    @pytest.mark.parametrize("release", RELEASES)
    def test_row_08_every_ref_an_objection_names_resolves_in_the_package(self, release):
        phantom = self.challenged(
            "disagree",
            ({"kind": "overlooked_evidence", "ref": "ADR-999", "statement": "x"},),
        )
        service = self.verifier(FakeProvider(responses=phantom))

        for package in self.packages(release):
            result = service.verify(self.primary(package), package)

            assert GuardFailure.UNRESOLVED_CITATION in result.guard_failures
            assert result.outcome is VerificationOutcome.UNCERTAIN

    # ---- rows 9 and 10: incoherence and malformation never become agreement ----

    def test_row_09_an_incoherent_answer_becomes_uncertain(self):
        faults = ({"kind": "claim_exceeds_evidence", "ref": None, "statement": "x"},)
        package = self.packages("v0.10.0")[0]

        agreeing = FakeProvider(responses=self.challenged("agree", faults))
        empty = FakeProvider(responses=self.challenged("disagree", ()))

        for ai in (agreeing, empty):
            result = self.verifier(ai).verify(self.primary(package), package)

            assert result.outcome is VerificationOutcome.UNCERTAIN
            assert GuardFailure.INCOHERENT_OUTCOME in result.guard_failures

    def test_row_10_malformed_twice_becomes_uncertain_never_agree(self):
        package = self.packages("v0.10.0")[0]

        result = self.verifier(FakeProvider(malformed_times=2)).verify(
            self.primary(package), package
        )

        assert result.outcome is VerificationOutcome.UNCERTAIN
        assert result.outcome is not VerificationOutcome.AGREE

    # ---- row 11: a real objection survives ----

    def test_row_11_a_real_objection_survives_with_its_kind_ref_and_sentence(self):
        package = self.packages("v0.10.0")[0]
        rule = self.primary(package).cited_evidence_refs[0]
        ai = FakeProvider(
            responses=self.challenged(
                "disagree",
                (
                    {
                        "kind": "citation_does_not_support",
                        "ref": rule,
                        "statement": "the line permits a different pair",
                    },
                ),
            )
        )

        result = self.verifier(ai).verify(self.primary(package), package)

        assert result.outcome is VerificationOutcome.DISAGREE
        assert result.objections[0].kind is ObjectionKind.CITATION_DOES_NOT_SUPPORT
        assert result.objections[0].ref == rule
        assert result.objections[0].statement == "the line permits a different pair"

    # ---- rows 12 and 13: the substitution that is refused, and the bound ----

    def test_row_12_an_unreachable_verifier_returns_none_and_never_calls_the_reasoner(
        self,
    ):
        """The most important row in the gate. A fallback to the reasoner's
        model would produce a Verification that looks completely real while
        being the first model endorsing its own answer - it would not fail and
        it would not warn."""

        package = self.packages("v0.10.0")[0]
        ai = FakeProvider(fail_times=99)

        result = self.verifier(ai).verify(self.primary(package), package)

        assert result is None
        asked = {call["model_id"] for call in ai.calls}
        settings = AISettings(ai_api_key="not-a-real-key")
        assert settings.ai_reasoner_model not in asked
        assert settings.ai_local_model not in asked

    def test_row_13_the_ladder_never_exceeds_two_model_calls(self):
        package = self.packages("v0.10.0")[0]
        ai = FakeProvider(fail_times=99)

        self.verifier(ai).verify(self.primary(package), package)

        assert ai.call_count <= 2

    # ---- row 14: provenance on every output ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_row_14_every_output_carries_its_provenance(self, release):
        ai = FakeProvider(responses=self.challenged())
        service = self.verifier(ai)

        for package in self.packages(release):
            result = service.verify(self.primary(package), package)

            assert result.mechanism == "critical-reframing"
            assert result.model_id
            assert result.provider
            assert result.schema_mode
            assert result.prompt_version == "critical_reframing@1"
            assert result.challenged_model_id

    # ---- row 15: reported, not adjudicated ----

    def test_row_15_a_disagreement_is_carried_forward_not_adjudicated(self):
        """No third call, no averaging. Resolving it here would make this an
        adjudicator - a different job with different failure modes - and it
        would hide the disagreement from the confidence score."""

        package = self.packages("v0.10.0")[0]
        faults = ({"kind": "unstated_assumption", "ref": None, "statement": "a mesh"},)
        ai = FakeProvider(responses=self.challenged("disagree", faults))

        result = self.verifier(ai).verify(self.primary(package), package)

        assert result.outcome is VerificationOutcome.DISAGREE
        assert ai.call_count == 1

    # ---- row 16: the one that is blocked ----

    def test_row_16_a_missing_verification_lowers_confidence_and_reviews(self):
        """The row this one held open while M6 was unwritten.

        It was asserting that `classify` raises `NotImplementedError`,
        inverted on purpose so that it failed the day the service was built
        and sent whoever built it here. That day has arrived, and this is the
        assertion it was holding the place for.

        `None` is a fourth state and not a falsy `AGREE`: an audited verdict
        and an unaudited one must not come out of here at the same number.
        """

        package = self.packages("v0.10.0")[0]
        fact, resolution = next(self.governed("v0.10.0"))
        verdict = self.primary(package)

        audited = ClassificationService().classify(
            fact, resolution, verdict, self.checked(package), VerificationMode.PERFORMED
        )
        unaudited = ClassificationService().classify(
            fact, resolution, verdict, None, VerificationMode.UNAVAILABLE
        )

        assert unaudited.confidence < audited.confidence
        assert unaudited.route == Route.REVIEW
        assert audited.route == Route.PUBLISH
        assert unaudited.score_trace.ceiling_applied == "unverified_unavailable"

    # ---- row 17: the counts, including the number this unit exists for ----

    @pytest.mark.parametrize("release", RELEASES)
    def test_row_17_the_run_reports_the_three_way_counts(self, release):
        ai = FakeProvider(responses=self.challenged())

        result = self.pipeline(ai).run(
            repository_id=self.REPOSITORY, release_id=release
        )
        counts = self.stage(result).counts

        for key in (
            "agreed",
            "disagreed",
            "uncertain",
            "unavailable",
            "agreed_while_arbiter_disagreed",
        ):
            assert key in counts, f"the run does not report {key}"

        assert counts["verifications"] == (
            counts["agreed"] + counts["disagreed"] + counts["uncertain"]
        )

    @pytest.mark.parametrize("release", RELEASES)
    def test_row_17_the_correlated_failure_count_is_zero_and_that_is_a_result(
        self, release
    ):
        """Zero on this corpus because it contains no violations for the models
        to be wrong about - *not observed on a corpus too clean to produce
        it*. A zero reported as *no correlated failure* would be a lie, and it
        is the easiest thing in the project to blur under presentation
        pressure."""

        ai = FakeProvider(responses=self.challenged())

        result = self.pipeline(ai).run(
            repository_id=self.REPOSITORY, release_id=release
        )

        assert self.stage(result).counts["agreed_while_arbiter_disagreed"] == 0

    # ---- row 18: one definition of Guard B ----

    def test_row_18_there_is_exactly_one_definition_of_guard_b(self):
        """The row most likely to be needed in six months. Two copies of a
        citation check is how one guarantee becomes two that disagree, and the
        drift stays invisible until a verdict passes one and fails the other.

        Asserted by parsing the component for functions that define the check
        rather than by grepping for the name, so a copy under a different name
        is still caught by what it does: a set difference against
        `package.refs`.
        """

        component = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "components"
            / "architecture_validation"
        )

        definitions = []
        for module in component.rglob("*.py"):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if any(_is_a_difference_against_refs(n) for n in ast.walk(node)):
                    definitions.append(f"{module.name}:{node.name}")

        assert definitions == ["_guards.py:check_citations_resolve"], (
            f"Guard B is defined in {definitions}; there must be exactly one"
        )


class ArmAwareProvider:
    """Answers whichever arm asked, citing a reference it was actually shown.

    The scripted-dict fake cannot serve these tests and the reason is Guard B
    doing its job: one dict cites one reference, and the fourteen packages
    whose evidence does not contain it correctly reject the answer. So the run
    would report one blind verdict out of fifteen and the arithmetic under
    test would never be exercised.

    This reads the governing rule's reference out of the prompt it was handed,
    which is what a model that cites what it can name does. It is still a fake
    with no judgement in it - the verdict and the outcome are scripted.
    """

    RULE = re.compile(r"\[([^\]]+)\] rule\n")

    def __init__(self, blind_verdict="confirms", informed="agree"):
        self._blind_verdict = blind_verdict
        self._informed = informed
        self.calls: list[dict] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(
        self,
        model_id,
        prompt,
        schema,
        strict=True,
        temperature=0.0,
        seed=42,
    ) -> dict:
        self.calls.append({"model_id": model_id, "prompt": prompt, "strict": strict})

        shown = self.RULE.search(prompt)
        cited = [shown.group(1)] if shown else []
        challenged = "What is wrong with that argument?" in prompt

        content = (
            {"reasoning": "the argument holds", "objections": [], "outcome": self._informed}
            if challenged
            else {
                "reasoning": "the rule names this pair",
                "cited_evidence_refs": cited,
                "verdict": self._blind_verdict,
            }
        )
        return {"content": content, "model_id": "fake/verifier-1", "usage": {}}


class TestTheTwoArmsOnARun:
    """VER-16 and VER-17. Two axes, and the number whose difference is the point.

    `verification_arm` is a **second axis** from `verification_mode`, not a
    widening of it: that field says whether verification ran, this one says
    what it was shown. Collapsing them would make *nobody asked for it* and
    *it ran blind* the same string, and an agreement rate cannot be read
    without both.
    """

    def blind_pipeline(self, *, blind_verdict="confirms", informed="agree"):
        """The real first five stages with both arms wired and scripted.

        The reasoner is unreachable here, so every verdict comes from the
        deterministic table - which is also the case the blind arm exists for,
        because the table abstains on anything it cannot speak to.
        """

        provider = ArmAwareProvider(blind_verdict=blind_verdict, informed=informed)
        client = ConfiguredAIClient(
            provider,
            settings=AISettings(ai_api_key="not-a-real-key"),
            cache=VerdictCache("unused", enabled=False),
        )
        verification = IndependentVerificationService(
            client,
            load_prompt("critical_reframing.v1.md"),
            TASK_VERIFICATION,
            provider="fake",
            blind_prompt=load_prompt("blind_verdict.v1.md"),
        )
        service = ArchitectureValidationService(
            architecture_reader=SnapshotFileReader(SNAPSHOTS),
            normalization=ObservationNormalizationService(),
            knowledge=DecisionKnowledgeService(
                WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
            ),
            evidence=EvidenceRetrievalService(WorkspaceReader()),
            reasoning=unreachable_reasoner(),
            verification=verification,
            classification=StubClassification(),
            review=StubReview(),
            publishing=StubPublishing(),
        )
        return service, provider

    def stage(self, result):
        return next(
            s for s in result.stages if s.name == "independent_verification"
        )

    def test_the_default_arm_is_informed(self):
        service, _ = self.blind_pipeline()

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        assert result.verification_arm == VerificationArm.INFORMED
        assert "blind_agreed" not in self.stage(result).counts

    def test_a_blind_run_reports_the_blind_arm(self):
        service, _ = self.blind_pipeline()

        result = service.run(
            repository_id="online-boutique", release_id="v0.10.0", arm="blind"
        )
        counts = self.stage(result).counts

        assert result.verification_arm == VerificationArm.BLIND
        assert result.verification_mode == VerificationMode.PERFORMED
        assert counts["blind_verdicts"] >= 1
        assert counts["verifications"] == 0

    def test_a_blind_only_run_is_performed_and_not_unavailable(self):
        """The quiet lie this guards against: a blind-only run has no informed
        opinion on any fact **by request**, and reading those absent
        verifications as failures would report a working run as
        `unavailable`."""

        service, _ = self.blind_pipeline()

        result = service.run(
            repository_id="online-boutique", release_id="v0.10.0", arm="blind"
        )

        assert result.verification_mode is not VerificationMode.UNAVAILABLE
        assert self.stage(result).counts["unavailable"] == 0

    def test_both_arms_run_three_calls_a_fact(self):
        """Why `both` is a measurement mode and not a demonstration one: two
        calls a fact becomes three, against a per-minute token cap."""

        service, provider = self.blind_pipeline()

        result = service.run(
            repository_id="online-boutique", release_id="v0.10.0", arm="both"
        )
        counts = self.stage(result).counts

        assert counts["verifications"] >= 1
        assert counts["blind_verdicts"] == counts["verifications"]
        assert provider.call_count == counts["verifications"] * 2

    def test_the_run_reports_both_rates_and_their_difference(self):
        service, _ = self.blind_pipeline()

        result = service.run(
            repository_id="online-boutique", release_id="v0.10.0", arm="both"
        )
        counts = self.stage(result).counts

        assert counts["anchoring_delta"] == counts["agreed"] - counts["blind_agreed"]

    def test_the_delta_is_zero_on_this_corpus_and_that_is_not_a_finding(self):
        """Every verdict here is `confirms` and the blind arm has nothing to
        disagree about, so the delta is zero **for want of anything to
        disagree about**. It has to be reported as *not measurable on this
        corpus* and never as *anchoring did not occur* - the same trap as the
        correlated-failure zero."""

        service, _ = self.blind_pipeline(blind_verdict="confirms", informed="agree")

        result = service.run(
            repository_id="online-boutique", release_id="v0.10.0", arm="both"
        )

        assert self.stage(result).counts["anchoring_delta"] == 0

    def test_a_blind_arm_that_disagrees_moves_the_delta(self):
        """The arithmetic proved on a disagreement the corpus cannot produce,
        so that a zero above is evidence of the corpus rather than of the
        code never computing anything."""

        service, _ = self.blind_pipeline(blind_verdict="unrelated", informed="agree")

        result = service.run(
            repository_id="online-boutique", release_id="v0.10.0", arm="both"
        )
        counts = self.stage(result).counts

        assert counts["blind_agreed"] == 0
        assert counts["anchoring_delta"] == counts["agreed"]
        assert counts["anchoring_delta"] > 0

    def test_a_fact_the_arbiter_abstained_on_still_gets_one_unanchored_opinion(self):
        """The reason V5 earns its place. The arbiter speaks only the closed
        constraint vocabulary, so where a decision came from prose it
        abstains - and in informed mode alone those facts have nothing on
        them that had not already seen the answer."""

        service, _ = self.blind_pipeline()

        result = service.run(
            repository_id="online-boutique", release_id="v0.10.0", arm="both"
        )
        counts = self.stage(result).counts

        assert "unanchored_cover" in counts
        assert counts["unanchored_cover"] <= counts["blind_verdicts"]

    def test_the_arm_is_null_when_verification_did_not_run(self):
        """A question that did not arise has no answer, and reporting
        `informed` on a run that verified nothing would describe a check that
        never happened."""

        service, _ = self.blind_pipeline()

        result = service.run(
            repository_id="online-boutique", release_id="v0.10.0", verify=False
        )

        assert result.verification_mode == VerificationMode.NOT_REQUESTED
        assert result.verification_arm is None

    def test_the_two_axes_are_independent_fields(self):
        """Asserted directly, because a refactor that merged them would leave
        every other test in this class passing."""

        service, _ = self.blind_pipeline()

        blind = service.run(
            repository_id="online-boutique", release_id="v0.10.0", arm="blind"
        )

        assert blind.verification_arm == VerificationArm.BLIND
        assert blind.verification_mode == VerificationMode.PERFORMED
        assert blind.verification_arm != blind.verification_mode


class TestTheM6GateOnARun:
    """M6's own rows: the stage counts, and the one number a whole release is
    gated on downstream.

    Asserted over `build_whole()`, which is the real classification
    service behind an unreachable reasoner and an unreachable verifier. That
    is the rung-5 configuration - every governed fact decided by the
    deterministic table, none of them audited - and it is the case where an
    honest confidence number matters most, because nothing in it came from a
    model at all.
    """

    def run(self, release="v0.10.0"):
        return build_whole().run(
            repository_id="online-boutique", release_id=release
        )

    def stage(self, result):
        return next(s for s in result.stages if s.name == "classification")

    def test_the_stage_reports_what_it_published_and_what_it_held_back(self):
        counts = self.stage(self.run()).counts

        assert counts["facts"] > 0
        assert counts["published"] + counts["review"] == counts["facts"]
        assert counts["capped"] == counts["facts"]

    def test_the_unrelated_rate_is_reported_even_when_it_is_zero(self):
        """It measures the resolver rather than the architecture, so the rate
        belongs on the run. A zero reported is worth more than a zero
        assumed - and on this corpus it should be zero."""

        assert self.stage(self.run()).counts["unrelated_resolutions"] == 0

    def test_a_verdict_with_no_model_behind_it_is_capped_and_sent_to_a_person(self):
        """The ladder's last rung, through the whole pipeline. Every governed
        fact is still decided and none of them is published unchecked."""

        counts = self.stage(self.run()).counts

        assert counts["published"] == 0
        assert counts["review"] == counts["facts"]

    def test_the_release_confidence_is_the_mean_of_the_facts(self):
        """Checkable by hand from the output, which is the whole point of
        publishing the per-fact arithmetic."""

        result = self.run()
        facts = result.facts

        assert result.validation_confidence == pytest.approx(
            sum(fact.confidence for fact in facts) / len(facts), abs=1e-4
        )

    def test_the_release_confidence_is_capped_by_the_ladder_rung_it_ran_on(self):
        """0.60 and not 0.85: nothing in this run was produced by a model, and
        the number says so without anybody having to read the badge."""

        result = self.run()

        assert result.validation_confidence == 0.60
        assert all(
            fact.score_trace.ceiling_applied == "verdict_without_a_model"
            for fact in result.facts
        )

    def test_a_release_with_no_facts_scores_zero_and_says_how_many(self, tmp_path):
        """The distinction the gate downstream cannot make on its own:
        *nothing was validated* and *everything validated badly* are both 0.0,
        and only the count beside it separates them.

        It runs against a **copy** of the decision store, and that is not
        tidiness. An empty architecture mines no rules, so the knowledge model
        concludes that every rule it already holds has been withdrawn and
        appends a supersession for each one - which closes their validity
        intervals at this release, in an append-only log. Pointed at the
        committed corpus it rewrote it, and nineteen unrelated tests in three
        other files then failed. See the build note in 07's PLAN.md.
        """

        store = tmp_path / "decisions"
        shutil.copytree(FIXTURES / "decisions", store)
        empty = RecoveredArchitecture(
            repository_id="online-boutique",
            release_id="v0.10.0",
            style=ArchitectureStyle.MICROSERVICES,
            style_source=StyleSource.C1,
            elements=(),
            relationships=(),
            provenance=RecoveryProvenance("snapshot_file_reader", "1.0.0", "test"),
        )
        service = ArchitectureValidationService(
            architecture_reader=_Fixed(empty),
            normalization=ObservationNormalizationService(),
            knowledge=DecisionKnowledgeService(
                WorkspaceReader(), JsonlDecisionStore(store)
            ),
            evidence=EvidenceRetrievalService(WorkspaceReader()),
            reasoning=unreachable_reasoner(),
            verification=unreachable_verifier(),
            classification=ClassificationService(),
            review=ArchitectReviewService(),
            publishing=GraphPublishingService(),
        )

        result = service.run(repository_id="online-boutique", release_id="v0.10.0")

        assert result.validation_confidence == 0.0
        assert result.facts == ()
        assert self.stage(result).status is StageStatus.SKIPPED


class _NotBuilt:
    """A subcomponent nobody has written yet, which is what every stage was.

    Kept so the guarantee in `test_a_stage_that_did_not_run_says_so` outlives
    the condition that used to produce it for free.
    """

    def judge(self, *args, **kwargs):
        raise NotImplementedError
