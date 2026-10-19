"""The validation summary.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    The block that answers *why should I believe this?*, written into the
    published document rather than computed by whoever reads it.

    That is the whole point of it being here. The screen, the consuming
    component and the dissertation all quote one set of numbers, and a figure
    that appears in a report can be traced to the artifact it came from. Three
    readers each doing their own arithmetic is three answers to one question,
    and the disagreement surfaces in whichever one somebody is looking at.

    Every number is read off the stages the run already recorded. Nothing is
    recounted from the facts, because the stages are where the counting
    happened and a second count is a second opinion.
"""

from ..models import StageRecord, ValidationRunResult


def build(run: ValidationRunResult) -> dict:
    """The summary block for one completed run."""

    classification = _counts(run, "classification")
    reasoning = _counts(run, "validation_reasoning")
    verification = _counts(run, "independent_verification")
    knowledge = _counts(run, "decision_knowledge")

    return {
        "facts": classification.get("facts", 0),
        "published": classification.get("published", 0),
        "review": classification.get("review", 0),
        "capped": classification.get("capped", 0),
        "buckets": _buckets(run),
        # The three-judges line, which is the reason the badge fields travel.
        "verdicts_from_a_model": reasoning.get("from_model", 0),
        "verdicts_from_the_arbiter": reasoning.get("from_arbiter", 0),
        "arbiter_agreed": reasoning.get("arbiter_agreed", 0),
        "arbiter_disagreed": reasoning.get("arbiter_disagreed", 0),
        "verification_mode": run.verification_mode,
        "verification_arm": run.verification_arm,
        "verified": verification.get("verifications", 0),
        "verifier_agreed": verification.get("agreed", 0),
        # Published even when it is zero, and especially then: a corpus whose
        # intent is total has nothing uncovered, and that is a finding about
        # the subject system rather than a gap in the output.
        "uncovered": knowledge.get("uncovered", 0),
        "intervals_closed": knowledge.get("intervals_closed", 0),
        "unrelated_resolutions": classification.get("unrelated_resolutions", 0),
        "decision_mode": run.decision_mode,
        "model_calls": run.model_calls,
        "validation_confidence": run.validation_confidence,
    }


def _counts(run: ValidationRunResult, name: str) -> dict:
    """One stage's counts, or an empty dict when the stage did not run.

    Empty rather than raising. A stage that was skipped reported no counts,
    and a summary that cannot be built for a partial run would mean the
    partial runs - the ones worth explaining - are the ones with no summary.
    """

    stage: StageRecord | None = next(
        (record for record in run.stages if record.name == name), None
    )
    return dict(stage.counts) if stage is not None else {}


def _buckets(run: ValidationRunResult) -> dict:
    """How many facts reached each bucket.

    The one count taken over the facts rather than off a stage, because no
    stage records it: the classification stage counts what it routed, not what
    it concluded. Sorted so two runs of one release produce identical bytes.
    """

    buckets: dict[str, int] = {}
    for fact in run.facts:
        buckets[str(fact.bucket)] = buckets.get(str(fact.bucket), 0) + 1
    return dict(sorted(buckets.items()))
