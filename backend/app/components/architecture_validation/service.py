"""Architecture validation service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Orchestrates the eight subcomponents for one validation run. This is the
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
    stub - would make an eight-stage component undemonstrable until the last
    stage was finished, and would hide the fact that the earlier stages work.
    Only `NotImplementedError` is treated this way, so a stage that genuinely
    broke still fails loudly.
"""

import uuid
from collections import Counter
from datetime import UTC, datetime
from time import perf_counter

from app.domain.recovered_architecture import RecoveredArchitecture

from .architect_review import ArchitectReviewService
from .classification import ClassificationService, Route, per_fact_mode
from .decision_knowledge import (
    DEFAULT_MODE,
    DecisionKnowledgeService,
    SourceRequest,
)
from .evidence_retrieval import EvidenceRetrievalService
from .graph_publishing import GraphPublishingService
from .independent_verification import IndependentVerificationService
from .models import (
    ArbiterAgreement,
    ClassifiedFact,
    PrimaryVerdict,
    StageRecord,
    StageStatus,
    ValidationRunResult,
    Verdict,
    VerdictSource,
    Verification,
    VerificationArm,
    VerificationMode,
    VerificationOutcome,
)
from .observation_normalization import ObservationNormalizationService
from .ports import RecoveredArchitectureReader
from .validation_reasoning import ValidationReasoningService
from .validation_reasoning._arbiter import decide

STAGE_ORDER = (
    "observation_normalization",
    "decision_knowledge",
    "evidence_retrieval",
    "validation_reasoning",
    "independent_verification",
    "classification",
    "architect_review",
    "graph_publishing",
)


VERIFICATION_NOTES = {
    VerificationMode.PERFORMED: "verification: performed by a second model",
    VerificationMode.NOT_REQUESTED: "verification: not requested on this run",
    VerificationMode.UNAVAILABLE: (
        "verification: the verifying model could not be reached. This is not "
        "agreement - the reasoner was deliberately not used in its place"
    ),
}
"""One sentence per mode, written here rather than at each reader.

The stage note and the summary card say the same thing because they read the
same string. The `unavailable` sentence says what was *not* done on purpose:
an audience that sees a missing check reads it as an unfinished feature
unless the output says it was refused.
"""


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


def _verification_counts(judged: list[tuple], verify: bool, arm: str) -> dict:
    """What the second model said across the run, and the one number that matters.

    `unavailable` is counted separately from `uncertain` and that separation
    is the point: a verifier that could not be reached produced nothing, and a
    verifier that answered unusably produced an uncertainty. Summing them
    would make a dead free tier indistinguishable from a confused model - the
    first is a result about the afternoon, the second is a result about the
    model.

    Every key is always present, and all of them are zero on a run that did
    not ask. A counts dictionary whose shape depends on the mode makes every
    reader branch, and the mode is already published for the reader who cares.

    **`agreed_while_arbiter_disagreed` is the component's headline number.**
    The facts where the verifier endorsed the reasoner *and* the deterministic
    table disagreed with both are a measured lower bound on correlated model
    failure, and no single-model or two-model pipeline can produce it. It is
    counted here whether or not anybody asks for it, because a number that is
    only computed on request is a number nobody has.

    On this corpus it will be **zero**, because the corpus contains no
    violations for the models to be wrong about. That has to be reported as
    *not observed on a corpus too clean to produce it* and never as *no
    correlated failure*.

    **The blind keys arrive only on a run that asked for the blind arm**, and
    `anchoring_delta` carries one caveat that the arithmetic hides. The
    informed arm's `agreed` means *the verifier found no fault in the
    argument*; the blind arm's means *the verifier reached the same verdict*.
    Those are two different questions, so the difference is an indication of
    how much being shown the answer moves the second model, and not a
    measurement of one quantity under two conditions. It is still the only
    number in the component that bounds the anchoring at all, and on this
    corpus it will be zero for want of anything to disagree about.
    """

    empty = {
        "verifications": 0,
        "agreed": 0,
        "disagreed": 0,
        "uncertain": 0,
        "objections": 0,
        "unavailable": 0,
        "agreed_while_arbiter_disagreed": 0,
    }
    if not verify:
        return empty

    answered = [check for _, check, _ in judged if check is not None]
    counts = {
        "verifications": len(answered),
        "agreed": sum(1 for c in answered if c.outcome is VerificationOutcome.AGREE),
        "disagreed": sum(
            1 for c in answered if c.outcome is VerificationOutcome.DISAGREE
        ),
        "uncertain": sum(
            1 for c in answered if c.outcome is VerificationOutcome.UNCERTAIN
        ),
        "objections": sum(len(c.objections) for c in answered),
        "unavailable": sum(
            1
            for _, check, _ in judged
            if check is None and arm is not VerificationArm.BLIND
        ),
        "agreed_while_arbiter_disagreed": sum(
            1
            for verdict, check, _ in judged
            if check is not None
            and check.outcome is VerificationOutcome.AGREE
            and verdict.arbiter_agreement is ArbiterAgreement.DISAGREED
        ),
    }

    if arm in (VerificationArm.BLIND, VerificationArm.BOTH):
        counts.update(_blind_counts(judged, counts["agreed"]))
    return counts


def _blind_counts(judged: list[tuple], informed_agreed: int) -> dict:
    """The blind arm's tally, the delta, and the facts it is really there for.

    `unanchored_cover` is the one that earns the arm its place. M4's arbiter
    speaks only the closed constraint vocabulary, so where a decision was
    recovered from prose it **abstains** - and on those facts an informed
    agreement is not a check at all, because the only thing that looked at
    them had already been shown the answer. A blind verdict is still a
    language model, so it does not make those facts verified; it is simply the
    one opinion present that did not see the primary's.

    `agrees_with` raises if the two arms saw different evidence, which is
    deliberate: a delta across two packages compares cleanly and means
    nothing.
    """

    answered = [(verdict, blind) for verdict, _, blind in judged if blind is not None]
    agreed = sum(1 for verdict, blind in answered if blind.agrees_with(verdict))

    return {
        "blind_verdicts": len(answered),
        "blind_agreed": agreed,
        "blind_unavailable": sum(1 for _, _, blind in judged if blind is None),
        "anchoring_delta": informed_agreed - agreed,
        "unanchored_cover": sum(
            1
            for verdict, blind in answered
            if verdict.arbiter_agreement is ArbiterAgreement.NOT_CHECKED
        ),
    }


def _arm_reported(arm: str, mode: str | None) -> str | None:
    """What the verifier was shown, or null when it was shown nothing.

    Null on a run that did not verify and on one nobody asked to verify: a
    question that did not arise has no answer, and reporting `informed` over a
    check that never happened describes one that did.

    **Not** null on an `unavailable` run. The arm was chosen and attempted,
    and *we tried to show it the verdict and could not reach it* is more
    informative than silence.
    """

    if mode is None or mode == VerificationMode.NOT_REQUESTED:
        return None
    return arm


def _verification_mode(
    verify: bool, arm: str, reasoned: int, judged: list[tuple]
) -> str | None:
    """Which of the three honest things this run can say about verification.

    `None` when no fact reached the stage. An uncovered release has nothing to
    verify, and both `performed` and `unavailable` would be false claims about
    it - the same shape as a style that was never resolved.

    A run where some facts were verified and some were not is `performed`.
    The per-fact detail is in the counts; the mode answers whether the second
    model was part of this run at all, and it was.

    **Which answers count depends on the arm**, and getting that wrong would
    be a quiet lie: a blind-only run has no informed opinion on any fact *by
    request*, and reading those absent verifications as failures would report
    a working run as `unavailable`.
    """

    if reasoned == 0:
        # Checked before the flag on purpose. A run with nothing to verify did
        # not decline the check, whatever was asked for, and saying
        # `not_requested` would attach the architect's name to a skip the
        # architecture caused.
        return None
    if not verify:
        return VerificationMode.NOT_REQUESTED

    informed = [check for _, check, _ in judged]
    blind = [verdict for _, _, verdict in judged]
    answered = {
        VerificationArm.INFORMED: informed,
        VerificationArm.BLIND: blind,
        VerificationArm.BOTH: informed + blind,
    }[VerificationArm(arm)]

    if any(answer is not None for answer in answered):
        return VerificationMode.PERFORMED
    return VerificationMode.UNAVAILABLE


def _release_confidence(classified: list[ClassifiedFact]) -> float:
    """How much of this release's validation can be relied on, as one number.

    The unweighted mean of the per-fact confidence over **every** fact,
    including the uncovered ones at 0.0. A release the component could say
    little about scores low, and that is the honest answer rather than a
    scoring artefact: a mean over the facts that happened to come out well
    would put a release where fourteen of fifteen facts went to review at the
    top.

    Unweighted because every weighting that could be applied here would be
    invented. A mean over numbers whose own arithmetic is published can be
    checked by hand from the output; anything cleverer would be the one value
    in the chain nobody downstream could re-derive.

    An empty release is 0.0, and the stage's `facts` count is what separates
    *nothing was validated* from *everything validated badly*. The next
    component excludes a release below 0.50 from its whole analysis, so the
    difference has to be visible beside the number.
    """

    if not classified:
        return 0.0
    return round(sum(fact.confidence for fact in classified) / len(classified), 4)


def _reasoning_counts(verdicts: list[PrimaryVerdict]) -> dict:
    """What the reasoning stage did, in the numbers a reader has to have.

    Three of these answer the question the run record exists to answer: how
    many of these verdicts had a model behind them at all. A run that fell to
    the arbiter for every fact and reported itself the same way as a normal
    run would be the exact failure Rule 7 forbids, so `from_arbiter` is
    published even when it is zero - and especially then.

    The agreement counts are the component's own research output: how often a
    free open-weights model and a deterministic table reach the same verdict
    on the cases the table can decide.
    """

    agreement = Counter(
        str(verdict.arbiter_agreement) if verdict.arbiter_agreement else "not_compared"
        for verdict in verdicts
    )
    return {
        "verdicts": len(verdicts),
        "from_cache": sum(1 for v in verdicts if v.cached),
        "from_model": sum(1 for v in verdicts if v.produced_by is VerdictSource.MODEL),
        "from_arbiter": sum(
            1 for v in verdicts if v.produced_by is VerdictSource.ARBITER
        ),
        "retried": sum(1 for v in verdicts if v.retried),
        "guard_rejections": sum(len(v.guard_failures) for v in verdicts),
        "insufficient_evidence": sum(
            1 for v in verdicts if v.verdict is Verdict.INSUFFICIENT_EVIDENCE
        ),
        **{f"arbiter_{name}": count for name, count in sorted(agreement.items())},
    }


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
        self._knowledge = knowledge
        self._evidence = evidence
        self._reasoning = reasoning
        self._verification = verification
        self._classification = classification
        self._review = review
        self._publishing = publishing

    def run(
        self,
        repository_id: str,
        release_id: str,
        decision_mode: str = DEFAULT_MODE,
        adr_repository_id: str | None = None,
        verify: bool = True,
        arm: str = VerificationArm.INFORMED,
    ) -> ValidationRunResult:
        """Validate one release of one repository.

        `release_id` is supplied by the caller rather than read from the
        recovered architecture: recovery identifies a release by commit, and
        commit hashes carry no order, which the validity intervals in the
        knowledge model require.

        `decision_mode` chooses where the decisions come from, and is recorded
        on the result. A mode that would supply nothing stops the run here,
        before any stage, because a validation with nothing to validate
        against publishes a graph that reads exactly like a clean one.

        `verify` turns the second model off for this run. It defaults to true,
        and turning it off is published as a skip with *that* reason rather
        than as an absent stage - a check nobody ran, rendered identically to
        a check that passed, is the one unacceptable way to make this
        optional. The verdicts themselves are not re-paid for on a later
        verifying run, because the cache is keyed on the evidence rather than
        on the run.

        `arm` chooses what the verifier is shown. `informed` is the default
        and the demonstration mode. `both` is three model calls a fact and is
        a measurement mode: the gap between the two agreement rates is the
        anchoring effect, measured instead of conceded.
        """

        run_id = uuid.uuid4().hex[:12]
        arm = VerificationArm(arm)
        architecture = self._architecture_reader.read(repository_id, release_id)

        decisions = self._knowledge.establish(
            SourceRequest(
                code_repository_id=repository_id,
                release_id=release_id,
                extracted_at=datetime.now(UTC),
                manifest_paths=architecture.manifest_paths,
                adr_repository_id=adr_repository_id,
            ),
            decision_mode,
        )

        stages: list[StageRecord] = []
        facts, stage, style = self._normalise(architecture)
        stages.append(stage)

        classified, reasoning_stages, verification_mode = self._validate_each(
            facts, repository_id, decisions, architecture, verify, arm
        )
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
            validation_confidence=_release_confidence(classified),
            style_resolved=style[0],
            style_source=style[1],
            verification_arm=_arm_reported(arm, verification_mode),
            verification_mode=verification_mode,
            decision_mode=decisions.mode,
        )

    def decision_sources(self, request: SourceRequest) -> dict:
        """What each decision mode would supply for one release.

        Exposed on the component rather than reached through the knowledge
        model directly, so the API composition root keeps one way in - the
        same reason the run is a method here and not nine calls in a route.
        """

        return self._knowledge.availability(request)

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

    def _validate_each(
        self,
        facts,
        repository_id: str,
        decisions,
        architecture,
        verify: bool = True,
        arm: str = VerificationArm.INFORMED,
    ) -> tuple[list[ClassifiedFact], list[StageRecord], str | None]:
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
        counts = {
            "resolved": 0,
            "uncovered": 0,
            "ambiguous": 0,
            "reasoned": 0,
            "unrelated_resolutions": 0,
        }
        classified: list[ClassifiedFact] = []
        verdicts: list[PrimaryVerdict] = []
        judged: list[tuple[PrimaryVerdict, Verification | None, object]] = []
        """Each reasoned fact's verdict, its verification and its blind verdict.

        Grouped rather than kept as parallel lists because both numbers this
        component exists to produce - agreement where the deterministic table
        disagreed, and the gap between the informed and blind arms - are
        properties of one fact's judgements *together*. Lists indexed in
        parallel desync the moment one gains an entry another did not, and the
        resulting figures would still look entirely plausible.
        """

        with knowledge, evidence, reasoning, verification, classification:
            for fact in facts:
                resolution, ran = _attempt(
                    knowledge, self._knowledge.resolve, fact, repository_id
                )
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
                        # Verification did not apply to this fact: it never
                        # reached a model, so there is no argument to audit
                        # and no cap to name for the absence of one.
                        None,
                    )
                    if not ran:
                        break
                    classified.append(result)
                    continue

                counts["resolved"] += 1
                package, ran = _attempt(
                    evidence, self._evidence.assemble, fact, resolution, architecture
                )
                if not ran:
                    break

                # The arbiter is computed here, beside the resolution it
                # reads, and handed to the reasoner. It is deliberately not
                # the reasoner's own call to make: a stage that could decide
                # when to consult the table could also decide to tell the
                # model what it said, and that would end the independence the
                # whole three-judge design rests on.
                verdict, ran = _attempt(
                    reasoning,
                    self._reasoning.judge,
                    package,
                    decide(fact, resolution.governing),
                )
                if not ran:
                    break
                verdicts.append(verdict)

                blind = None
                if verify and arm in (VerificationArm.INFORMED, VerificationArm.BOTH):
                    checked, ran = _attempt(
                        verification, self._verification.verify, verdict, package
                    )
                    if not ran:
                        break
                elif verify:
                    # A blind-only run. There is no informed opinion by
                    # request, which is not the same as one being unavailable.
                    checked = None
                else:
                    # Not asked for. `None` travels on exactly as an
                    # unreachable verifier's would, so classification caps the
                    # confidence by the one path it already has - and the
                    # reason the two are distinguishable is the stage note and
                    # the run's mode, never the per-fact value.
                    checked = None

                if verify and arm in (VerificationArm.BLIND, VerificationArm.BOTH):
                    blind, ran = _attempt(
                        verification, self._verification.verify_blind, package
                    )
                    if not ran:
                        break

                judged.append((verdict, checked, blind))
                counts["reasoned"] += 1
                result, ran = _attempt(
                    classification,
                    self._classification.classify,
                    fact,
                    resolution,
                    verdict,
                    checked,
                    per_fact_mode(verify, arm is VerificationArm.BLIND, checked),
                )
                if not ran:
                    break
                if verdict.verdict is Verdict.UNRELATED:
                    # A governing decision was found and the model says it does
                    # not bear on this pair, which is a measurement of the
                    # resolver rather than of the architecture. The rate
                    # belongs on the run; one occurrence buried in a fact says
                    # nothing.
                    counts["unrelated_resolutions"] += 1
                classified.append(result)

        unmatched = self._knowledge.rules_without_facts(
            repository_id, decisions.release_id, facts
        )
        knowledge.counts = {
            **decisions.counts(),
            **{k: counts[k] for k in ("resolved", "uncovered", "ambiguous")},
            "rules_without_facts": len(unmatched),
        }
        knowledge.note = (
            f"mode {decisions.mode}; "
            f"{decisions.in_force} decisions in force at this release"
        )
        if unmatched:
            # An observation about the architecture rather than about this
            # stage, so it goes in the warnings beside normalisation's.
            knowledge.warnings = tuple(
                f"decision '{decision_id}' is in force at this release and no "
                "observed dependency corresponds to it"
                for decision_id in unmatched
            )
        evidence.counts = {"packages": counts["resolved"]}
        reasoning.counts = _reasoning_counts(verdicts)
        verification.counts = _verification_counts(judged, verify, arm)
        classification.counts = {
            "facts": len(classified),
            # Published beside the confidence they are the mean of. A mean
            # over fifteen facts and a mean over one look identical without
            # the count, and the next component gates a whole release on it.
            "published": len([f for f in classified if f.route == Route.PUBLISH]),
            "review": len([f for f in classified if f.route == Route.REVIEW]),
            "capped": len([f for f in classified if f.score_trace.ceiling_applied]),
            "unrelated_resolutions": counts["unrelated_resolutions"],
        }

        if not facts:
            # Not one of these five was called. Reporting them as completed
            # would be the same lie as a stub reporting a completed pass: a
            # board of green stages over a run that validated nothing.
            for stage in group:
                if stage.status is StageStatus.COMPLETED:
                    stage.skip("normalisation produced no facts to validate")
            # No mode: nothing reached verification, so neither
            # `performed` nor `unavailable` is true of this run - and
            # `not_requested` would blame the architect for a skip the empty
            # architecture caused. The stage note carries the real reason.
            return classified, [stage.record() for stage in group], None

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

        mode = _verification_mode(verify, arm, counts["reasoned"], judged)
        if verification.status is StageStatus.COMPLETED and mode is not None:
            verification.note = VERIFICATION_NOTES[mode]
        if mode in (VerificationMode.NOT_REQUESTED, VerificationMode.UNAVAILABLE):
            # Skipped rather than completed, because nothing was verified -
            # and with the reason attached, because "nobody asked for this
            # check" and "this check could not run" are different findings
            # about a run and only the second one is actionable.
            verification.skip(VERIFICATION_NOTES[mode])

        return classified, [
            knowledge.record(),
            evidence.record(),
            reasoning.record(),
            verification.record(),
            classification.record(),
        ], mode

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
