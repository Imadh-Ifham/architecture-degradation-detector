"""Independent verification tests: the shapes, and the challenge as asked.

Author: Aman Mohamed M.A
Date: 2026-10-18
Description:
    V1 is the shape of an objection, the provenance a verification carries,
    and the prompt file that asks for both. No model is called anywhere in
    this file.

    Two tests carry more weight than the rest.
    `test_an_objection_about_one_item_must_name_it` is the one lie this
    subcomponent cannot afford: an objection with an invented reference reads
    as more specific than one with none, and it points at the wrong line.
    And `test_the_challenge_never_mentions_the_arbiter` is M4's trap again -
    tell a model what the deterministic table concluded and it agrees with
    it, the agreement rate goes to a hundred per cent, every measured number
    improves, and the only uncorrelated check in the component is gone.

    The prompt is read off disk rather than stood in for. The file and the
    renderer are two halves of one artifact and they drift.
"""

import inspect
from dataclasses import replace

import pytest

from app.components.architecture_validation.independent_verification import (
    IndependentVerificationService,
)
from app.components.architecture_validation.independent_verification._guards import check
from app.components.architecture_validation.independent_verification._prompt import (
    render,
    verification_schema,
)
from app.components.architecture_validation.models import (
    BlindVerdict,
    GuardFailure,
    Objection,
    ObjectionKind,
    PrimaryVerdict,
    Verdict,
    VerdictSource,
    Verification,
    VerificationOutcome,
)
from app.components.architecture_validation.validation_reasoning._prompt import (
    render as render_blind,
)
from app.components.architecture_validation.validation_reasoning._prompt import (
    render as render_primary,
)
from app.infrastructure.ai import (
    SCHEMA_MODE_STRICT,
    TASK_VERIFICATION,
    AISettings,
    ConfiguredAIClient,
    VerdictCache,
)
from app.infrastructure.ai.model_registry import capabilities_for
from app.infrastructure.ai.prompt_library import load_prompt
from app.infrastructure.ai.providers.fake import DEFAULT_MODEL_ID, FakeProvider
from app.infrastructure.ai.providers.openai_compatible import strictify
from tests.components.architecture_validation.corpus import package

TEMPLATE = load_prompt("critical_reframing.v1.md")
PRIMARY_TEMPLATE = load_prompt("primary_verdict.v1.md")

ABOUT_ONE_ITEM = (
    ObjectionKind.CITATION_DOES_NOT_SUPPORT,
    ObjectionKind.OVERLOOKED_EVIDENCE,
)
ABOUT_THE_ARGUMENT = (
    ObjectionKind.CLAIM_EXCEEDS_EVIDENCE,
    ObjectionKind.UNSTATED_ASSUMPTION,
)

RULE = "rule-frontend-cartservice"


def verdict(sealed=None, concluded: Verdict = Verdict.CONFIRMS) -> PrimaryVerdict:
    """A verdict over the real package, as M4 would have produced it."""

    sealed = sealed if sealed is not None else package()
    return PrimaryVerdict(
        fact_id=sealed.fact_id,
        verdict=concluded,
        reasoning="The policy names cartservice among the peers frontend may call.",
        cited_evidence_refs=(RULE,),
        model_id="fake/reasoner-1",
        prompt_version="primary_verdict@1",
        evidence_hash=sealed.evidence_hash,
        cached=False,
    )


class TestTheObjectionShape:
    """VER-1. Four kinds, and a reference only where there is one to name."""

    @pytest.mark.parametrize("kind", ABOUT_ONE_ITEM)
    def test_an_objection_about_one_item_must_name_it(self, kind):
        """The one lie this subcomponent cannot afford. An objection that
        names an arbitrary item reads as more precise than one that names
        nothing, while pointing at the wrong line."""

        with pytest.raises(ValueError):
            Objection(kind=kind, ref=None, statement="the citation is wrong")

    @pytest.mark.parametrize("kind", ABOUT_THE_ARGUMENT)
    def test_an_objection_about_the_argument_as_a_whole_need_not(self, kind):
        """A claim exceeding its evidence and an assumption out of nowhere are
        statements about the argument. Requiring a reference would force one."""

        objection = Objection(kind, None, "it assumes a mesh exists")

        assert objection.ref is None

    def test_an_empty_reference_is_not_a_reference(self):
        """`ref=""` would satisfy a type check and render as a blank citation
        the UI would print an arrow next to."""

        with pytest.raises(ValueError):
            Objection(ObjectionKind.OVERLOOKED_EVIDENCE, "", "the policy was not cited")

    def test_an_objection_survives_being_written_down_and_read_back(self):
        """A run's record is only worth keeping if the objections in it are
        still objections afterwards. Every other published shape in the
        component serialises itself; one that cannot gets a serialiser written
        beside its first consumer and a second one beside the next, and the
        two disagree about whether an absent reference is null or missing."""

        objection = Objection(
            ObjectionKind.OVERLOOKED_EVIDENCE, RULE, "the policy was not cited"
        )

        assert objection.to_dict() == {
            "kind": "overlooked_evidence",
            "ref": RULE,
            "statement": "the policy was not cited",
        }

    def test_an_absent_reference_is_written_down_as_null(self):
        """The field is present and empty rather than missing, so a reader of
        a stored record cannot mistake *about the whole argument* for *the
        reference was lost on the way out*."""

        objection = Objection(ObjectionKind.UNSTATED_ASSUMPTION, None, "assumes a mesh")

        assert objection.to_dict()["ref"] is None

    def test_the_vocabulary_is_the_four_kinds_and_no_others(self):
        """Closed because free text cannot be counted: *which kind of
        reasoning error does a free model make* is only answerable over a
        corpus if the kinds are a fixed small set."""

        assert tuple(ObjectionKind) == ABOUT_ONE_ITEM + ABOUT_THE_ARGUMENT


class TestWhatAVerificationCarries:
    """VER-2. The provenance that makes a stored verification re-readable."""

    def test_a_verification_records_the_package_it_was_produced_from(self):
        """Without the hash nothing in the output would say whether both
        passes saw the same evidence - and a verification of a *different*
        package is a second opinion on a different question that looks
        exactly like a real one."""

        sealed = package()
        verification = Verification(
            fact_id=sealed.fact_id,
            outcome=VerificationOutcome.AGREE,
            mechanism="critical-reframing",
            reasoning="nothing found",
            model_id="fake/verifier-1",
            prompt_version=TEMPLATE.version,
            cached=False,
            evidence_hash=sealed.evidence_hash,
        )

        assert verification.evidence_hash == verdict(sealed).evidence_hash

    def test_the_fields_a_later_reader_needs_are_all_on_it(self):
        """Provenance is the one thing that cannot be added to a result
        afterwards, which is why these are V1. Two runs under different
        enforcement are not the same experiment, and a stored verification
        that cannot say which it was cannot be compared with the other."""

        recorded = Verification(
            fact_id="f1",
            outcome=VerificationOutcome.UNCERTAIN,
            mechanism="critical-reframing",
            reasoning="an objection was raised and then withdrawn",
            model_id="fake/verifier-1",
            prompt_version=TEMPLATE.version,
            cached=False,
            evidence_hash="abc",
            provider="fake",
            schema_mode="strict",
            retried=True,
            guard_failures=(GuardFailure.UNRESOLVED_CITATION,),
        )

        assert recorded.provider and recorded.schema_mode
        assert recorded.retried is True
        assert GuardFailure.UNRESOLVED_CITATION in recorded.guard_failures

    def test_an_agreement_carries_an_empty_list_of_faults_not_an_absent_one(self):
        """`agree` means the verifier looked and found nothing, so the field is
        present and empty. A null would be indistinguishable from a field that
        was dropped somewhere between here and a screen."""

        verification = Verification(
            fact_id="f1",
            outcome=VerificationOutcome.AGREE,
            mechanism="critical-reframing",
            reasoning="nothing found",
            model_id="fake/verifier-1",
            prompt_version=TEMPLATE.version,
            cached=False,
        )

        assert verification.objections == ()

    def test_an_objection_survives_onto_the_verification(self):
        verification = Verification(
            fact_id="f1",
            outcome=VerificationOutcome.DISAGREE,
            mechanism="critical-reframing",
            reasoning="the citation does not support the claim",
            model_id="fake/verifier-1",
            prompt_version=TEMPLATE.version,
            cached=False,
            objections=(
                Objection(
                    ObjectionKind.CITATION_DOES_NOT_SUPPORT,
                    RULE,
                    "the line permits cartservice; this verdict is about adservice",
                ),
            ),
        )

        assert verification.objections[0].kind is ObjectionKind.CITATION_DOES_NOT_SUPPORT
        assert verification.objections[0].ref == RULE


class TestTheVerificationSchema:
    """VER-3's other half: the shape the objections come back in."""

    def test_the_objections_are_declared_before_the_outcome(self):
        """A statement about the schema, and only about the schema. M4
        measured the inference that used to justify this: the declared order
        survives strictify intact and the provider still returns its
        conclusion first. Coherence between the two fields is a guard's job
        after the answer arrives, which is why withdrawing the justification
        costs nothing here."""

        properties = list(strictify(verification_schema())["properties"])

        assert properties.index("objections") < properties.index("outcome")

    def test_the_objection_kind_is_closed_to_the_four_values(self):
        """A string field can return anything. Under a strict schema a closed
        enum cannot, so a fifth kind of objection stops being something the
        guards have to catch."""

        kind = verification_schema()["properties"]["objections"]["items"]
        assert kind["properties"]["kind"]["enum"] == [
            "citation_does_not_support",
            "overlooked_evidence",
            "claim_exceeds_evidence",
            "unstated_assumption",
        ]

    def test_the_outcome_is_closed_to_the_three_values(self):
        assert verification_schema()["properties"]["outcome"]["enum"] == [
            "agree",
            "disagree",
            "uncertain",
        ]

    def test_a_reference_can_come_back_null_rather_than_absent(self):
        """Strict mode has no optional properties - strictify makes every one
        of them required - so the two kinds with no item to name have to be
        able to send null for it. Declared as a union here, or the two kinds
        about the argument would be unaskable."""

        strict = strictify(verification_schema())
        item = strict["properties"]["objections"]["items"]

        assert item["properties"]["ref"]["type"] == ["string", "null"]
        assert item["required"] == ["kind", "ref", "statement"]

    def test_finding_no_fault_is_a_representable_answer(self):
        """A `minItems` of one would guarantee a fault was always found, and
        the disagreement rate would be a property of the schema."""

        assert "minItems" not in verification_schema()["properties"]["objections"]

    def test_strictifying_it_forbids_anything_else_coming_back(self):
        strict = strictify(verification_schema())

        assert strict["additionalProperties"] is False
        assert strict["properties"]["objections"]["items"]["additionalProperties"] is False


class TestTheRenderedChallenge:
    """VER-3. What the verifier is shown, and the one thing it must not be.

    `test_the_challenge_never_mentions_the_arbiter` is the most important test
    here for the same reason it is in M4: a verifier told what the
    deterministic table concluded agrees with it, and the three-way
    comparison the component exists to report becomes two opinions and an
    echo.
    """

    def test_the_prompt_shows_the_verdict_and_the_reasoning(self):
        """VER-D3. A verifier that cannot see the claim is running M4's task a
        second time, which measures the model's self-consistency rather than
        verifying anything - and at temperature zero it mostly agrees with
        itself."""

        sealed = package()
        primary = verdict(sealed)

        rendered = render(TEMPLATE, sealed, primary)

        assert primary.verdict.value in rendered
        assert primary.reasoning in rendered
        for ref in primary.cited_evidence_refs:
            assert ref in rendered

    def test_the_renderer_takes_the_package_and_the_verdict_and_nothing_else(self):
        """The extra argument against M4's renderer is the whole of this
        subcomponent. One that could also reach the fact or the resolution
        would be showing the verifier evidence nobody sealed, and the
        citation set would stop being the evidence set."""

        assert list(inspect.signature(render).parameters) == [
            "template",
            "package",
            "verdict",
        ]

    def test_the_challenge_never_mentions_the_arbiter(self):
        """Tell the verifier what the table decided and it agrees with it.
        Every measured number improves and the only uncorrelated check in the
        component is gone."""

        rendered = render(TEMPLATE, package(), verdict()).lower()

        assert "arbiter" not in rendered
        assert "basis" not in rendered

    def test_it_asks_for_faults_rather_than_for_a_verdict(self):
        """VER-D4. A second verdict would be a second sample of one task, the
        agreement rate would be high and nearly content-free, and this would
        be two hundred lines of self-congratulation."""

        rendered = render(TEMPLATE, package(), verdict())

        for kind in ObjectionKind:
            assert kind.value in rendered
        assert "What is wrong with that argument?" in rendered

    def test_every_placeholder_in_the_file_is_filled(self):
        """The prompt is a file and the renderer is code, so they can drift. A
        placeholder left in the text reaches the model as a literal
        `{{verdict}}`, which it will answer anyway."""

        assert "{{" not in render(TEMPLATE, package(), verdict())

    def test_both_arms_are_shown_the_identical_evidence(self):
        """The two prompts differ in the challenge, never in the evidence. A
        measured difference between the arms that was partly a difference in
        formatting would be a difference in nothing anybody could name, which
        is what the shared renderer is for."""

        sealed = package()

        for item in sealed.items:
            assert item.ref in render(TEMPLATE, sealed, verdict(sealed))
            assert str(item.role) in render(TEMPLATE, sealed, verdict(sealed))
            assert item.text.splitlines()[0] in render(TEMPLATE, sealed, verdict(sealed))

    def test_the_evidence_hash_is_not_rendered(self):
        """It is the cache key, not evidence. A model given it is given a
        number it cannot check and could cite."""

        sealed = package()

        assert sealed.evidence_hash not in render(TEMPLATE, sealed, verdict(sealed))

    def test_the_challenge_is_its_own_file_and_not_the_primary_prompt_reworded(self):
        """VER-3. Two arms that share a template are indistinguishable in the
        results, and the mechanism comparison this component is built to
        support needs them apart - which is also why the version string is
        part of the cache key and of what a result is attributed to."""

        assert TEMPLATE.version == "critical_reframing@1"
        assert TEMPLATE.version != PRIMARY_TEMPLATE.version
        assert TEMPLATE.system != PRIMARY_TEMPLATE.system

    def test_the_primary_prompt_is_not_shown_the_verdict(self):
        """The guarantee in the other direction, asserted because the two
        renderers now share functions: M4's must still be unable to render a
        verdict even by accident."""

        sealed = package()

        assert verdict(sealed).reasoning not in render_primary(PRIMARY_TEMPLATE, sealed)


def answer(
    outcome: str = "agree",
    objections: tuple[dict, ...] = (),
    reasoning: str = "the cited policy does name cartservice as a permitted peer",
) -> dict:
    return {
        "reasoning": reasoning,
        "objections": [dict(objection) for objection in objections],
        "outcome": outcome,
    }


def objection(
    kind: str = "claim_exceeds_evidence",
    ref: str | None = None,
    statement: str = "the verdict is stronger than the policy line allows",
) -> dict:
    return {"kind": kind, "ref": ref, "statement": statement}


def verifier(provider: FakeProvider, cache: VerdictCache | None = None):
    """The real service over the real client, with a scripted provider.

    Built through `ConfiguredAIClient` rather than a hand-written stub, so the
    cache key, the strict-schema request and the translation of a provider's
    failure into the port's own error are exercised here rather than assumed.
    """

    client = ConfiguredAIClient(
        provider,
        settings=AISettings(ai_api_key="not-a-real-key"),
        cache=cache or VerdictCache("unused", enabled=False),
    )
    return IndependentVerificationService(
        client, TEMPLATE, TASK_VERIFICATION, provider="fake"
    )


class TestTheGuards:
    """VER-5 and VER-6. Three checks, and the schema can express none of them.

    `test_guard_e_rejects_agreeing_while_listing_faults` is the one Guard E
    exists for, and it is common rather than exotic: a small model asked for a
    list of faults and a judgement in one response will sometimes produce
    both, disagreeing with itself.
    """

    def test_guard_a_rejects_an_answer_with_no_reasoning(self):
        outcome = check(answer(reasoning="  "), package())

        assert outcome.accepted is False
        assert outcome.failure is GuardFailure.MALFORMED

    def test_guard_a_rejects_an_outcome_outside_the_vocabulary(self):
        """Impossible under a strict schema, which is exactly why it is
        checked: strict mode is a request, and a provider can serve it
        without honouring it."""

        rejected = check(answer(outcome="looks_fine"), package())

        assert rejected.failure is GuardFailure.MALFORMED

    def test_guard_a_rejects_an_objection_kind_outside_the_four(self):
        rejected = answer("disagree", (objection(kind="vibes"),))

        assert check(rejected, package()).failure is GuardFailure.MALFORMED

    def test_guard_a_rejects_an_objection_with_no_statement(self):
        """A kind and a reference with nothing said about them renders as a
        heading over an empty line."""

        rejected = answer("disagree", (objection(statement="   "),))

        assert check(rejected, package()).failure is GuardFailure.MALFORMED

    def test_an_objection_about_one_item_that_names_none_is_rejected_not_raised(self):
        """`Objection` would raise on this, and an exception out of a parser is
        not a finding. It comes back as a recorded guard failure so the ladder
        retries identically and the rate of it stays measurable."""

        rejected = answer("disagree", (objection(kind="overlooked_evidence", ref=None),))

        assert check(rejected, package()).failure is GuardFailure.MALFORMED

    def test_guard_b_rejects_an_objection_naming_a_reference_that_does_not_exist(self):
        """The verifier hallucinating, caught by the same ten lines that catch
        the reasoner hallucinating."""

        rejected = answer(
            "disagree",
            (objection(kind="citation_does_not_support", ref="ADR-999"),),
        )
        outcome = check(rejected, package())

        assert outcome.failure is GuardFailure.UNRESOLVED_CITATION
        assert outcome.refs_at_fault == ("ADR-999",)

    def test_guard_b_is_not_handed_the_absent_references_as_citations(self):
        """Two of the four kinds carry no reference by design. Passing their
        nulls to Guard B would reject every well formed objection about the
        argument as a whole."""

        accepted = answer("disagree", (objection(kind="unstated_assumption"),))

        assert check(accepted, package()).accepted is True

    def test_guard_e_rejects_agreeing_while_listing_faults(self):
        incoherent = answer("agree", (objection(),))

        assert check(incoherent, package()).failure is GuardFailure.INCOHERENT_OUTCOME

    def test_guard_e_rejects_disagreeing_with_nothing_to_point_at(self):
        """An opinion rather than a finding, and nothing a reviewer can open."""

        empty = check(answer("disagree", ()), package())

        assert empty.failure is GuardFailure.INCOHERENT_OUTCOME

    def test_guard_e_allows_uncertainty_with_a_partial_objection(self):
        """The one outcome that may carry any number of them: a fault somebody
        could not settle is a coherent thing to report."""

        assert check(answer("uncertain", (objection(),)), package()).accepted is True
        assert check(answer("uncertain", ()), package()).accepted is True

    def test_an_objection_about_a_neighbour_is_a_legitimate_objection(self):
        """M4's guard C refuses a *verdict* resting on a neighbour. This answer
        is not a verdict, and an objection pointing at one is the verifier
        doing its job."""

        neighbour = "context:frontend-also-reaches-adservice"
        pointed = answer(
            "disagree",
            (objection(kind="overlooked_evidence", ref=neighbour),),
        )

        assert check(pointed, package()).accepted is True

    def test_an_objection_about_the_replaced_decision_is_legitimate_too(self):
        """M4's guard D refuses a verdict resting on the superseded item. An
        objection saying *the verdict rests on the replaced decision* is the
        most valuable single thing this subcomponent can say, so the guard
        that catches the verdict must not be applied to the objection."""

        pointed = answer(
            "disagree",
            (
                objection(
                    kind="citation_does_not_support",
                    ref=RULE,
                    statement="this item was replaced and is not the rule in force",
                ),
            ),
        )

        assert check(pointed, package()).accepted is True


class TestTheAuditCall:
    """VER-4. One task, three rungs, and nothing that can become the reasoner.

    `test_an_unreachable_verifier_never_becomes_the_reasoner` is the one that
    matters most here. A fallback to the reasoner's model would produce a
    `Verification` that looks completely real, with a plausible model id on
    it, while being the first model endorsing its own answer.
    """

    def test_verification_runs_on_the_identical_evidence_package(self):
        """If the evidence differs this is a second opinion on a different
        question, and nothing in the output would say so."""

        sealed = package()
        primary = verdict(sealed)
        ai = FakeProvider(responses=answer())

        result = verifier(ai).verify(primary, sealed)

        assert result.evidence_hash == sealed.evidence_hash == primary.evidence_hash

    def test_a_real_objection_survives_intact(self):
        ai = FakeProvider(
            responses=answer(
                "disagree",
                (
                    objection(
                        kind="citation_does_not_support",
                        ref=RULE,
                        statement="the line permits cartservice; this is about adservice",
                    ),
                ),
            )
        )

        result = verifier(ai).verify(verdict(), package())

        assert result.outcome is VerificationOutcome.DISAGREE
        assert result.objections[0].kind is ObjectionKind.CITATION_DOES_NOT_SUPPORT
        assert result.objections[0].ref in package().refs

    def test_an_objection_about_the_argument_arrives_with_no_reference(self):
        """The null survives the round trip rather than becoming an empty
        string, so a screen can tell *about the whole argument* from *a
        reference that went missing on the way out*."""

        ai = FakeProvider(
            responses=answer("disagree", (objection(kind="unstated_assumption"),))
        )

        result = verifier(ai).verify(verdict(), package())

        assert result.objections[0].ref is None

    def test_agreeing_while_listing_faults_is_not_agreement(self):
        """Guard E through the real service: rejected, retried identically,
        and then uncertain rather than either of the two things the model
        said."""

        ai = FakeProvider(responses=[answer("agree", (objection(),))] * 2)

        result = verifier(ai).verify(verdict(), package())

        assert result.outcome is VerificationOutcome.UNCERTAIN
        assert result.outcome is not VerificationOutcome.AGREE
        assert GuardFailure.INCOHERENT_OUTCOME in result.guard_failures

    def test_disagreeing_with_nothing_to_point_at_is_an_opinion(self):
        ai = FakeProvider(responses=[answer("disagree", ())] * 2)

        result = verifier(ai).verify(verdict(), package())

        assert result.outcome is VerificationOutcome.UNCERTAIN

    def test_an_objection_naming_a_ref_that_does_not_exist_is_rejected(self):
        phantom = answer(
            "disagree", (objection(kind="overlooked_evidence", ref="ADR-999"),)
        )
        ai = FakeProvider(responses=[phantom] * 2)

        result = verifier(ai).verify(verdict(), package())

        assert result.outcome is VerificationOutcome.UNCERTAIN
        assert GuardFailure.UNRESOLVED_CITATION in result.guard_failures

    def test_malformed_twice_is_uncertain_never_agree(self):
        ai = FakeProvider(malformed_times=2)

        result = verifier(ai).verify(verdict(), package())

        assert result.outcome is VerificationOutcome.UNCERTAIN
        assert GuardFailure.MALFORMED in result.guard_failures

    def test_a_rejected_answer_publishes_no_objections(self):
        """Three good faults with the wrong label on them look salvageable.
        Salvaging them would mean this code deciding what the model meant, and
        publishing objections under an outcome the model never paired with
        them."""

        ai = FakeProvider(responses=[answer("agree", (objection(),))] * 2)

        result = verifier(ai).verify(verdict(), package())

        assert result.objections == ()
        assert "not agreement" in result.reasoning

    def test_a_rejection_is_retried_once_and_then_accepted(self):
        """The retry asks the identical question. A second model answering a
        question the first one botched would be a different question, and no
        comparison between the two would mean anything."""

        ai = FakeProvider(responses=[answer("disagree", ()), answer("agree")])

        result = verifier(ai).verify(verdict(), package())

        assert result.outcome is VerificationOutcome.AGREE
        assert result.retried is True
        assert ai.call_count == 2
        assert ai.prompts()[0] == ai.prompts()[1]

    def test_the_ladder_stops_at_two_calls(self):
        """VER-D8's arithmetic: cache, model, identical retry, stop. The
        truncation is a property of being given one task rather than a
        condition somebody can move."""

        ai = FakeProvider(fail_times=9)

        verifier(ai).verify(verdict(), package())

        assert ai.call_count <= 2

    def test_an_unreachable_verifier_never_becomes_the_reasoner(self):
        """A fallback to the reasoner's model would raise confidence on the
        basis of nothing, and it would neither fail nor warn."""

        ai = FakeProvider(fail_times=9)

        result = verifier(ai).verify(verdict(), package())

        assert result is None
        assert AISettings().ai_reasoner_model not in {
            call["model_id"] for call in ai.calls
        }

    def test_the_service_cannot_be_given_a_second_model_to_try(self):
        """The structural half of VER-D8. M4 takes an ordered sequence of
        tasks because it may try another model; this one takes a single
        string, so a fallback chain cannot be passed in at all by somebody
        who has not read the decision."""

        parameters = inspect.signature(IndependentVerificationService).parameters

        assert parameters["task"].annotation is str

    def test_a_check_that_could_not_run_is_not_a_check_that_ran(self):
        """Asserted on the two returns: nothing answered is `None`, and
        something that answered unusably is an `UNCERTAIN` saying so.
        Collapsing them would lose the only half that is actionable."""

        unreachable = verifier(FakeProvider(fail_times=9)).verify(verdict(), package())
        unusable = verifier(FakeProvider(malformed_times=2)).verify(verdict(), package())

        assert unreachable is None
        assert unusable is not None
        assert unusable.outcome is VerificationOutcome.UNCERTAIN

    def test_every_verification_carries_its_provenance(self):
        ai = FakeProvider(responses=answer())

        result = verifier(ai).verify(verdict(), package())

        assert result.mechanism == "critical-reframing"
        assert result.model_id and result.provider and result.prompt_version
        assert result.schema_mode == SCHEMA_MODE_STRICT

    def test_the_challenge_is_asked_under_a_strict_schema(self):
        ai = FakeProvider(responses=answer())

        verifier(ai).verify(verdict(), package())

        assert ai.schemas_were_strict()

    def test_a_warmed_cache_answers_without_a_call(self, tmp_path):
        """The verification half of the demonstration's cache plan. A run with
        `verify=false` followed later by one with `verify=true` pays only for
        the calls it has not already made."""

        cache = VerdictCache(tmp_path)
        ai = FakeProvider(responses=answer())
        sealed = package()

        first = verifier(ai, cache).verify(verdict(sealed), sealed)
        second = verifier(ai, cache).verify(verdict(sealed), sealed)

        assert ai.call_count == 1
        assert first.outcome is second.outcome
        assert second.cached is True

    def test_disagreement_is_carried_forward_not_resolved_here(self):
        """This subcomponent reports; classification decides what it means. A
        third call or a majority vote would make it an adjudicator - a
        different job with different failure modes - and it would hide the
        disagreement from the confidence score."""

        ai = FakeProvider(responses=answer("disagree", (objection(),)))

        result = verifier(ai).verify(verdict(), package())

        assert result.outcome is VerificationOutcome.DISAGREE
        assert ai.call_count == 1


class TestIndependence:
    """VER-8 and VER-13. What is recorded, and the one substitution refused.

    `test_the_verifier_is_not_the_reasoner` is asserted on the configuration
    rather than on a run, because the day somebody sets both settings to the
    same value nothing else in the suite would notice - every test would pass
    and the component would be one model checking its own answer.
    """

    def test_the_verifier_is_not_the_reasoner(self):
        settings = AISettings(ai_api_key="not-a-real-key")

        assert settings.ai_verifier_model != settings.ai_reasoner_model
        assert capabilities_for(settings.ai_verifier_model).supports_strict_schema

    def test_the_two_models_are_from_different_families(self):
        """VER-D1. Same weights would share the reasoner's blind spots, so its
        agreement would say almost nothing. Asserted on the vendor prefix,
        which is the only part of a model id that carries the family."""

        settings = AISettings(ai_api_key="not-a-real-key")
        reasoner = settings.ai_reasoner_model.split("/")[0]
        verifier = settings.ai_verifier_model.split("/")[0]

        assert reasoner != verifier

    def test_the_mechanism_and_both_model_ids_are_recorded(self):
        """VER-8. One row says which mechanism challenged which model, which
        is what makes the four-arm comparison a configuration change rather
        than a harness per arm."""

        ai = FakeProvider(responses=answer())
        primary = verdict()

        result = verifier(ai).verify(primary, package())

        assert result.mechanism == "critical-reframing"
        assert result.model_id == DEFAULT_MODEL_ID
        assert result.challenged_model_id == primary.model_id

    def test_the_challenged_model_is_the_one_that_answered_not_the_configured_one(self):
        """The distinction the field exists for. A verdict that fell to the
        ladder's second model, or to the deterministic table with a model id
        of "none", was not produced by the configured reasoner - and a
        comparison that assumed otherwise would be comparing arms that never
        ran against the same thing."""

        from_the_table = replace(
            verdict(), model_id="none", produced_by=VerdictSource.ARBITER
        )
        ai = FakeProvider(responses=answer())

        result = verifier(ai).verify(from_the_table, package())

        assert result.challenged_model_id == "none"
        assert result.challenged_model_id != AISettings().ai_reasoner_model

    def test_a_rejected_verification_still_records_what_it_was_challenging(self):
        """Provenance is the one thing that cannot be added to a result
        afterwards, so the unusable path carries it too."""

        ai = FakeProvider(malformed_times=2)
        primary = verdict()

        result = verifier(ai).verify(primary, package())

        assert result.outcome is VerificationOutcome.UNCERTAIN
        assert result.challenged_model_id == primary.model_id
        assert result.mechanism == "critical-reframing"


BLIND_TEMPLATE = load_prompt("blind_verdict.v1.md")


def blind_answer(
    concluded: str = "confirms",
    cited: tuple[str, ...] = (RULE,),
    reasoning: str = "the policy names cartservice among the permitted peers",
) -> dict:
    return {
        "reasoning": reasoning,
        "cited_evidence_refs": list(cited),
        "verdict": concluded,
    }


def both_arms(provider: FakeProvider, cache: VerdictCache | None = None):
    """The service with both arms wired, as the composition root wires it."""

    client = ConfiguredAIClient(
        provider,
        settings=AISettings(ai_api_key="not-a-real-key"),
        cache=cache or VerdictCache("unused", enabled=False),
    )
    return IndependentVerificationService(
        client,
        TEMPLATE,
        TASK_VERIFICATION,
        provider="fake",
        blind_prompt=BLIND_TEMPLATE,
    )


class TestTheBlindArm:
    """V5. The same model, the same package, and not the answer.

    `test_the_blind_prompt_cannot_show_the_verdict` is the most important test
    in V5 and the reason the renderer takes no verdict: a blind prompt that
    leaked one would not fail and would not warn. The two arms would
    converge, the delta would collapse toward zero, and the number would read
    as *anchoring does not happen here* - a wrong result that looks like a
    finding.
    """

    def test_the_blind_prompt_cannot_show_the_verdict(self):
        """There must be nothing available to leak, asserted two ways.

        **The template has no placeholder that could carry the answer**, and
        **the renderer takes no verdict** - M4's, over `(template, package)`,
        so one cannot reach it even by accident. That is a stronger guarantee
        than a request object missing a field, because a field can be added
        and a parameter cannot appear on its own.

        It is *not* asserted by looking for the verdict word or the cited refs
        in the rendered text, which is how this was first written and which no
        correct implementation can satisfy: the five verdict values are listed
        in the rules because the model has to know them, and every ref is in
        the evidence listing because a model cites what it can name. A test
        shaped that way fails on a correct prompt and would have been
        "fixed" by weakening it.
        """

        leaky = ("{{verdict}}", "{{reasoning}}", "{{cited}}")

        for placeholder in leaky:
            assert placeholder not in BLIND_TEMPLATE.system
            assert placeholder not in BLIND_TEMPLATE.body

        assert list(inspect.signature(render_blind).parameters) == [
            "template",
            "package",
        ]

    def test_that_test_would_notice_a_leak(self):
        """The contrast that gives the one above its teeth. The informed
        template does carry all three placeholders, so the check
        discriminates between an arm that may see the answer and one that may
        not - rather than passing on every file."""

        assert "{{verdict}}" in TEMPLATE.body
        assert "{{reasoning}}" in TEMPLATE.body
        assert "{{cited}}" in TEMPLATE.body

    def test_the_primary_reasoning_never_reaches_the_blind_prompt(self):
        """The one text that is unique to the primary's answer and so the one
        whose absence is evidence. The verdict word and the refs are both
        legitimately present for other reasons."""

        sealed = package()
        primary = verdict(sealed, Verdict.CONTRADICTS)

        rendered = render_blind(BLIND_TEMPLATE, sealed)

        assert primary.reasoning not in rendered

    def test_the_blind_prompt_says_no_other_answer_is_coming(self):
        """A model asked for a verdict with no context sometimes hedges toward
        `insufficient_evidence` on the assumption something is missing. Saying
        the evidence is all there is turns that into a real judgement."""

        rendered = render_blind(BLIND_TEMPLATE, package()).lower()

        assert "nobody else's answer is available" in rendered
        assert "arbiter" not in rendered

    def test_the_blind_prompt_is_its_own_file(self):
        assert BLIND_TEMPLATE.version == "blind_verdict@1"
        assert BLIND_TEMPLATE.version != TEMPLATE.version
        assert BLIND_TEMPLATE.system != TEMPLATE.system

    def test_the_blind_arm_returns_a_verdict_in_m4s_vocabulary(self):
        ai = FakeProvider(responses=blind_answer("partially_confirms"))

        result = both_arms(ai).verify_blind(package())

        assert result.verdict is Verdict.PARTIALLY_CONFIRMS
        assert result.mechanism == "blind-verdict"
        assert result.cited_evidence_refs == (RULE,)

    def test_a_blind_verdict_is_not_a_primary_verdict(self):
        """The one thing this arm must never do is have its unanchored opinion
        published as the component's conclusion. Its content would fit
        `PrimaryVerdict` exactly, so the separate type is what stops it."""

        ai = FakeProvider(responses=blind_answer())

        result = both_arms(ai).verify_blind(package())

        assert isinstance(result, BlindVerdict)
        assert not isinstance(result, PrimaryVerdict)
        assert not hasattr(result, "arbiter")
        assert not hasattr(result, "arbiter_agreement")

    def test_a_blind_verifier_citing_a_phantom_ref_is_rejected_by_m4s_guard(self):
        """No new guard. Its output is M4's shape, so it is M4's code that
        catches it hallucinating - and a second implementation of one
        guarantee is how two of them come to disagree."""

        ai = FakeProvider(responses=blind_answer(cited=("ADR-999",)))

        result = both_arms(ai).verify_blind(package())

        assert result is None or GuardFailure.UNRESOLVED_CITATION in (
            result.guard_failures
        )

    def test_a_blind_verdict_resting_on_a_neighbour_is_rejected_by_m4s_guard(self):
        """M4's guard C applies here and does *not* apply to an objection. The
        difference is that this arm produces a verdict, and a conclusion rests
        on a rule rather than on a neighbour."""

        neighbour = "context:frontend-also-reaches-adservice"
        ai = FakeProvider(responses=blind_answer(cited=(neighbour,)))

        result = both_arms(ai).verify_blind(package())

        assert result is None

    def test_the_blind_arm_stops_at_two_calls_like_the_informed_one(self):
        ai = FakeProvider(fail_times=9)

        assert both_arms(ai).verify_blind(package()) is None
        assert ai.call_count <= 2

    def test_a_service_with_no_blind_prompt_refuses_rather_than_improvising(self):
        """What keeps V5 separable. A service built without the blind prompt
        has no blind arm, and asking for one is a wiring mistake rather than
        something to paper over."""

        ai = FakeProvider(responses=blind_answer())

        with pytest.raises(ValueError, match="blind_prompt"):
            verifier(ai).verify_blind(package())

    def test_the_blind_arm_is_the_same_model_as_the_informed_arm(self):
        """A third model would confound the delta: the difference would be
        partly family and partly anchoring, and would measure neither."""

        ai = FakeProvider(responses=[answer(), blind_answer()])
        sealed = package()

        both_arms(ai).verify_both(verdict(sealed), sealed)

        informed, blind = ai.calls
        assert informed["model_id"] == blind["model_id"]
        assert informed["prompt"] != blind["prompt"]

    def test_both_arms_must_have_seen_the_same_package(self):
        sealed = package()
        ai = FakeProvider(responses=[answer(), blind_answer()])

        informed, blind = both_arms(ai).verify_both(verdict(sealed), sealed)

        assert informed.evidence_hash == sealed.evidence_hash
        assert blind.evidence_hash == sealed.evidence_hash

    def test_comparing_arms_that_saw_different_evidence_is_refused(self):
        """A delta across two packages compares perfectly well and means
        nothing, so this raises rather than returning a number somebody would
        publish."""

        ai = FakeProvider(responses=blind_answer())
        blind = both_arms(ai).verify_blind(package())
        elsewhere = replace(verdict(), evidence_hash="a-different-package")

        with pytest.raises(ValueError, match="measures nothing"):
            blind.agrees_with(elsewhere)

    def test_agreement_is_a_comparison_of_two_words(self):
        """Not a model's opinion about agreement, which would add a third
        thing that can be wrong to a measurement whose point is that only one
        variable moved."""

        sealed = package()
        primary = verdict(sealed, Verdict.CONFIRMS)

        agreeing = both_arms(FakeProvider(responses=blind_answer("confirms")))
        differing = both_arms(FakeProvider(responses=blind_answer("unrelated")))

        assert agreeing.verify_blind(sealed).agrees_with(primary) is True
        assert differing.verify_blind(sealed).agrees_with(primary) is False

    def test_the_blind_arm_is_cached_on_its_own_prompt_version(self, tmp_path):
        """The two arms must not share a cache entry. The key carries the
        prompt version, so an informed answer can never be served to a blind
        request - which would be the leak arriving through the cache."""

        cache = VerdictCache(tmp_path)
        sealed = package()
        ai = FakeProvider(responses=[answer(), blind_answer(), blind_answer()])

        service = both_arms(ai, cache)
        service.verify(verdict(sealed), sealed)
        first = service.verify_blind(sealed)
        second = both_arms(ai, cache).verify_blind(sealed)

        assert ai.call_count == 2
        assert first.verdict is second.verdict
        assert second.cached is True
