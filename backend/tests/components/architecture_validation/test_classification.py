"""M6 - classification, confidence and the ceiling that makes the rest safe.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    Every input here is built by hand. `classify` is a pure function over
    frozen shapes, so a test can hold the model's answer completely fixed and
    vary one thing about its evidence - which is the only way to assert that
    the ceiling is doing anything at all.

    The three rows marked THE CEILING are the most valuable lines in the file.
"""

import inspect
import random
from datetime import UTC, datetime

import pytest

from app.components.architecture_validation.classification import (
    ClassificationService,
    Route,
    per_fact_mode,
    rules,
)
from app.components.architecture_validation.classification.models import (
    PUBLISH_THRESHOLD,
)
from app.components.architecture_validation.models import (
    ArbiterAgreement,
    ConstraintKind,
    DecisionRecord,
    EvidenceStrength,
    ExtractionMethod,
    FactEndpoint,
    GuardFailure,
    ObservedFact,
    PrimaryVerdict,
    RelationshipKind,
    Resolution,
    SourceTier,
    Verdict,
    VerdictSource,
    Verification,
    VerificationMode,
    VerificationOutcome,
)
from app.domain.recovered_architecture import EvidenceQuality
from app.domain.validated_architecture import ValidationBucket

STRENGTH_FOR = {
    SourceTier.DECISION_RECORD: EvidenceStrength.AUTHORITATIVE,
    SourceTier.EXECUTABLE_CONFIG: EvidenceStrength.AUTHORITATIVE,
    SourceTier.DOCUMENTATION: EvidenceStrength.SUPPORTING,
    SourceTier.HISTORY: EvidenceStrength.SUPPORTING,
    SourceTier.CONVENTION: EvidenceStrength.WEAK,
}
"""The strength a record of each tier normally carries.

Used so that a test varying the tier varies the realistic pair rather than an
impossible one - a tier-5 convention marked `authoritative` would be a record
no adapter produces. The two fields stay separate in the model because the
ceiling reads one and the score reads the other.
"""


def fact(quality=EvidenceQuality.CONFIRMED) -> ObservedFact:
    return ObservedFact(
        fact_id="f1",
        release_id="v0.10.0",
        release_sort_key=(0, 0, 10, 0, 0, 4, 0, 1, 0),
        subject=FactEndpoint(id="c:1", name="frontend", canonical="frontend"),
        relationship=RelationshipKind.COMMUNICATES_WITH,
        object=FactEndpoint(id="c:2", name="cartservice", canonical="cartservice"),
        style_resolved="microservices",
        style_source="c1",
        quality=quality,
    )


def decision(tier=SourceTier.EXECUTABLE_CONFIG, strength=None) -> DecisionRecord:
    return DecisionRecord(
        decision_id="rule-frontend-cartservice",
        subject="frontend",
        constraint=ConstraintKind.MAY_CALL,
        object="cartservice",
        valid_from="v0.9.0",
        valid_to=None,
        source="kubernetes_network_policy",
        source_repository="online-boutique",
        source_tier=tier,
        source_strength=strength or STRENGTH_FOR[tier],
        source_ref="kubernetes-manifests/network-policies.yaml",
        extraction_method=ExtractionMethod.DECLARED,
        extracted_at=datetime(2026, 10, 14, tzinfo=UTC),
    )


def verdict(
    concluded=Verdict.CONFIRMS,
    agreement=ArbiterAgreement.AGREED,
    produced_by=VerdictSource.MODEL,
    cached=False,
    retried=False,
    live_calls=None,
    guard_failures=(),
) -> PrimaryVerdict:
    # The arbiter's rung is reached because nothing answered, so a verdict it
    # produced cost no call. Defaulting it here keeps every caller honest
    # without each of them having to say so.
    if live_calls is None:
        live_calls = 0 if produced_by is VerdictSource.ARBITER else 1

    return PrimaryVerdict(
        fact_id="f1",
        verdict=concluded,
        reasoning="the governing rule names this pair",
        cited_evidence_refs=("rule-frontend-cartservice",),
        model_id="fake/reasoner-1",
        prompt_version="primary_verdict@1",
        evidence_hash="a" * 64,
        cached=cached,
        retried=retried,
        live_calls=live_calls,
        guard_failures=guard_failures,
        produced_by=produced_by,
        arbiter_agreement=agreement,
    )


def verification(
    outcome=VerificationOutcome.AGREE, cached=False, retried=False, live_calls=1
) -> Verification:
    return Verification(
        fact_id="f1",
        outcome=outcome,
        mechanism="critical-reframing",
        reasoning="the cited rule does say what the verdict claims",
        model_id="fake/verifier-1",
        prompt_version="critical_reframing@1",
        cached=cached,
        live_calls=live_calls,
        evidence_hash="a" * 64,
        retried=retried,
    )


def classified(
    concluded=Verdict.CONFIRMS,
    outcome=VerificationOutcome.AGREE,
    tier=SourceTier.EXECUTABLE_CONFIG,
    strength=None,
    quality=EvidenceQuality.CONFIRMED,
    agreement=ArbiterAgreement.AGREED,
    produced_by=VerdictSource.MODEL,
    mode=VerificationMode.PERFORMED,
    audited=True,
):
    """One classified fact, with exactly one thing varied per call."""

    return ClassificationService().classify(
        fact(quality),
        Resolution(governing=decision(tier, strength)),
        verdict(concluded, agreement, produced_by),
        verification(outcome) if audited else None,
        mode,
    )


class TestTheTwoTables:
    """CLS-1 and CLS-2. The mappings, exhaustively, because a mapping with a
    hole in it defaults to whatever the code happens to do."""

    def test_every_verdict_has_a_bucket(self):
        assert set(rules.VERDICT_BUCKET) == set(Verdict)

    def test_every_bucket_it_maps_to_is_a_real_bucket(self):
        assert set(rules.VERDICT_BUCKET.values()) <= set(ValidationBucket)

    def test_an_unknown_verdict_raises_rather_than_defaulting(self):
        """A sixth verdict value appearing should stop the run. Defaulting
        would classify it as whatever the most permissive row happens to be,
        and nothing would say so."""

        with pytest.raises(KeyError):
            rules.bucket_for("a_verdict_nobody_declared")

    def test_every_tier_has_a_cap_row(self):
        assert set(rules.TIER_CAP) == set(SourceTier)

    def test_every_bucket_has_an_assertion_rank(self):
        """The ranks are what every ceiling comparison goes through, so a
        bucket missing from them would raise at classification time."""

        assert set(rules.ASSERTION_RANK) == set(ValidationBucket)

    def test_only_the_two_executable_tiers_may_state_a_violation(self):
        """CLS-D1, as the table rather than as a paragraph."""

        uncapped = [tier for tier, cap in rules.TIER_CAP.items() if cap is None]

        assert uncapped == [SourceTier.DECISION_RECORD, SourceTier.EXECUTABLE_CONFIG]


class TestTheBucketTruthTable:
    """CLS-7 and CLS-9. One row per distinct, meaningful behaviour."""

    @pytest.mark.parametrize(
        "concluded,outcome,tier,expected_bucket,expected_route",
        [
            # --- the normal paths ---
            (Verdict.CONFIRMS, VerificationOutcome.AGREE,
             SourceTier.EXECUTABLE_CONFIG,
             ValidationBucket.CONFIRMED, Route.PUBLISH),
            (Verdict.CONTRADICTS, VerificationOutcome.AGREE,
             SourceTier.DECISION_RECORD,
             ValidationBucket.CONTRADICTED, Route.PUBLISH),
            (Verdict.PARTIALLY_CONFIRMS, VerificationOutcome.AGREE,
             SourceTier.DECISION_RECORD,
             ValidationBucket.AMBIGUOUS, Route.REVIEW),
            (Verdict.UNRELATED, VerificationOutcome.AGREE,
             SourceTier.DECISION_RECORD,
             ValidationBucket.INSUFFICIENT_EVIDENCE, Route.REVIEW),
            (Verdict.INSUFFICIENT_EVIDENCE, VerificationOutcome.UNCERTAIN,
             SourceTier.DECISION_RECORD,
             ValidationBucket.INSUFFICIENT_EVIDENCE, Route.REVIEW),

            # --- disagreement must never publish a strong claim ---
            (Verdict.CONTRADICTS, VerificationOutcome.DISAGREE,
             SourceTier.DECISION_RECORD,
             ValidationBucket.INSUFFICIENT_EVIDENCE, Route.REVIEW),
            (Verdict.CONTRADICTS, VerificationOutcome.UNCERTAIN,
             SourceTier.DECISION_RECORD,
             ValidationBucket.NEEDS_REVIEW, Route.REVIEW),

            # --- THE CEILING: identical model output, weaker source ---
            (Verdict.CONTRADICTS, VerificationOutcome.AGREE,
             SourceTier.DOCUMENTATION,
             ValidationBucket.NEEDS_REVIEW, Route.REVIEW),
            (Verdict.CONTRADICTS, VerificationOutcome.AGREE,
             SourceTier.HISTORY,
             ValidationBucket.NEEDS_REVIEW, Route.REVIEW),
            (Verdict.CONTRADICTS, VerificationOutcome.AGREE,
             SourceTier.CONVENTION,
             ValidationBucket.CONVENTION_DEVIATION, Route.REVIEW),
        ],
    )
    def test_the_bucket_truth_table(
        self, concluded, outcome, tier, expected_bucket, expected_route
    ):
        result = classified(concluded=concluded, outcome=outcome, tier=tier)

        assert result.bucket == expected_bucket
        assert result.route == expected_route

    def test_the_ceiling_rows_hold_the_model_output_identical(self):
        """What makes the three rows above evidence rather than coincidence:
        the verdict, the reasoning and the citations are the same object in
        all three, and only the tier moves."""

        strong = classified(
            concluded=Verdict.CONTRADICTS, tier=SourceTier.EXECUTABLE_CONFIG
        )
        weak = classified(
            concluded=Verdict.CONTRADICTS, tier=SourceTier.CONVENTION
        )

        assert strong.bucket == ValidationBucket.CONTRADICTED
        assert weak.bucket == ValidationBucket.CONVENTION_DEVIATION
        assert weak.confidence < strong.confidence

    @pytest.mark.parametrize("concluded", list(Verdict))
    def test_a_tier_4_source_can_never_produce_a_contradiction(self, concluded):
        """D21, as a standing guarantee rather than a hope. Every verdict the
        model can return, against a rule read out of commit history."""

        result = classified(concluded=concluded, tier=SourceTier.HISTORY)

        assert result.bucket != ValidationBucket.CONTRADICTED

    @pytest.mark.parametrize("concluded", list(Verdict))
    def test_a_weak_source_can_never_publish(self, concluded):
        """The route half of the same claim: a tier-5 fact always reaches a
        person, whatever the model concluded about it."""

        assert classified(concluded=concluded, tier=SourceTier.CONVENTION).route == (
            Route.REVIEW
        )

    def test_a_cap_never_raises_a_bucket(self):
        """`unrelated` is already claiming nothing, so a ceiling has nothing
        to reduce - it must not be *promoted* to the ceiling's own value."""

        result = classified(
            concluded=Verdict.UNRELATED, tier=SourceTier.CONVENTION
        )

        assert result.bucket == ValidationBucket.INSUFFICIENT_EVIDENCE


class TestTheCapsComposing:
    """CLS-3 and CLS-D6. Four caps, several at once, and the order that must
    not matter."""

    def test_an_inferred_observation_caps_at_needs_review(self):
        """CLS-D4. A dependency recovery guessed from folder structure sits
        where a design document sits."""

        result = classified(
            concluded=Verdict.CONTRADICTS, quality=EvidenceQuality.INFERRED
        )

        assert result.bucket == ValidationBucket.NEEDS_REVIEW
        assert result.score_trace.ceiling_applied == "observation_inferred"

    def test_a_confirmed_observation_does_not_cap(self):
        """The contrast, so the test above is not passing on something else."""

        result = classified(
            concluded=Verdict.CONTRADICTS, quality=EvidenceQuality.CONFIRMED
        )

        assert result.bucket == ValidationBucket.CONTRADICTED
        assert result.score_trace.ceiling_applied is None

    def test_arbiter_disagreement_caps_and_does_not_overwrite_the_verdict(self):
        """RSN-D6 reaching the place it finally shows. The model said
        `confirms` and the table said otherwise; the published verdict is
        still the model's, capped."""

        result = classified(agreement=ArbiterAgreement.DISAGREED)

        assert result.bucket == ValidationBucket.NEEDS_REVIEW
        assert result.score_trace.ceiling_applied == "arbiter_disagreed"

    @pytest.mark.parametrize(
        "agreement",
        [ArbiterAgreement.NOT_COMPARABLE, ArbiterAgreement.NOT_CHECKED],
    )
    def test_an_abstaining_arbiter_does_not_cap(self, agreement):
        """An oracle that answers everything is not an oracle, and an
        abstention is not evidence against a verdict."""

        assert classified(agreement=agreement).score_trace.ceiling_applied is None

    def test_the_lowest_of_two_caps_binds_and_is_the_one_named(self):
        """Two caps apply here: tier 4 at 0.50 and an uncertain verification
        at 0.60. The published number is the lower, and the trace names the
        cap that produced it rather than the one that happened to be checked
        first."""

        result = classified(
            concluded=Verdict.CONTRADICTS,
            tier=SourceTier.HISTORY,
            outcome=VerificationOutcome.UNCERTAIN,
        )

        assert result.confidence == 0.50
        assert result.score_trace.ceiling_applied == "source_tier_4_history"

    def test_caps_do_not_compound(self):
        """Three caps that each allow 0.60 allow 0.60, not 0.216. None of
        them claimed the fact was that weak."""

        result = classified(
            concluded=Verdict.CONTRADICTS,
            tier=SourceTier.DOCUMENTATION,
            quality=EvidenceQuality.INFERRED,
            outcome=VerificationOutcome.UNCERTAIN,
        )

        assert result.confidence == 0.60

    def test_shuffling_the_cap_list_changes_nothing(self):
        """What protects every test above from a refactor.

        Rewriting the minimum into a chain of `if` statements leaves all of
        them passing and reintroduces a dependency on the order the code is
        written in. This is the only test that fails.
        """

        baseline = classified(
            concluded=Verdict.CONTRADICTS,
            tier=SourceTier.CONVENTION,
            quality=EvidenceQuality.INFERRED,
            outcome=VerificationOutcome.DISAGREE,
            agreement=ArbiterAgreement.DISAGREED,
        )
        shuffled = list(rules.CAPS)
        random.shuffle(shuffled)
        original = rules.CAPS

        try:
            rules.CAPS = tuple(shuffled)
            assert classified(
                concluded=Verdict.CONTRADICTS,
                tier=SourceTier.CONVENTION,
                quality=EvidenceQuality.INFERRED,
                outcome=VerificationOutcome.DISAGREE,
                agreement=ArbiterAgreement.DISAGREED,
            ) == baseline
        finally:
            rules.CAPS = original


class TestTheArithmetic:
    """CLS-4 and CLS-5. The whole defence of hand-set weights is that it can
    be checked by hand, so these check it by hand."""

    def test_the_trace_adds_up_when_nothing_capped_it(self):
        trace = classified().score_trace

        assert trace.terms == {
            "verdict_base": 0.50,
            "source_strength_authoritative": 0.25,
            "verification_agreement": 0.10,
        }
        assert sum(trace.terms.values()) == pytest.approx(trace.total)
        assert trace.ceiling_applied is None

    def test_a_cap_shows_as_a_gap_between_the_terms_and_the_total(self):
        """And when something did cap it, the gap is the cap - named.

        The sketched version of this test asserted `sum(terms) == total`
        unconditionally. That cannot hold: a capped fact deliberately proposes
        more than it publishes, and the difference is the point. A test
        written the old way fails on correct code and gets "fixed" by removing
        the ceiling it exists to protect.
        """

        trace = classified(outcome=VerificationOutcome.UNCERTAIN).score_trace

        assert sum(trace.terms.values()) == pytest.approx(0.75)
        assert trace.total == 0.60
        assert trace.total < sum(trace.terms.values())
        assert trace.ceiling_applied == "verification_uncertain"

    def test_agreement_is_worth_one_term_and_never_more(self):
        """Nothing downstream can manufacture confidence the evidence did not
        contain."""

        agreed = classified(outcome=VerificationOutcome.AGREE)
        uncertain = classified(outcome=VerificationOutcome.UNCERTAIN)

        assert "verification_agreement" in agreed.score_trace.terms
        assert "verification_agreement" not in uncertain.score_trace.terms
        assert agreed.confidence - 0.10 == pytest.approx(
            sum(uncertain.score_trace.terms.values())
        )

    def test_the_arbiter_agreeing_adds_no_term_at_all(self):
        """A deterministic table is a check against invention, not a second
        opinion whose assent is evidence."""

        agreed = classified(agreement=ArbiterAgreement.AGREED)
        abstained = classified(agreement=ArbiterAgreement.NOT_CHECKED)

        assert agreed.score_trace.terms == abstained.score_trace.terms

    @pytest.mark.parametrize(
        "tier,expected",
        [
            (SourceTier.DECISION_RECORD, 0.85),
            (SourceTier.EXECUTABLE_CONFIG, 0.85),
            (SourceTier.DOCUMENTATION, 0.60),
            (SourceTier.HISTORY, 0.50),
            (SourceTier.CONVENTION, 0.35),
        ],
    )
    def test_what_each_tier_can_reach_at_best(self, tier, expected):
        """The same fact, agreed by both models, at each tier. This is the
        table a reader can check the published output against."""

        assert classified(tier=tier).confidence == expected

    def test_nothing_ever_reaches_one(self):
        """The best case is 0.85. The remaining 0.15 is what this method
        cannot establish at all, and a scheme topping out at 1.0 would be
        claiming certainty it has no way to reach."""

        best = max(
            classified(tier=tier, concluded=concluded).confidence
            for tier in SourceTier
            for concluded in Verdict
        )

        assert best == rules.MAXIMUM_CONFIDENCE == 0.85

    def test_the_route_boundary_is_the_threshold_itself(self):
        """Asserted on the function, because the terms cannot sum to exactly
        0.70 and the boundary is still worth pinning."""

        assert rules.route_for(ValidationBucket.CONFIRMED, PUBLISH_THRESHOLD) == (
            Route.PUBLISH
        )
        assert rules.route_for(ValidationBucket.CONFIRMED, 0.6999) == Route.REVIEW


class TestWhenVerificationDidNotHappen:
    """CLS-8 and VER-D9. `None` is a fourth state, not a falsy `AGREE`."""

    def test_the_two_reasons_cap_alike_and_are_named_apart(self):
        chosen = classified(audited=False, mode=VerificationMode.NOT_REQUESTED)
        broken = classified(audited=False, mode=VerificationMode.UNAVAILABLE)

        assert chosen.confidence == broken.confidence == 0.65
        assert chosen.score_trace.ceiling_applied == "unverified_by_choice"
        assert broken.score_trace.ceiling_applied == "unverified_unavailable"

    def test_a_missing_verification_never_raises_confidence(self):
        """The falsy-check trap. `if not verification:` merges skipped with
        disagreed, and skipped must never score higher than performed."""

        skipped = classified(audited=False, mode=VerificationMode.NOT_REQUESTED)
        agreed = classified(outcome=VerificationOutcome.AGREE)

        assert skipped.confidence < agreed.confidence

    def test_an_unverified_confirmation_is_still_a_confirmation(self):
        """The unverified cap limits the number without changing what was
        concluded - and the number is below the threshold, so the fact
        reaches a person instead of a report."""

        result = classified(audited=False, mode=VerificationMode.UNAVAILABLE)

        assert result.bucket == ValidationBucket.CONFIRMED
        assert result.route == Route.REVIEW

    def test_a_verdict_with_no_model_behind_it_is_capped_and_published(self):
        """The ladder's last rung. Every governed fact still decided, with the
        arbiter named as the author, capped because the rule extraction above
        it is the only thing holding it up."""

        result = classified(
            produced_by=VerdictSource.ARBITER,
            audited=False,
            mode=VerificationMode.UNAVAILABLE,
        )

        assert result.confidence == 0.60
        assert result.score_trace.ceiling_applied == "verdict_without_a_model"
        assert result.model_calls == 0


class TestThePerFactMode:
    """CLS-7. The helper that answers *why was this not audited*."""

    def test_a_verified_fact_is_performed(self):
        assert per_fact_mode(True, False, verification()) is (
            VerificationMode.PERFORMED
        )

    def test_a_run_that_turned_verification_off_is_not_requested(self):
        assert per_fact_mode(False, False, None) is VerificationMode.NOT_REQUESTED

    def test_an_unreachable_verifier_is_unavailable(self):
        assert per_fact_mode(True, False, None) is VerificationMode.UNAVAILABLE

    def test_a_blind_only_run_is_not_requested_rather_than_unavailable(self):
        """The bug M5 shipped and fixed, in the one place it would reappear.

        A blind-only run has no informed opinion on any fact **by request**.
        Reading those absent checks as failures reports a working run as a
        broken one - and here it would put `unverified_unavailable` on
        fifteen facts nobody ever asked to have verified.
        """

        assert per_fact_mode(True, True, None) is VerificationMode.NOT_REQUESTED


class TestWhenNoModelWasCalled:
    """CLS-6. "No model was called" is a representable state, not a sentinel."""

    def test_an_uncovered_fact_is_a_finding_and_publishes(self):
        result = ClassificationService().classify(
            fact(), Resolution(governing=None, uncovered=True), None, None, None
        )

        assert result.bucket == ValidationBucket.UNCOVERED
        assert result.route == Route.PUBLISH
        assert result.model_calls == 0
        assert result.confidence == 0.0

    def test_an_uncovered_fact_has_an_empty_trace_rather_than_a_zero_term(self):
        """A term worth 0.0 would read as a contribution that happened to
        count for nothing. Nothing was claimed at all."""

        trace = ClassificationService().classify(
            fact(), Resolution(governing=None, uncovered=True), None, None, None
        ).score_trace

        assert trace.terms == {}
        assert trace.total == 0.0
        assert trace.ceiling_applied is None

    def test_an_ambiguous_resolution_goes_to_a_person(self):
        result = ClassificationService().classify(
            fact(), Resolution(governing=None, ambiguous=True), None, None, None
        )

        assert result.bucket == ValidationBucket.AMBIGUOUS
        assert result.route == Route.REVIEW
        assert result.model_calls == 0

    def test_a_verdict_without_a_governing_decision_cannot_be_classified(self):
        """The verdict was produced *against* that decision. Classifying it
        without one would apply no source ceiling at all, which is the one
        thing this unit exists to guarantee."""

        with pytest.raises(ValueError, match="no governing decision"):
            ClassificationService().classify(
                fact(), Resolution(governing=None), verdict(), None, None
            )


class TestWhatIsPublishedPerFact:
    """The fields M7 and M8 read, and the one number C3 gates a release on."""

    def test_the_tier_travels_so_the_ceiling_can_be_rechecked(self):
        """The whole reason the ceiling is keyed on tier. Anyone holding the
        output can look the tier up in the table and confirm the bucket is
        one that tier is allowed to reach."""

        result = classified(tier=SourceTier.DOCUMENTATION)

        assert result.source_tier is SourceTier.DOCUMENTATION
        assert rules.ASSERTION_RANK[result.bucket] <= rules.ASSERTION_RANK[
            rules.TIER_CAP[result.source_tier].bucket
        ]

    def test_the_citations_are_the_models_own(self):
        assert classified().evidence_refs == ("rule-frontend-cartservice",)

    @pytest.mark.parametrize(
        "reasoning_calls,verifying_calls,audited,expected",
        [
            (1, 1, True, 2),
            (2, 1, True, 3),
            (0, 1, True, 1),
            (1, 0, False, 1),
            (0, 0, False, 0),
        ],
    )
    def test_model_calls_is_what_the_two_stages_counted(
        self, reasoning_calls, verifying_calls, audited, expected
    ):
        """Added up from what each stage recorded, never re-derived here.

        A replayed answer is zero and a retry that reached the provider is
        two, as before - but both numbers now come from the ladder, which is
        the only thing that saw every answer.
        """

        result = ClassificationService().classify(
            fact(),
            Resolution(governing=decision()),
            verdict(live_calls=reasoning_calls),
            verification(live_calls=verifying_calls) if audited else None,
            VerificationMode.PERFORMED if audited else VerificationMode.UNAVAILABLE,
        )

        assert result.model_calls == expected

    def test_a_fact_rejected_from_cache_reports_no_call(self):
        """The regression this field was added for.

        Every answer came from the cache and every one was thrown out by a
        guard, so nothing was concluded and nothing was spent. Inferring the
        count from `cached` and `retried` reported **two** live calls, because
        the verdict that is kept when nothing survives has `cached=False` by
        default - and the number is published to the next component.
        """

        result = ClassificationService().classify(
            fact(),
            Resolution(governing=decision()),
            verdict(
                concluded=Verdict.INSUFFICIENT_EVIDENCE,
                agreement=ArbiterAgreement.NOT_COMPARABLE,
                retried=True,
                live_calls=0,
                guard_failures=(GuardFailure.UNRESOLVED_CITATION,),
            ),
            verification(live_calls=0),
            VerificationMode.PERFORMED,
        )

        assert result.model_calls == 0

    def test_a_fact_nothing_was_concluded_about_carries_no_confidence(self):
        """Both answers rejected, so no claim was established.

        It scored 0.85 - the maximum this component can publish - beside a
        bucket that declines to conclude, because it collected the verdict
        base, its source strength and a verification agreement term. The
        agreement was the verifier confirming there was no argument to fault.
        """

        result = ClassificationService().classify(
            fact(),
            Resolution(governing=decision()),
            verdict(
                concluded=Verdict.INSUFFICIENT_EVIDENCE,
                agreement=ArbiterAgreement.NOT_COMPARABLE,
                retried=True,
                live_calls=0,
                guard_failures=(GuardFailure.UNRESOLVED_CITATION,),
            ),
            verification(live_calls=0),
            VerificationMode.PERFORMED,
        )

        assert result.bucket is ValidationBucket.INSUFFICIENT_EVIDENCE
        assert result.confidence == 0.0
        assert result.score_trace.ceiling_applied == "every_answer_rejected"
        assert "verification_agreement" not in result.score_trace.terms
        assert result.route == Route.REVIEW

    def test_classify_does_not_accept_a_blind_verdict(self):
        """CLS-D9, asserted on the signature, because the opposite is a
        natural thing for somebody to add: there is a second verdict sitting
        right there, and two models agreeing feels like it should count.

        It must not. An opinion formed without seeing the argument is not a
        check on that argument.
        """

        parameters = list(
            inspect.signature(ClassificationService.classify).parameters
        )

        assert parameters == [
            "self",
            "fact",
            "resolution",
            "verdict",
            "verification",
            "verification_mode",
        ]
