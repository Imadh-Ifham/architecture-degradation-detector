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

    A subcomponent that is not written yet is reported as a pending stage and
    the run carries on. The alternative - the whole run failing on the first
    stub - would make a nine-stage component undemonstrable until the last
    stage was finished, and would hide the fact that the earlier stages work.
    Only `NotImplementedError` is treated this way, so a stage that genuinely
    broke still fails loudly.
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
        self.warnings: tuple[str, ...] = ()
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

    def pending(self, note: str | None = None) -> None:
        self.status = StageStatus.PENDING
        self.note = note or "not implemented yet"

    def record(self) -> StageRecord:
        return StageRecord(
            name=self.name,
            status=self.status,
            counts=self.counts,
            duration_ms=int((perf_counter() - self._started) * 1000),
            note=self.note,
            warnings=self.warnings,
        )


def _attempt(stage: _Stage, call, *arguments):
    """Make one subcomponent call, returning whether it had an implementation.

    Catches `NotImplementedError` around that single call and nothing else, so
    a stub nobody has written yet and a subcomponent that broke stay
    distinguishable in the run record.
    """

    try:
        return call(*arguments), True
    except NotImplementedError as error:
        stage.pending(str(error) or None)
        return None, False


def _run_status(stages: list[StageRecord]) -> str:
    """Describe the run as a whole from how its stages ended.

    A run with stages still pending is reported as incomplete rather than
    completed, so a caller never reads a partial run as a finished one.
    """

    if any(stage.status is StageStatus.FAILED for stage in stages):
        return "failed"
    if any(stage.status is StageStatus.PENDING for stage in stages):
        return "incomplete"
    return "completed"


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
        facts, stage, style = self._normalise(architecture)
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
            status=_run_status(stages),
            stages=tuple(stages),
            facts=tuple(classified),
            published_ref=published_ref,
            model_calls=sum(fact.model_calls for fact in classified),
            style_resolved=style[0],
            style_source=style[1],
        )

    def _normalise(self, architecture: RecoveredArchitecture):
        """Normalise, and return the facts, the stage record and the style.

        The style travels back as a pair rather than being read off a fact,
        because a run with no facts still resolved a style and still has to
        report whose answer it was.
        """

        with _Stage("observation_normalization") as stage:
            outcome, ran = _attempt(stage, self._normalization.normalise, architecture)
            if not ran:
                return (), stage.record(), (None, None)

            stage.counts = {
                "facts": len(outcome.facts),
                "relationships": outcome.relationship_count,
                "identity_collisions": len(outcome.identity_collisions),
                "merged_facts": outcome.merged_fact_count,
                "absorbed_labels": len(outcome.absorbed_labels),
            }
            stage.note = self._style_note(outcome)
            stage.warnings = outcome.warnings
            return (
                outcome.facts,
                stage.record(),
                (outcome.style_resolved, outcome.style_source),
            )

    def _style_note(self, outcome) -> str | None:
        """The one style case that belongs in the note rather than the warnings.

        The note is for what happened to the stage - skipped, pending, failed
        - plus anything that caps the whole run. An undetermined style does
        cap it: every verdict built on these facts inherits the ceiling, so a
        reader scanning statuses has to see it without opening the warnings.

        An *inferred* style is an observation and stays in the warnings, where
        normalisation already put it. Repeating it here would print the same
        sentence twice on every run, and a field that usually repeats another
        one stops being read.
        """

        if outcome.style_resolved == "generic":
            return "architecture style not resolved; confidence capped"
        return None

    def _extract_intent(self, repository_id: str, release_id: str) -> StageRecord:
        with _Stage("intent_extraction") as stage:
            outcome, ran = _attempt(
                stage, self._intent.extract, repository_id, release_id
            )
            if ran:
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

        group = (knowledge, evidence, reasoning, verification, classification)
        counts = {"resolved": 0, "uncovered": 0, "ambiguous": 0, "reasoned": 0}
        classified: list[ClassifiedFact] = []

        with knowledge, evidence, reasoning, verification, classification:
            for fact in facts:
                resolution, ran = _attempt(knowledge, self._knowledge.resolve, fact)
                if not ran:
                    break

                if resolution.uncovered or resolution.ambiguous:
                    # Nothing to reason against. The model is never called,
                    # which is why the published fact can report zero calls.
                    counts["uncovered" if resolution.uncovered else "ambiguous"] += 1
                    result, ran = _attempt(
                        classification,
                        self._classification.classify,
                        fact,
                        resolution,
                        None,
                        None,
                    )
                    if not ran:
                        break
                    classified.append(result)
                    continue

                counts["resolved"] += 1
                package, ran = _attempt(
                    evidence, self._evidence.assemble, fact, resolution
                )
                if not ran:
                    break

                verdict, ran = _attempt(reasoning, self._reasoning.judge, package)
                if not ran:
                    break

                checked, ran = _attempt(
                    verification, self._verification.verify, verdict, package
                )
                if not ran:
                    break

                counts["reasoned"] += 1
                result, ran = _attempt(
                    classification,
                    self._classification.classify,
                    fact,
                    resolution,
                    verdict,
                    checked,
                )
                if not ran:
                    break
                classified.append(result)

        knowledge.counts = {k: counts[k] for k in ("resolved", "uncovered", "ambiguous")}
        evidence.counts = {"packages": counts["resolved"]}
        reasoning.counts = {"verdicts": counts["reasoned"]}
        verification.counts = {"verifications": counts["reasoned"]}
        classification.counts = {"facts": len(classified)}

        if not facts:
            # Not one of these five was called. Reporting them as completed
            # would be the same lie as a stub reporting a completed pass: a
            # board of green stages over a run that validated nothing.
            for stage in group:
                if stage.status is StageStatus.COMPLETED:
                    stage.skip("normalisation produced no facts to validate")
            return classified, [stage.record() for stage in group]

        # A stage after the one that stalled was never reached, so it reports
        # itself skipped with the reason rather than as a clean pass over
        # nothing it never saw. Named before the short-circuit below, because
        # "no fact had a governing decision" would otherwise be attached to a
        # pass that never happened - which reads as knowledge having looked.
        stalled = next((s for s in group if s.status is StageStatus.PENDING), None)
        if stalled is not None:
            for stage in group[group.index(stalled) + 1 :]:
                if stage.status is StageStatus.COMPLETED:
                    stage.skip(f"{stalled.name} is not implemented yet")

        if counts["reasoned"] == 0:
            if reasoning.status is StageStatus.COMPLETED:
                reasoning.skip("no fact had a governing decision to reason against")
            if verification.status is StageStatus.COMPLETED:
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
            if not needing_review:
                stage.counts = {"queued": 0}
                stage.skip("no fact was routed for review")
                return stage.record()

            queued, ran = _attempt(stage, self._review.enqueue, needing_review)
            stage.counts = {"queued": len(queued) if ran else 0}
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
            published_ref, ran = _attempt(
                stage, self._publishing.publish, interim, architecture
            )
            if ran:
                stage.counts = {
                    "nodes": len(architecture.elements),
                    "edges": len(classified),
                }
            return published_ref, stage.record()


__all__ = ["ArchitectureValidationService", "STAGE_ORDER"]
