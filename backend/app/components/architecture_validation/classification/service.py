"""Classification service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Turns a verdict and its verification into a bucket, a confidence and a route.

    Research module: M6.
"""

from app.domain.validated_architecture import ValidationBucket

from ..models import (
    ClassifiedFact,
    ObservedFact,
    PrimaryVerdict,
    Resolution,
    ScoreTrace,
    VerdictSource,
    Verification,
    VerificationMode,
)
from . import rules


class ClassificationService:
    """Turns a verdict and its verification into a bucket, a confidence and a route."""

    def classify(self, fact: ObservedFact, resolution: Resolution,
                 verdict: PrimaryVerdict | None,
                 verification: Verification | None,
                 verification_mode: VerificationMode | None) -> ClassifiedFact:
        """Assigns the final bucket, confidence and route for one fact.

        Two lookup tables and one threshold, all in plain code. The first maps
        a verdict to a bucket. The second caps the bucket by the tier of the
        source the decision came from, so weak evidence cannot produce a
        confident accusation.

        The ceiling is applied after the model has answered, not asked for in
        the prompt, so it holds even when the model is wrong.

        Emits the arithmetic behind the confidence value alongside it. A bare
        number invites one question that cannot otherwise be answered.

        `verification_mode` is this fact's own, not the run's. The run's
        answer is an aggregate computed after every fact is in, and
        `verification=None` means two different things - the architect did not
        ask, or the second model could not be reached - which cap alike and
        are reported apart.
        """

        if verdict is None:
            return self._unreasoned(fact, resolution)

        if resolution.governing is None:
            raise ValueError(
                f"Fact '{fact.fact_id}' has a verdict and no governing "
                "decision. The verdict was produced against that decision, so "
                "classifying it without one would apply no source ceiling at "
                "all."
            )

        decision = resolution.governing
        outcome = verification.outcome if verification is not None else None
        caps = rules.applicable(
            rules.CapContext(
                tier=decision.source_tier,
                inferred=rules.inferred(fact.quality),
                outcome=outcome,
                agreement=verdict.arbiter_agreement,
                verification_mode=(
                    verification_mode
                    if verification_mode is not VerificationMode.PERFORMED
                    else None
                ),
                produced_without_a_model=verdict.produced_by is VerdictSource.ARBITER,
            )
        )

        terms = rules.terms_for(decision.source_strength, outcome)
        cap = rules.binding(caps)
        score = rules.capped_confidence(terms, cap)
        bucket = rules.capped_bucket(rules.bucket_for(verdict.verdict), cap)
        held_back = (
            cap
            if score < rules.proposed(terms)
            or bucket is not rules.bucket_for(verdict.verdict)
            else None
        )

        return ClassifiedFact(
            fact_id=fact.fact_id,
            bucket=bucket,
            confidence=score,
            score_trace=ScoreTrace(
                terms=terms,
                total=score,
                ceiling_applied=held_back.name if held_back is not None else None,
            ),
            route=rules.route_for(bucket, score),
            governing_decision=decision.decision_id,
            source_tier=decision.source_tier,
            evidence_refs=verdict.cited_evidence_refs,
            model_calls=_model_calls(verdict, verification),
            produced_by=verdict.produced_by,
            verification_outcome=outcome,
            arbiter_agreement=verdict.arbiter_agreement,
            verdict=verdict,
            verification=verification,
            **_topology(fact),
        )

    def _unreasoned(self, fact: ObservedFact,
                    resolution: Resolution) -> ClassifiedFact:
        """One fact no model was asked about.

        Nothing was claimed, so there is nothing for a ceiling to reduce and
        the trace is empty rather than zero-valued: a term of 0.0 would read
        as a contribution that happened to be worth nothing.

        `UNCOVERED` is a finding and it publishes. It is also the cheapest
        output the component produces - the short-circuit happens before any
        evidence is assembled, which is why `model_calls` is zero and can be
        shown to be.
        """

        bucket = (
            ValidationBucket.UNCOVERED
            if resolution.uncovered
            else ValidationBucket.AMBIGUOUS
        )

        return ClassifiedFact(
            fact_id=fact.fact_id,
            bucket=bucket,
            confidence=0.0,
            score_trace=ScoreTrace(terms={}, total=0.0),
            route=rules.route_for(bucket, 0.0),
            governing_decision=(
                resolution.governing.decision_id if resolution.governing else None
            ),
            source_tier=(
                resolution.governing.source_tier if resolution.governing else None
            ),
            evidence_refs=(),
            model_calls=0,
            **_topology(fact),
        )


def _topology(fact: ObservedFact) -> dict:
    """Which relationship this verdict is about, in recovery's own ids.

    Copied onto the classified fact because the publisher is handed these and
    nothing else, and the alternative is joining two lists by `fact_id` on the
    way out - which is the join that putting the verdict on the edge exists to
    avoid.
    """

    return {
        "source_element_id": fact.subject.id,
        "target_element_id": fact.object.id,
        "relationship": fact.relationship,
        "attributes": dict(fact.attributes),
    }


def _model_calls(verdict: PrimaryVerdict,
                 verification: Verification | None) -> int:
    """How many times a model was actually called for this fact.

    Counted here rather than carried down from each stage because this is the
    first place that holds both answers, and the number is published per edge
    so that a reader can see which verdicts cost a call and which were settled
    by code.

    A cached answer is not a call, and a retry is two. Both matter: the first
    is what makes a second run of the same release nearly free, and the second
    is the cost of a guard rejecting an answer.
    """

    calls = 0
    if verdict.produced_by is VerdictSource.MODEL and not verdict.cached:
        calls += 2 if verdict.retried else 1
    if verification is not None and not verification.cached:
        calls += 2 if verification.retried else 1
    return calls


def per_fact_mode(verify: bool, blind_only: bool,
                  verification: Verification | None) -> VerificationMode:
    """Whether this fact's argument was audited, and if not, why not.

    Separate from the run's mode and deliberately so. The run's answer is an
    aggregate - *was the second model part of this run at all* - and it is
    computed once every fact is in. This one is about one argument, and it is
    needed while the loop is still running.

    The two can disagree without either being wrong. A blind-only run reports
    `performed` for the run, because a second model did run, while every fact
    in it is unaudited: a verdict reached without seeing the argument is not a
    check on that argument.

    `blind_only` is checked before `verify` for the reason the run-level
    version checks its own order carefully. A blind-only run has no informed
    opinion on any fact **by request**, and reading those absent checks as
    failures reports a working run as a broken one.
    """

    if blind_only or not verify:
        return VerificationMode.NOT_REQUESTED
    if verification is not None:
        return VerificationMode.PERFORMED
    return VerificationMode.UNAVAILABLE
