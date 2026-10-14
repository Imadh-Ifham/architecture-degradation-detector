"""The foundation phase gate: the pipeline runs end to end.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Runs a whole validation run with every subcomponent except normalisation
    behind a stub, and checks the wiring.

    This is the cheapest test in the project and the one with the best return.
    A pipeline that runs with its subcomponents stubbed proves the orchestration
    is correct *before* any logic exists that could hide a wiring bug - and
    once it passes, the nine subcomponents can be built in any order, because
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
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.components.architecture_validation.service import (
    STAGE_ORDER,
    ArchitectureValidationService,
)
from app.domain.recovered_architecture import ArchitectureStyle, ElementKind
from app.infrastructure.recovered_architecture.fixture_reader import (
    FixtureArchitectureReader,
)
from app.infrastructure.recovered_architecture.translation import manifest_paths

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"
SUBJECT = FIXTURES / "subject"


class StubIntent:
    def __init__(self, candidates: int = 3) -> None:
        self.candidates = candidates
        self.calls = 0

    def extract(self, repository_id, release_id):
        from app.components.architecture_validation.intent_extraction.models import (
            ExtractionOutcome,
        )

        self.calls += 1
        return ExtractionOutcome(
            candidates=(),
            sources_run=("decision_records", "configuration", "service_contracts"),
            counts_by_tier={"tier_1_decision_record": 0, "tier_2_executable_config": self.candidates},
        )


class StubKnowledge:
    """Resolves the first fact and leaves every other one uncovered.

    One governing decision and the rest uncovered is the realistic shape for a
    repository with partial recorded intent, and it exercises both the
    reasoning path and the short-circuit in one run.
    """

    def __init__(self, resolve_first: bool = True) -> None:
        self.resolve_first = resolve_first
        self.calls = 0

    def resolve(self, fact) -> Resolution:
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
    """Assemble the pipeline with one real subcomponent and eight stubs."""

    stubs = {
        "intent": StubIntent(),
        "knowledge": StubKnowledge(resolve_first=resolve_first),
        "evidence": StubEvidence(),
        "reasoning": StubReasoning(),
        "verification": StubVerification(),
        "classification": StubClassification(),
        "review": StubReview(),
        "publishing": StubPublishing(),
    }
    service = ArchitectureValidationService(
        architecture_reader=FixtureArchitectureReader(FIXTURES),
        normalization=ObservationNormalizationService(WorkspaceReader()),
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
        assert normalisation.counts["derived_relationships"] > 0

    def test_the_style_is_inferred_from_the_recorded_inventory(self):
        architecture = FixtureArchitectureReader(FIXTURES).read("online-boutique", "v0.10.0")

        assert architecture.style is ArchitectureStyle.MICROSERVICES
        assert all(
            element.kind is ElementKind.SERVICE for element in architecture.elements
        )

    def test_recovery_supplies_no_element_relationships_so_they_are_derived(self):
        """The finding this whole input layer exists for."""

        architecture = FixtureArchitectureReader(FIXTURES).read("online-boutique", "v0.10.0")

        assert architecture.has_element_relationships is False

    def test_the_new_release_adds_the_service_the_diff_showed(self):
        reader = FixtureArchitectureReader(FIXTURES)

        previous = {e.name for e in reader.read("online-boutique", "v0.9.0").elements}
        current = {e.name for e in reader.read("online-boutique", "v0.10.0").elements}

        assert current - previous == {"shoppingassistantservice"}

    def test_the_derived_dependencies_match_the_real_manifests(self):
        """checkoutservice declares six, and they are the six in the manifest."""

        service = ObservationNormalizationService(WorkspaceReader())
        architecture = FixtureArchitectureReader(FIXTURES).read("online-boutique", "v0.10.0")
        document = json.loads((FIXTURES / "inventory_v0.10.0.json").read_text(encoding="utf-8"))

        outcome = service.normalise(architecture, manifest_paths(document))

        checkout = {f.object for f in outcome.facts if f.subject == "checkoutservice"}
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
