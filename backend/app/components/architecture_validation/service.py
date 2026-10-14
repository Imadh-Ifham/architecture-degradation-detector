"""Architecture validation service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Orchestrates the nine subcomponents for one validation run. This is the
    only module that knows the pipeline order, and the only way into the
    component from outside it.

    Subcomponents never call each other. Each receives what it needs as an
    argument and returns its result here, which is what lets any of them be
    built, tested or replaced without the others existing.

    The short-circuits live here rather than inside the subcomponents they
    skip. When no decision governs a fact, reasoning is never called at all -
    so an uncovered fact reaches its bucket with provably zero model calls,
    rather than with a call whose result was discarded.
"""

import uuid
from time import perf_counter

from app.domain.recovered_architecture import RecoveredArchitecture

from .architect_review import ArchitectReviewService
from .classification import ClassificationService
from .decision_knowledge import DecisionKnowledgeService
from .evidence_retrieval import EvidenceRetrievalService
from .graph_publishing import GraphPublishingService
from .independent_verification import IndependentVerificationService
from .intent_extraction import IntentExtractionService
from .models import (
    ClassifiedFact,
    StageRecord,
    StageStatus,
    ValidationRunResult,
)
from .observation_normalization import ObservationNormalizationService
from .ports import RecoveredArchitectureReader
from .validation_reasoning import ValidationReasoningService

STAGE_ORDER = (
    "observation_normalization",
    "intent_extraction",
    "decision_knowledge",
    "evidence_retrieval",
    "validation_reasoning",
    "independent_verification",
    "classification",
    "architect_review",
    "graph_publishing",
)


class _Stage:
    """Times one stage and records how it ended.

    A context manager rather than a decorator so a stage that short-circuits
    can still report itself as skipped with a reason, instead of silently
    producing no record at all.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.status = StageStatus.COMPLETED
        self.counts: dict = {}
        self.note: str | None = None
        self._started = 0.0

    def __enter__(self) -> "_Stage":
        self._started = perf_counter()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is not None:
            self.status = StageStatus.FAILED
            self.note = str(exc)
        return False

    def skip(self, note: str) -> None:
        self.status = StageStatus.SKIPPED
        self.note = note

    def record(self) -> StageRecord:
        return StageRecord(
            name=self.name,
            status=self.status,
            counts=self.counts,
            duration_ms=int((perf_counter() - self._started) * 1000),
            note=self.note,
        )


class ArchitectureValidationService:
    """Validates one release and publishes the result.

    Every dependency is injected, including each subcomponent, so a run can be
    exercised end to end with any part of it faked. That is what makes the
    wiring testable before any of the logic exists.
    """

    def __init__(
        self,
        architecture_reader: RecoveredArchitectureReader,
        normalization: ObservationNormalizationService,
        intent: IntentExtractionService,
        knowledge: DecisionKnowledgeService,
        evidence: EvidenceRetrievalService,
        reasoning: ValidationReasoningService,
        verification: IndependentVerificationService,
        classification: ClassificationService,
        review: ArchitectReviewService,
        publishing: GraphPublishingService,
    ) -> None:
        self._architecture_reader = architecture_reader
        self._normalization = normalization
        self._intent = intent
        self._knowledge = knowledge
        self._evidence = evidence
        self._reasoning = reasoning
        self._verification = verification
        self._classification = classification
        self._review = review
        self._publishing = publishing

    def run(self, repository_id: str, release_id: str) -> ValidationRunResult:
        """Validate one release of one repository.

        `release_id` is supplied by the caller rather than read from the
        recovered architecture: recovery identifies a release by commit, and
        commit hashes carry no order, which the validity intervals in the
        knowledge model require.
        """

        run_id = uuid.uuid4().hex[:12]
        architecture = self._architecture_reader.read(repository_id, release_id)

        stages: list[StageRecord] = []
        facts, stage = self._normalise(architecture)
        stages.append(stage)

        stages.append(self._extract_intent(repository_id, release_id))

        classified, reasoning_stages = self._validate_each(facts)
        stages.extend(reasoning_stages)

        stages.append(self._queue_for_review(classified))

        published_ref, stage = self._publish(
            run_id, repository_id, release_id, classified, stages, architecture
        )
        stages.append(stage)

        return ValidationRunResult(
            run_id=run_id,
            repository_id=repository_id,
            release_id=release_id,
            status="completed",
            stages=tuple(stages),
            facts=tuple(classified),
            published_ref=published_ref,
            model_calls=sum(fact.model_calls for fact in classified),
        )

    def _normalise(self, architecture: RecoveredArchitecture):
        with _Stage("observation_normalization") as stage:
            outcome = self._normalization.normalise(architecture)
            stage.counts = {
                "facts": len(outcome.facts),
                "derived_relationships": outcome.derived_relationships,
            }
            if outcome.style_resolved == "generic":
                stage.note = "architecture style not resolved; confidence capped"
            return outcome.facts, stage.record()

    def _extract_intent(self, repository_id: str, release_id: str) -> StageRecord:
        with _Stage("intent_extraction") as stage:
            outcome = self._intent.extract(repository_id, release_id)
            stage.counts = {
                "candidates": len(outcome.candidates),
                "sources_run": len(outcome.sources_run),
                **outcome.counts_by_tier,
            }
            return stage.record()

    def _validate_each(self, facts) -> tuple[list[ClassifiedFact], list[StageRecord]]:
        """Resolve, reason about and classify every fact.

        The five per-fact stages are reported once for the whole pass rather
        than once per fact: a reader wants to know how many facts reached
        reasoning, not to scroll through one record per relationship.
        """

        knowledge = _Stage("decision_knowledge")
        evidence = _Stage("evidence_retrieval")
        reasoning = _Stage("validation_reasoning")
        verification = _Stage("independent_verification")
        classification = _Stage("classification")

        counts = {"resolved": 0, "uncovered": 0, "ambiguous": 0, "reasoned": 0}
        classified: list[ClassifiedFact] = []

        with knowledge, evidence, reasoning, verification, classification:
            for fact in facts:
                resolution = self._knowledge.resolve(fact)

                if resolution.uncovered or resolution.ambiguous:
                    # Nothing to reason against. The model is never called,
                    # which is why the published fact can report zero calls.
                    counts["uncovered" if resolution.uncovered else "ambiguous"] += 1
                    classified.append(
                        self._classification.classify(fact, resolution, None, None)
                    )
                    continue

                counts["resolved"] += 1
                package = self._evidence.assemble(fact, resolution)
                verdict = self._reasoning.judge(package)
                checked = self._verification.verify(verdict, package)
                counts["reasoned"] += 1
                classified.append(
                    self._classification.classify(fact, resolution, verdict, checked)
                )

        knowledge.counts = {k: counts[k] for k in ("resolved", "uncovered", "ambiguous")}
        evidence.counts = {"packages": counts["resolved"]}
        reasoning.counts = {"verdicts": counts["reasoned"]}
        verification.counts = {"verifications": counts["reasoned"]}
        classification.counts = {"facts": len(classified)}

        if counts["reasoned"] == 0:
            reasoning.skip("no fact had a governing decision to reason against")
            verification.skip("nothing to verify")

        return classified, [
            knowledge.record(),
            evidence.record(),
            reasoning.record(),
            verification.record(),
            classification.record(),
        ]

    def _queue_for_review(self, classified: list[ClassifiedFact]) -> StageRecord:
        with _Stage("architect_review") as stage:
            needing_review = tuple(f for f in classified if f.route == "review")
            queued = self._review.enqueue(needing_review) if needing_review else ()
            stage.counts = {"queued": len(queued)}
            if not needing_review:
                stage.skip("no fact was routed for review")
            return stage.record()

    def _publish(
        self,
        run_id: str,
        repository_id: str,
        release_id: str,
        classified: list[ClassifiedFact],
        stages: list[StageRecord],
        architecture: RecoveredArchitecture,
    ):
        with _Stage("graph_publishing") as stage:
            interim = ValidationRunResult(
                run_id=run_id,
                repository_id=repository_id,
                release_id=release_id,
                status="publishing",
                stages=tuple(stages),
                facts=tuple(classified),
                model_calls=sum(fact.model_calls for fact in classified),
            )
            published_ref = self._publishing.publish(interim, architecture)
            stage.counts = {"nodes": len(architecture.elements), "edges": len(classified)}
            return published_ref, stage.record()


__all__ = ["ArchitectureValidationService", "STAGE_ORDER"]
