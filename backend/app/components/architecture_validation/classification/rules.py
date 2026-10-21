"""The classification tables.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    Every rule this subcomponent applies, as data, in one file.

    It is a separate module from the service because the tables are the thing
    a reviewer reads. A reader who opens this file and finds six data
    structures and no control flow can check the claim the component rests on
    - that a weak source cannot produce a strong conclusion - without reading
    any code at all. Mixed into the service, the same tables become six
    dictionaries somewhere inside a method.

    Nothing here consults a model, a file or a clock.
"""

from dataclasses import dataclass

from app.domain.recovered_architecture import EvidenceQuality
from app.domain.validated_architecture import ValidationBucket

from ..models import (
    ArbiterAgreement,
    EvidenceStrength,
    Route,
    SourceTier,
    Verdict,
    VerificationMode,
    VerificationOutcome,
)
from .models import PUBLISH_THRESHOLD, Cap

TERM_VERDICT_BASE = 0.50
"""What a verdict is worth before anything about its evidence is considered.

Half, so that the source and the audit together can account for the other
half. Hand-set, like every number in this file, and unswept.
"""

TERM_SOURCE_STRENGTH = {
    EvidenceStrength.AUTHORITATIVE: 0.25,
    EvidenceStrength.SUPPORTING: 0.15,
    EvidenceStrength.WEAK: 0.05,
}
"""What the strength of the governing decision's source adds.

Keyed on strength while the *ceiling* is keyed on tier, and the two are not
in competition: the ceiling has to be re-derivable from the published output,
which carries `source_tier` and not strength, whereas a term is published by
name in the trace beside its value.
"""

TERM_VERIFICATION_AGREEMENT = 0.10
"""What a second model finding no fault in the argument adds.

One term, and it is the only thing agreement is ever worth. The arbiter
agreeing adds nothing at all: a deterministic table that cannot hallucinate
is a check against invention, not a second opinion whose assent is evidence.
"""

MAXIMUM_CONFIDENCE = TERM_VERDICT_BASE + 0.25 + TERM_VERIFICATION_AGREEMENT
"""0.85, and nothing in this component ever publishes more.

Not an oversight. The remaining 0.15 is what cannot be established by this
method at all: an uncalibrated score over an architecture nobody has labelled.
A scheme whose best case is 1.0 would be claiming certainty it has no way to
reach.
"""


ASSERTION_RANK = {
    ValidationBucket.CONFIRMED: 3,
    ValidationBucket.CONTRADICTED: 3,
    ValidationBucket.AMBIGUOUS: 2,
    ValidationBucket.NEEDS_REVIEW: 1,
    ValidationBucket.INSUFFICIENT_EVIDENCE: 1,
    ValidationBucket.CONVENTION_DEVIATION: 1,
    ValidationBucket.UNCOVERED: 0,
}
"""How strong a claim each bucket makes, which is what a ceiling compares.

Three bands rather than seven places. `CONFIRMED` and `CONTRADICTED` are both
assertions about conformance and rank together: confirming against a stale
rule is as wrong as accusing against one, so a ceiling that stops the
accusation has to stop the confirmation too. `CONVENTION_DEVIATION` ranks with
`NEEDS_REVIEW` rather than above it - it is the same refusal to assert, said
in the vocabulary of conventions - and without that, a tier-5 ceiling would
come out stronger than a tier-3 one.

`UNCOVERED` is below everything and is never capped. There is no claim in it
to reduce.
"""

VERDICT_BUCKET = {
    Verdict.CONFIRMS: ValidationBucket.CONFIRMED,
    Verdict.CONTRADICTS: ValidationBucket.CONTRADICTED,
    Verdict.PARTIALLY_CONFIRMS: ValidationBucket.AMBIGUOUS,
    Verdict.UNRELATED: ValidationBucket.INSUFFICIENT_EVIDENCE,
    Verdict.INSUFFICIENT_EVIDENCE: ValidationBucket.INSUFFICIENT_EVIDENCE,
}
"""Five verdicts to seven buckets, exhaustively.

`partially_confirms` becomes `AMBIGUOUS` rather than an eighth bucket:
`ValidationRollup` has four counters, so a bucket nothing counts would be
invisible in every per-element summary the next component reads. The detail
survives - the fact still carries the verdict, the reasoning and the
citations.

`unrelated` means a governing decision was found and the model says it has
nothing to do with this relationship. That is a statement about the
*resolution*, not about the architecture, which is why it is also counted on
the stage.
"""

TIER_CAP = {
    SourceTier.DECISION_RECORD: None,
    SourceTier.EXECUTABLE_CONFIG: None,
    SourceTier.DOCUMENTATION: Cap(
        "source_tier_3_documentation", ValidationBucket.NEEDS_REVIEW, 0.60
    ),
    SourceTier.HISTORY: Cap(
        "source_tier_4_history", ValidationBucket.NEEDS_REVIEW, 0.50
    ),
    SourceTier.CONVENTION: Cap(
        "source_tier_5_convention", ValidationBucket.CONVENTION_DEVIATION, 0.35
    ),
}
"""The ceiling table, and the research claim this component is defending.

**A ratified record is exempt from every row of it**, which is the third row
of CLS-D1's table and was missing from this code until M7 was built. The
exemption is the table's own premise being satisfied rather than a hole in it:
the ceiling exists because nobody has vouched for the rule, and once a named
architect has, at a recorded time, the condition it protects against is gone.

What keeps that from being a back door is that it takes a person.
`extraction_method` stays `reconstructed` for the record's life and
`ratified_by` sits beside it, so a confirmed rule is always distinguishable
from a written one; and there is no code path from a run to a confirmation.


Tiers 1 and 2 have no cap: both may state a violation. **Tier 2 reaching the
top is the finding**, and it has to be defensible out loud. For a structural
rule - may this service call that one - a network policy is unambiguous,
versioned, current and cluster-enforced. A prose decision record is none of
those four. Decision records are the gold standard for *rationale*, not for
rules.

A missing tier raises rather than defaulting. `SourceTier` is closed at five
values and a sixth appearing should stop the run, not quietly take the most
permissive row.
"""

OBSERVATION_CAP = Cap(
    "observation_inferred", ValidationBucket.NEEDS_REVIEW, 0.60
)
"""An element-to-element dependency that recovery inferred rather than read.

The same ceiling as a tier-3 source, because both describe the same
situation - probably true, not stated anywhere definitive - and one mechanism
covering both is one less thing to explain.

It caps; it never weights. `EvidenceQuality` is a two-value category, and
turning `INFERRED` into 0.6 would put the single fabricated number inside an
otherwise checkable calculation.
"""

VERIFICATION_CAP = {
    VerificationOutcome.DISAGREE: Cap(
        "verification_disagree", ValidationBucket.INSUFFICIENT_EVIDENCE, 0.45
    ),
    VerificationOutcome.UNCERTAIN: Cap(
        "verification_uncertain", ValidationBucket.NEEDS_REVIEW, 0.60
    ),
}
"""Disagreement caps the outcome; it never raises it, and never flips it.

`AGREE` is absent on purpose: agreement is a term, not the lack of a cap
being worth something extra. A fault found in the argument is the stronger
signal of the two, which is why the two values that appear here are the two
that lower the result.
"""

ARBITER_CAP = {
    ArbiterAgreement.DISAGREED: Cap(
        "arbiter_disagreed", ValidationBucket.NEEDS_REVIEW, 0.60
    ),
}
"""A deterministic table disagreeing with the model caps the fact.

`NOT_COMPARABLE` and `NOT_CHECKED` are absent: an abstention is not evidence
against a verdict. An oracle that answers everything is not an oracle.
"""

UNVERIFIED_CAP = {
    VerificationMode.NOT_REQUESTED: Cap("unverified_by_choice", None, 0.65),
    VerificationMode.UNAVAILABLE: Cap("unverified_unavailable", None, 0.65),
}
"""Two names for one ceiling, and the two names are the point.

Same value, because an unaudited argument is worth the same either way. Two
names, because one is a decision about how this run was requested and the
other is a fault in it - and a reader looking at fifteen facts capped
`unverified_unavailable` knows the provider was down, where fifteen capped
`unverified_by_choice` tells them the run was deliberately cheap.

Neither caps the bucket. An unverified confirmation is still a confirmation;
it is simply below the publish threshold, so it reaches a person instead of a
report.
"""

NO_MODEL_CAP = Cap("verdict_without_a_model", None, 0.60)
"""A verdict the deterministic table produced on its own.

The ladder's last rung decides every governed fact with no model reachable at
all. That is a real verdict and it is published as one - with the arbiter
named as its author and capped here, because the rule extraction above it is
the only thing holding it up.
"""


REJECTED_CAP = Cap("every_answer_rejected", None, 0.0)
"""A fact whose every model answer was thrown out by a guard.

The twin of `NO_MODEL_CAP` from the other direction. There, nothing answered
and the table decided; here a model answered twice and neither answer could
be used, so nothing was concluded at all - and `ASSERTION_RANK` already puts
the resulting bucket at the bottom.

**Zero rather than a low number**, which is the same answer `UNCOVERED`
already gets: confidence is confidence in a claim, and where there is no
claim there is nothing to be confident about. Without this row such a fact
scored `verdict_base` plus its source strength plus a verification agreement
term - 0.85, the maximum this component can publish, beside a bucket that
declines to conclude. The bucket was honest and the number was not.

It caps the value and not the bucket, because the bucket is already
`INSUFFICIENT_EVIDENCE` and promoting it to a ceiling's own name would be
inventing a finding.
"""


@dataclass(frozen=True)
class CapContext:
    """Everything the caps read, and nothing else.

    A small shape rather than five parameters repeated on every entry in
    `CAPS`, so that adding a cap is one row in one list.
    """

    tier: SourceTier | None
    ratified: bool
    inferred: bool
    outcome: VerificationOutcome | None
    agreement: ArbiterAgreement | None
    verification_mode: VerificationMode | None
    produced_without_a_model: bool
    every_answer_rejected: bool = False


CAPS = (
    lambda ctx: None if ctx.ratified else _tier_cap(ctx.tier),
    lambda ctx: OBSERVATION_CAP if ctx.inferred else None,
    lambda ctx: VERIFICATION_CAP.get(ctx.outcome),
    lambda ctx: ARBITER_CAP.get(ctx.agreement),
    lambda ctx: UNVERIFIED_CAP.get(ctx.verification_mode),
    lambda ctx: NO_MODEL_CAP if ctx.produced_without_a_model else None,
    lambda ctx: REJECTED_CAP if ctx.every_answer_rejected else None,
)
"""The seven caps, each answering with a cap or with `None` for *does not apply*.

Several apply at once on most facts. They are composed by minimum rather than
applied in sequence, so the answer cannot depend on the order of this tuple -
which is the order most likely to be edited by somebody in a hurry.
"""


def _tier_cap(tier: SourceTier | None) -> Cap | None:
    """The ceiling the governing decision's tier imposes, if it imposes one.

    A missing tier raises rather than defaulting, because `SourceTier` is
    closed at five values and a sixth appearing should stop the run instead of
    quietly taking the most permissive row.
    """

    return TIER_CAP[tier] if tier is not None else None


def applicable(context: CapContext) -> tuple[Cap, ...]:
    """Every cap that applies to one fact."""

    found = (cap(context) for cap in CAPS)
    return tuple(cap for cap in found if cap is not None)


def binding(caps: tuple[Cap, ...]) -> Cap | None:
    """Which single cap holds this fact back, and decides both halves of it.

    The lowest confidence ceiling wins. Ties are broken by the more
    restrictive bucket and then by name - deliberately not by position in
    `CAPS`, because then shuffling that tuple could change the answer and the
    guarantee above would be untestable.

    One cap decides the bucket as well as the number, rather than the bucket
    being capped by every applicable ceiling in turn. Three ceilings that each
    refuse to assert - `needs_review`, `insufficient_evidence` and
    `convention_deviation` - rank equally, so taking a minimum over them
    returns whichever came first and the answer moves when the list is
    reordered. That is the order dependency this file claims not to have, and
    it is what `test_shuffling_the_cap_list_changes_nothing` caught on the
    first run.

    It also makes the trace honest in a way the other arrangement could not:
    the name in `ceiling_applied` explains the published number *and* the
    published bucket, instead of naming one cap while a different one quietly
    decided what was concluded.
    """

    if not caps:
        return None
    return min(caps, key=lambda cap: (cap.confidence, _rank(cap.bucket), cap.name))


def capped_bucket(bucket: ValidationBucket, cap: Cap | None) -> ValidationBucket:
    """The bucket, reduced to what the binding cap allows.

    A cap never raises a bucket. A verdict of `unrelated` under a tier-5
    ceiling stays `INSUFFICIENT_EVIDENCE` - it was already claiming nothing,
    and promoting it to the ceiling's own name would be inventing a finding.
    """

    if cap is None or cap.bucket is None:
        return bucket
    if ASSERTION_RANK[bucket] > ASSERTION_RANK[cap.bucket]:
        return cap.bucket
    return bucket


def proposed(terms: dict) -> float:
    """What the terms add up to before any ceiling is applied."""

    return round(sum(terms.values()), 10)


def capped_confidence(terms: dict, cap: Cap | None) -> float:
    """What the terms add up to, or the binding ceiling, whichever is lower.

    Caps do not compound. Two caps at 0.6 give 0.6, not 0.36: neither of them
    claimed the fact was that weak, and inventing a number lower than anybody
    argued for is as dishonest as inventing a higher one.
    """

    if cap is None:
        return proposed(terms)
    return min(proposed(terms), cap.confidence)


def bucket_for(verdict: Verdict) -> ValidationBucket:
    """The bucket a verdict maps to, before any ceiling."""

    return VERDICT_BUCKET[verdict]


def route_for(bucket: ValidationBucket, score: float) -> Route:
    """Who looks at this fact next.

    `UNCOVERED` publishes whatever its score: it is a finding reached with no
    model at all - the architecture has a dependency that nothing in the
    recorded intent speaks to - and routing it to a queue would bury the one
    result that costs nothing to produce.

    Everything that is not an assertion goes to a person. A bucket that
    already declines to conclude has nothing to publish.
    """

    if bucket is ValidationBucket.UNCOVERED:
        return Route.PUBLISH
    if ASSERTION_RANK[bucket] < 3:
        return Route.REVIEW
    return Route.PUBLISH if score >= PUBLISH_THRESHOLD else Route.REVIEW


def terms_for(
    strength: EvidenceStrength | None,
    outcome: VerificationOutcome | None,
    asserts: bool = True,
) -> dict:
    """The named contributions behind one confidence value.

    Insertion-ordered, because the dict is rendered top to bottom on a screen
    and the order it is built in is the order the argument is made: the
    verdict exists, its source is this strong, and a second model found no
    fault in it.

    `asserts` is whether the verdict claims anything about the architecture.
    When it does not, **the agreement term is not awarded**, and that is a
    correctness fix rather than a tuning choice: the verifier is shown the
    primary verdict and asked what is wrong with the argument, so agreeing
    with `insufficient_evidence` means *there is indeed no argument here*. A
    second model confirming that nothing was established is not corroboration
    of a finding, and scoring it as `verification_agreement` put the word
    agreement on a screen next to a fact nobody concluded anything about.
    """

    terms = {"verdict_base": TERM_VERDICT_BASE}
    if strength is not None:
        terms[f"source_strength_{strength.value}"] = TERM_SOURCE_STRENGTH[strength]
    if asserts and outcome is VerificationOutcome.AGREE:
        terms["verification_agreement"] = TERM_VERIFICATION_AGREEMENT
    return terms


def asserts_something(bucket: ValidationBucket) -> bool:
    """Whether a bucket claims anything about the architecture.

    Read off `ASSERTION_RANK` rather than listed again, so a bucket added to
    one and forgotten in the other is impossible. Rank 2 and above assert:
    `AMBIGUOUS` says the dependency is permitted with a condition unmet, which
    is a claim. Rank 1 and below decline to conclude.
    """

    return ASSERTION_RANK[bucket] >= 2


def _rank(bucket: ValidationBucket | None) -> int:
    """Where a ceiling sits, with *no bucket ceiling* ranked above every one.

    A cap that limits only the number must not win a tie against one that
    also limits the claim, or it would shadow it.
    """

    if bucket is None:
        return max(ASSERTION_RANK.values()) + 1
    return ASSERTION_RANK[bucket]


def inferred(quality: str) -> bool:
    """Whether recovery inferred this dependency rather than reading it."""

    return quality == EvidenceQuality.INFERRED
