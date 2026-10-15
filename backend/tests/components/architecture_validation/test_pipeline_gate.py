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

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.components.architecture_validation.models import (
    ClassifiedFact,
    EvidencePackage,
    PrimaryVerdict,
    Resolution,
    ScoreTrace,
    SourceTier,
    StageStatus,
    Verdict,
    Verification,
    VerificationOutcome,
)
from app.components.architecture_validation.architect_review import (
    ArchitectReviewService,
)
from app.components.architecture_validation.classification import ClassificationService
from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
    DecisionStageOutcome,
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
from app.components.architecture_validation.pipeline import IMPLEMENTED_STAGES
from app.components.architecture_validation.validation_reasoning import (
    ValidationReasoningService,
)
from app.components.architecture_validation.service import (
    STAGE_ORDER,
    ArchitectureValidationService,
)
from dataclasses import replace

from app.domain.recovered_architecture import (
    ArchitectureStyle,
    EvidenceQuality,
    ElementKind,
    RecoveredArchitecture,
    RecoveryProvenance,
    StyleSource,
)
from app.infrastructure.recovery_gateway.fixture_reader import (
    FixtureArchitectureReader,
)
from app.infrastructure.decision_log import JsonlDecisionStore
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

    def assemble(self, fact, resolution) -> EvidencePackage:
        self.calls += 1
        return EvidencePackage(fact_id=fact.fact_id, evidence_hash="hash-1", items=())


class StubReasoning:
    def __init__(self) -> None:
        self.calls = 0

    def judge(self, package) -> PrimaryVerdict:
        self.calls += 1
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
    def classify(self, fact, resolution, verdict, verification) -> ClassifiedFact:
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

    def enqueue(self, facts) -> tuple[str, ...]:
        self.queued.extend(facts)
        return tuple(f"review-{index}" for index, _ in enumerate(facts))


class StubPublishing:
    def __init__(self) -> None:
        self.published = None

    def publish(self, run, architecture) -> str:
        self.published = run
        return f"artifacts/validated/{run.release_id}.graph.json"


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


def build_unimplemented(release="v0.10.0"):
    """Assemble the pipeline from the real subcomponents, stubs and all.

    This is what the API wires today, so it is the configuration the run
    endpoint is actually exercised in. The knowledge model reads the recorded
    decision corpus, which is the same log a live run accumulates - read
    through the same port, so nothing here is a special case.
    """

    return ArchitectureValidationService(
        architecture_reader=SnapshotFileReader(SNAPSHOTS),
        normalization=ObservationNormalizationService(),
        knowledge=DecisionKnowledgeService(
            WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
        ),
        evidence=EvidenceRetrievalService(),
        reasoning=ValidationReasoningService(),
        verification=IndependentVerificationService(),
        classification=ClassificationService(),
        review=ArchitectReviewService(),
        publishing=GraphPublishingService(),
    )


class TestStagesNotBuiltYet:
    """An eight-stage component has to be runnable before stage eight exists."""

    def test_a_run_completes_with_only_one_subcomponent_implemented(self):
        """Without this the component is undemonstrable until the last stage
        is finished, and the stages that do work cannot be shown at all."""

        result = build_unimplemented().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )

        assert result.status == "incomplete"
        assert [stage.name for stage in result.stages] == list(STAGE_ORDER)

    def test_the_implemented_stage_still_reports_what_it_did(self):
        result = build_unimplemented().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )
        stages = {stage.name: stage for stage in result.stages}
        normalisation = stages["observation_normalization"]

        assert normalisation.status is StageStatus.COMPLETED
        assert normalisation.counts["facts"] > 0

    def test_no_unimplemented_stage_claims_to_have_completed(self):
        """A stub reporting a completed pass would be the one failure mode
        that makes the whole board worthless."""

        result = build_unimplemented().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )

        for stage in result.stages:
            if stage.name in IMPLEMENTED_STAGES:
                continue
            assert stage.status in {StageStatus.PENDING, StageStatus.SKIPPED}
            assert stage.note

    def test_a_stage_after_the_one_that_stalled_names_what_stopped_it(self):
        """Otherwise it reads as a clean pass over work it never saw.

        Which stage stalls moves along as each one is built, so it is read
        from the pipeline's own description rather than named here - the test
        would otherwise have to be rewritten on the day it finally passes.
        """

        result = build_unimplemented().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )
        stages = {stage.name: stage for stage in result.stages}
        stalled = next(
            stage.name for stage in result.stages
            if stage.status is StageStatus.PENDING
        )

        assert stalled not in IMPLEMENTED_STAGES
        assert stages["classification"].status is StageStatus.SKIPPED
        assert stalled in stages["classification"].note

    def test_an_incomplete_run_makes_no_model_calls_and_publishes_nothing(self):
        result = build_unimplemented().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )

        assert result.model_calls == 0
        assert result.published_ref is None

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

    def test_a_skipped_stage_blames_the_stub_rather_than_the_evidence(self):
        """"No fact had a governing decision" would read as a stage having
        looked and found none, which is not what happened."""

        result = build_unimplemented().run(
            repository_id="online-boutique", release_id="v0.10.0"
        )
        stages = {stage.name: stage for stage in result.stages}
        stalled = next(
            stage.name for stage in result.stages
            if stage.status is StageStatus.PENDING
        )

        for name in ("validation_reasoning", "independent_verification"):
            assert stalled in stages[name].note


class TestARunWithNothingToValidate:
    """Zero facts is a real outcome, and it must not look like a clean pass."""

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

    def test_the_stand_in_lives_outside_the_component_and_names_its_expiry(self):
        """The last row of the checklist, and the only one that is about where
        a file is rather than what it does."""

        import ast
        from pathlib import Path

        stand_in = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "infrastructure"
            / "recovery_gateway"
            / "c1_dependency_stand_in.py"
        )

        assert stand_in.is_file()
        docstring = ast.get_docstring(ast.parse(stand_in.read_text(encoding="utf-8"))) or ""
        assert "deleted when recovery ships" in docstring

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

        assert kinds[ConstraintKind.MAY_CALL] == 16
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

        import json

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
            "combined": 25,
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
        assert outcome.reconstructed == 25
        assert outcome.in_force == 25

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
