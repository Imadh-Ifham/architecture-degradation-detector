"""Validation reasoning tests: the judge that cannot hallucinate.

Author: Aman Mohamed M.A
Date: 2026-10-16
Description:
    The arbiter is the component's answer to the question everybody asks about
    it: if the reasoner and the verifier are wrong in the same direction, what
    notices? These tests are that answer, so two of them carry more weight
    than the rest.

    `test_the_general_refusal_contradicts_anything_it_governs` is the row that
    reaches a contradiction without a named prohibition, which is how a
    violation is found on a repository that never wrote one down. And the
    three abstention tests matter more than the five decided rows, because a
    table that answered everything would report a check nothing made - which
    is the one failure that looks exactly like a success.

    The whole file runs with no key, no network and no provider.
"""

import ast
import inspect
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from app.components.architecture_validation._release import release_sort_key
from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
    SourceRequest,
)
from app.components.architecture_validation.decision_knowledge.sources.base import (
    decision_record,
)
from app.components.architecture_validation.evidence_retrieval import (
    EvidenceRetrievalService,
)
from app.components.architecture_validation.models import (
    ArbiterAgreement,
    ArbiterCheck,
    ConstraintKind,
    EvidenceStrength,
    ExtractionMethod,
    FactEndpoint,
    GuardFailure,
    ObservedFact,
    RelationshipKind,
    Resolution,
    SourceTier,
    Span,
    Verdict,
    VerdictSource,
)
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.components.architecture_validation.validation_reasoning import (
    ArbiterOnlyRefused,
    ValidationReasoningService,
)
from app.components.architecture_validation.validation_reasoning._arbiter import decide
from app.components.architecture_validation.validation_reasoning._guards import check
from app.components.architecture_validation.validation_reasoning._prompt import (
    render,
    verdict_schema,
)
from app.infrastructure.ai import (
    TASK_PRIMARY_VERDICT,
    TASK_PRIMARY_VERDICT_FALLBACK,
    TASK_PRIMARY_VERDICT_LOCAL,
    AISettings,
    ConfiguredAIClient,
    VerdictCache,
)
from app.infrastructure.ai.prompt_library import load_prompt
from app.infrastructure.ai.providers.fake import FakeProvider
from app.infrastructure.ai.providers.openai_compatible import strictify
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.recovery_gateway import SnapshotFileReader

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"
SUBJECT = FIXTURES / "subject"
SNAPSHOTS = Path(__file__).resolve().parents[3] / "data" / "snapshots"

ARBITER = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "components"
    / "architecture_validation"
    / "validation_reasoning"
    / "_arbiter.py"
)

REPOSITORY = "online-boutique"
RELEASES = ("v0.9.0", "v0.10.0")
AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)

POLICY = "kustomize/components/network-policies/network-policy-cartservice.yaml"

TEMPLATE = load_prompt("primary_verdict.v1.md")
"""The real prompt file, read once. R3 is not tested against a stand-in:
the file and the renderer are two halves of one artifact and they drift."""


class WorkspaceReader:
    """Reads the generated subject tree in place of an ingested checkout."""

    def read_text(self, repository_id, release_id, path):
        return (SUBJECT / release_id / path).read_text(encoding="utf-8")

    def list_paths(self, repository_id, release_id, pattern):
        root = SUBJECT / release_id
        return sorted(
            str(match.relative_to(root)).replace("\\", "/")
            for match in root.glob(pattern)
            if match.is_file()
        )


def architecture(release: str = "v0.10.0"):
    return SnapshotFileReader(SNAPSHOTS).read(REPOSITORY, release)


def facts(release: str = "v0.10.0"):
    return ObservationNormalizationService().normalise(architecture(release)).facts


def knowledge() -> DecisionKnowledgeService:
    return DecisionKnowledgeService(
        WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
    )


def governed(release: str):
    """Every fact of one release that resolved to a governing decision.

    The arbiter is only ever asked about these: an uncovered or ambiguous fact
    has no rule to be checked against, which is why it reaches its bucket with
    nothing consulting a model either.
    """

    store = knowledge()
    for observed in facts(release):
        resolution = store.resolve(observed, REPOSITORY)
        if resolution.governing is not None:
            yield observed, resolution


def service() -> EvidenceRetrievalService:
    return EvidenceRetrievalService(WorkspaceReader())


def recorded_fact(subject="frontend", object_="cartservice", release="v0.10.0"):
    """One of the real facts, picked by the names a person would use."""

    return next(
        observed
        for observed in facts(release)
        if observed.subject.name == subject and observed.object.name == object_
    )


def resolution_for(observed):
    return knowledge().resolve(observed, REPOSITORY)


def package(subject="frontend", object_="cartservice", release="v0.10.0"):
    """A real sealed package, out of M3 and over the committed corpus."""

    observed = recorded_fact(subject, object_, release)
    return service().assemble(observed, resolution_for(observed), architecture(release))


def fact(subject="frontend", object_="cartservice", release="v0.10.0", **attributes):
    """A fact built here, for the pairs the recording does not contain."""

    return ObservedFact(
        fact_id=sha256(f"{subject}|{object_}|{release}".encode()).hexdigest()[:16],
        release_id=release,
        release_sort_key=release_sort_key(release),
        subject=FactEndpoint(id="e1", name=subject, canonical=subject),
        relationship=RelationshipKind.COMMUNICATES_WITH,
        object=FactEndpoint(id="e2", name=object_, canonical=object_),
        style_resolved="microservices",
        style_source="c1",
        quality="confirmed",
        attributes=attributes,
    )


def record(
    decision_id: str = "rule-frontend-cartservice",
    *,
    subject: str = "frontend",
    object_: str = "cartservice",
    constraint: ConstraintKind = ConstraintKind.MAY_CALL,
    tier: SourceTier = SourceTier.EXECUTABLE_CONFIG,
):
    return decision_record(
        SourceRequest(REPOSITORY, "v0.10.0", AT),
        decision_id=decision_id,
        subject=subject,
        constraint=constraint,
        object_=object_,
        source="config_scan",
        source_repository=REPOSITORY,
        source_ref=POLICY,
        source_span=Span(path=POLICY, start_line=16, end_line=16),
        source_tier=tier,
        source_strength=EvidenceStrength.AUTHORITATIVE,
        extraction_method=ExtractionMethod.RECONSTRUCTED,
    )


class TestTheTable:
    """One row at a time, and each one names itself in the basis."""

    def test_a_permission_with_the_dependency_observed_confirms(self):
        """The simplest row, and the one the demonstration leans on fifteen
        times."""

        check = decide(fact(), record())

        assert check.verdict is Verdict.CONFIRMS
        assert "named as permitted" in check.basis

    def test_a_named_prohibition_contradicts(self):
        check = decide(
            fact("adservice", "paymentservice"),
            record(
                "ADR-014",
                subject="adservice",
                object_="paymentservice",
                constraint=ConstraintKind.MUST_NOT_CALL,
            ),
        )

        assert check.verdict is Verdict.CONTRADICTS
        assert "named as forbidden" in check.basis

    def test_the_general_refusal_contradicts_anything_it_governs(self):
        """The default deny is one record about every pair, so this row is how
        a contradiction is reached in a repository that never wrote a
        prohibition down. Its basis has to say that nothing names the pair -
        read as a named prohibition it would be an accusation the
        configuration does not make."""

        check = decide(
            fact("adservice", "paymentservice"),
            record(
                "np-deny-all",
                subject="*",
                object_="*",
                constraint=ConstraintKind.MUST_NOT_CALL,
            ),
        )

        assert check.verdict is Verdict.CONTRADICTS
        assert "nothing names this pair" in check.basis
        assert "forbidden" not in check.basis

    def test_an_intermediary_rule_distinguishes_through_from_around(self):
        via = record(
            "ADR-021",
            subject="checkoutservice",
            object_="redis-proxy",
            constraint=ConstraintKind.MUST_CALL_VIA,
        )

        through = decide(fact("checkoutservice", "redisproxy"), via)
        around = decide(fact("checkoutservice", "rediscart"), via)

        assert through.verdict is Verdict.CONFIRMS
        assert around.verdict is Verdict.CONTRADICTS
        assert "bypasses" in around.basis

    def test_a_contract_confirms_the_operation_it_declares(self):
        check = decide(
            fact("frontend", "cartservice", operation="AddItem"),
            record(
                "rpc-cartservice-additem",
                subject="CartService",
                object_="AddItem",
                constraint=ConstraintKind.DECLARED_RPC,
            ),
        )

        assert check.verdict is Verdict.CONFIRMS
        assert "declared in the service contract" in check.basis


class TestWhereItAbstains:
    """An oracle that answers everything is not an oracle.

    Each of these would otherwise be a confident mechanical verdict, and a
    mechanical verdict is harder to argue with than a model's - so the cases
    where the table's premise does not hold are the ones worth testing most.
    """

    def test_it_abstains_below_executable_configuration(self):
        """A tier 3 record had its pair inferred from prose, so the premise
        that subject and object mean what they say is the thing in doubt."""

        check = decide(fact(), record(tier=SourceTier.DOCUMENTATION))

        assert check.verdict is None
        assert "inferred from prose" in check.basis

    def test_a_rule_about_every_element_does_not_accuse_one_dependency(self):
        """`sa-shared-component` requires that workload identity be declared
        in one shared overlay. `frontend -> cartservice` does not bypass it:
        the rule is about another axis, and a contradiction here would be a
        false accusation with a table's authority behind it."""

        check = decide(
            fact(),
            record(
                "sa-shared-component",
                subject="*",
                object_="kustomize/components/service-accounts",
                constraint=ConstraintKind.MUST_CALL_VIA,
            ),
        )

        assert check.verdict is None
        assert "rather than of a pair" in check.basis

    def test_a_contract_record_abstains_on_a_fact_that_names_no_operation(self):
        """Which is every fact today: an observed dependency comes out of
        deployment manifests and names no operation. Confirming regardless
        would be a check that passed without looking."""

        contract = record(
            "rpc-cartservice-additem",
            subject="CartService",
            object_="AddItem",
            constraint=ConstraintKind.DECLARED_RPC,
        )

        check = decide(fact(), contract)

        assert check.verdict is None
        assert "nothing to compare" in check.basis

    def test_a_constraint_with_no_row_raises_rather_than_abstaining(self):
        """An abstention would report the fact as one the table considered and
        could not decide. It did not consider it."""

        unknown = replace(record(), constraint="may_publish_to")

        with pytest.raises(ValueError, match="no row"):
            decide(fact(), unknown)


class TestAgainstTheRecordedReleases:
    """The table over every resolution the committed corpus produces."""

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_governed_fact_gets_an_answer_or_a_reason(self, release):
        """No silent third state. An abstention with no basis would be a fact
        nothing checked, reported as though something had."""

        checked = [decide(observed, r.governing) for observed, r in governed(release)]

        assert len(checked) == 15
        for check in checked:
            assert check.basis
            assert check.verdict in (None, Verdict.CONFIRMS, Verdict.CONTRADICTS)

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_corpus_is_decided_on_one_row_of_the_six(self, release):
        """Said out loud here rather than left for a reader to notice. Every
        dependency in the subject system is explicitly permitted at both
        releases, so the arbiter decides thirty of thirty and uses the
        `may_call` row for all of them. The rows that contradict are proved by
        the constructed records above - which is a result about this corpus
        containing no violation, not a gap in the mechanism."""

        kinds = {r.governing.constraint for _, r in governed(release)}
        verdicts = {decide(o, r.governing).verdict for o, r in governed(release)}

        assert kinds == {ConstraintKind.MAY_CALL}
        assert verdicts == {Verdict.CONFIRMS}


class TestItHasNoModelInIt:
    """The claim the whole design rests on, asserted against the source.

    The thing deciding whether the models are believed has to be incapable of
    the failure it is checking for, and that is a property of what the module
    can reach rather than of what it currently does.
    """

    def test_it_reaches_nothing_outside_the_component(self):
        tree = ast.parse(ARBITER.read_text(encoding="utf-8"))
        absolute = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            or (isinstance(node, ast.ImportFrom) and node.level == 0)
        ]

        assert absolute == []

    @pytest.mark.parametrize(
        "module", sorted(ARBITER.parent.glob("*.py")), ids=lambda path: path.name
    )
    def test_no_module_here_names_a_provider_a_key_or_a_file(self, module):
        """The whole subcomponent, not only the arbiter. It asks for a task and
        hands over a schema; the moment one of these words appears, it has
        started choosing a model or reaching for a credential."""

        body = module.read_text(encoding="utf-8").lower()

        for forbidden in (
            "httpx",
            "requests",
            "anthropic",
            "openai",
            "groq",
            "ai_api_key",
            "ai_base_url",
            "open(",
            "pathlib",
            "os.path",
        ):
            assert forbidden not in body, f"{module.name} names {forbidden}"


class TestTheRenderedPrompt:
    """What the model is shown, and the one thing it must never be shown.

    `test_the_prompt_never_mentions_the_arbiter` is the most important test in
    R3. Tell the model what the table decided and it agrees with it: the
    agreement rate goes to a hundred per cent, every measured number in the
    research improves, and the only uncorrelated check in the component is
    gone.
    """

    def test_every_item_is_rendered_with_its_reference_and_its_role(self):
        """A model cites what it can name, so an item without its reference is
        an item that cannot be cited. The role is there because *this rule is
        in force* and *this one was replaced* are otherwise the same text."""

        rendered = render(TEMPLATE, package())

        for item in package().items:
            assert item.ref in rendered
            assert str(item.role) in rendered
            assert item.text.splitlines()[0] in rendered

    def test_the_prompt_states_the_question_it_is_asking(self):
        rendered = render(TEMPLATE, package())

        assert "frontend" in rendered
        assert "cartservice" in rendered
        assert "communicates-with" in rendered
        assert "v0.10.0" in rendered

    def test_the_prompt_never_mentions_the_arbiter(self):
        """Asserted on the text as well as on the signature, because the
        signature only stops the answer arriving as an argument."""

        rendered = render(TEMPLATE, package()).lower()

        assert "arbiter" not in rendered
        assert "basis" not in rendered

    def test_the_renderer_takes_the_template_and_the_package_and_nothing_else(self):
        """The whole of Guard B's premise. A renderer that could reach the fact
        or the resolution would be showing the model evidence nobody sealed,
        and the citation set would stop being the evidence set without one
        other test failing."""

        assert list(inspect.signature(render).parameters) == ["template", "package"]

    def test_the_evidence_hash_is_not_rendered(self):
        """It is the cache key, not evidence. A model given it is given a
        number it cannot check and could cite."""

        assert package().evidence_hash not in render(TEMPLATE, package())

    def test_every_placeholder_in_the_file_is_filled(self):
        """The prompt is a file and the renderer is code, so they can drift.
        A placeholder left in the text reaches the model as a literal
        `{{subject}}`, which it will answer anyway."""

        assert "{{" not in render(TEMPLATE, package())

    def test_a_shortened_package_says_so_and_names_what_it_lost(self):
        """A question weakened to fit a budget has to be answered as one."""

        shortened = service().assemble(
            recorded_fact(), resolution_for(recorded_fact()), architecture(), budget=1
        )
        rendered = render(TEMPLATE, shortened)

        assert "shortened" in rendered
        assert "structural_context" in rendered

    def test_a_whole_package_carries_no_warning(self):
        assert "shortened" not in render(TEMPLATE, package())


class TestTheVerdictSchema:
    """The shape of the answer, and why its field order is load-bearing."""

    def test_the_reasoning_and_the_citations_are_declared_before_the_verdict(self):
        """Constrained decoding generates fields in declaration order, so this
        is what makes the model commit to its reasoning and to the evidence it
        rests on before it names a conclusion - a reasoning trace at the cost
        of no extra call."""

        properties = list(verdict_schema()["properties"])

        assert properties.index("reasoning") < properties.index("verdict")
        assert properties.index("cited_evidence_refs") < properties.index("verdict")

    def test_strictifying_it_does_not_reorder_the_fields(self):
        """The helper existed; that it preserves declaration order did not.
        Alphabetically `cited_evidence_refs` sorts first, so a sorted
        `required` list would hand the provider a different order from the one
        the schema declares - and nothing in the output would say so."""

        strict = strictify(verdict_schema())

        assert list(strict["properties"]) == list(verdict_schema()["properties"])
        assert strict["required"] == ["reasoning", "cited_evidence_refs", "verdict"]

    def test_the_verdict_is_closed_to_the_five_values(self):
        """A string field can return anything. Under strict schema a closed
        enum cannot, so an out-of-vocabulary verdict stops being something the
        guards have to catch."""

        assert verdict_schema()["properties"]["verdict"]["enum"] == [
            "confirms",
            "contradicts",
            "partially_confirms",
            "unrelated",
            "insufficient_evidence",
        ]

    def test_a_verdict_must_cite_something(self):
        citations = verdict_schema()["properties"]["cited_evidence_refs"]

        assert citations["minItems"] == 1

    def test_strictifying_it_forbids_anything_else_coming_back(self):
        strict = strictify(verdict_schema())

        assert strict["additionalProperties"] is False


TASKS = (
    TASK_PRIMARY_VERDICT,
    TASK_PRIMARY_VERDICT_FALLBACK,
    TASK_PRIMARY_VERDICT_LOCAL,
)


def reasoner(
    provider: FakeProvider,
    cache: VerdictCache | None = None,
    allow_arbiter_only: bool = True,
):
    """The real service over the real client, with a scripted provider.

    Built through `ConfiguredAIClient` rather than a hand-written stub, so the
    cache key, the strict-schema check and the translation of a provider's
    failure into the port's own error are all exercised by these tests rather
    than assumed.

    The one fake answers for both endpoints, so a test counting calls counts
    the whole ladder rather than the hosted part of it. That the two endpoints
    are really distinct is a property of the client and is tested there; here
    the subject is the order the rungs are tried in.
    """

    settings = AISettings(
        ai_api_key="not-a-real-key", ai_local_base_url="http://localhost:11434/v1"
    )
    client = ConfiguredAIClient(
        provider,
        settings=settings,
        cache=cache or VerdictCache("unused", enabled=False),
        local_provider=provider,
    )
    return ValidationReasoningService(
        client,
        TEMPLATE,
        TASKS,
        provider="fake",
        allow_arbiter_only=allow_arbiter_only,
    )


def answer(
    verdict: str = "confirms",
    cited: tuple[str, ...] = ("rule-frontend-cartservice",),
    reasoning: str = "the policy names frontend among the peers that may reach it",
) -> dict:
    return {
        "reasoning": reasoning,
        "cited_evidence_refs": list(cited),
        "verdict": verdict,
    }


def confirms() -> ArbiterCheck:
    return ArbiterCheck(Verdict.CONFIRMS, "the dependency is named as permitted")


def abstains() -> ArbiterCheck:
    return ArbiterCheck(None, "the pair was inferred from prose")


def package_with_supersession():
    """A package that carries the decision the resolver rejected.

    The committed corpus never produces one - `sa-shared-component` was
    superseded but governs no observed dependency - so the one case Guard D
    exists for is built here.
    """

    observed = recorded_fact()
    return service().assemble(
        observed,
        Resolution(
            governing=record("rule-frontend-cartservice"),
            superseded_ancestor="sa-shared-component",
            superseded=record(
                "sa-shared-component",
                subject="*",
                object_="kustomize/components/service-accounts",
                constraint=ConstraintKind.MUST_CALL_VIA,
            ),
        ),
        architecture(),
    )


class TestTheGuards:
    """Four checks in plain Python, and the schema can express none of them.

    `test_guard_b_rejects_a_phantom_citation` is the most important test in
    the subcomponent. `["ADR-999"]` is perfectly schema-valid, so without that
    comparison *enforced citation* quietly becomes *requested citation* - and
    the degradation is invisible, because the answer still looks right.
    """

    def test_guard_a_rejects_an_answer_with_no_reasoning(self):
        outcome = check(answer(reasoning="  "), package())

        assert outcome.accepted is False
        assert outcome.failure is GuardFailure.MALFORMED

    def test_guard_a_rejects_a_verdict_outside_the_vocabulary(self):
        """Impossible under strict schema, which is exactly why it is checked:
        strict mode is a request, and a provider can serve it without
        honouring it."""

        outcome = check(answer(verdict="probably_fine"), package())

        assert outcome.failure is GuardFailure.MALFORMED

    def test_an_answer_that_cites_nothing_is_not_called_malformed(self):
        """It is well formed and groundless, which is a different problem with
        a different fix."""

        outcome = check(answer(cited=()), package())

        assert outcome.failure is GuardFailure.NO_CITATION

    def test_guard_b_rejects_a_phantom_citation(self):
        outcome = check(answer(cited=("ADR-999",)), package())

        assert outcome.accepted is False
        assert outcome.failure is GuardFailure.UNRESOLVED_CITATION
        assert outcome.refs_at_fault == ("ADR-999",)

    def test_guard_b_names_only_the_references_that_did_not_resolve(self):
        """A rejection that says only *a citation was wrong* cannot tell an
        invented document from a real decision that was not in this package."""

        outcome = check(
            answer(cited=("rule-frontend-cartservice", "ADR-999")), package()
        )

        assert outcome.refs_at_fault == ("ADR-999",)

    def test_guard_c_rejects_a_conclusion_resting_on_a_neighbour(self):
        """M3's budget module says in prose that a verdict may rest on the rule
        alone and never on a neighbour. Until this guard that was a comment."""

        neighbour = "context:frontend-also-reaches-adservice"
        outcome = check(answer(cited=(neighbour,)), package())

        assert outcome.failure is GuardFailure.CONTEXT_ONLY_CITATION

    def test_guard_c_leaves_an_inconclusive_answer_alone(self):
        """`insufficient_evidence` claims nothing about what was decided, so it
        may cite whatever led it there."""

        neighbour = "context:frontend-also-reaches-adservice"
        outcome = check(
            answer(verdict="insufficient_evidence", cited=(neighbour,)), package()
        )

        assert outcome.accepted is True

    def test_guard_d_refuses_a_verdict_resting_on_the_replaced_decision(self):
        """`sa-shared-component` is in the package as context: it is the
        decision M2 considered and correctly rejected. A verdict resting on it
        is the single most embarrassing output this component could produce,
        and it would look entirely normal."""

        outcome = check(
            answer(cited=("sa-shared-component",)), package_with_supersession()
        )

        assert outcome.failure is GuardFailure.SUPERSEDED_AS_GOVERNING

    def test_the_replaced_decision_may_be_cited_beside_the_rule(self):
        """Which is how a model shows it read the whole package rather than
        the first item."""

        outcome = check(
            answer(cited=("rule-frontend-cartservice", "sa-shared-component")),
            package_with_supersession(),
        )

        assert outcome.accepted is True


class TestTheVerdictAndTheLadder:
    """What `judge` returns, and what it costs."""

    def test_a_resolvable_citation_is_accepted(self):
        result = reasoner(FakeProvider(answer())).judge(package(), confirms())

        assert result.verdict is Verdict.CONFIRMS
        assert result.cited_evidence_refs == ("rule-frontend-cartservice",)
        assert result.produced_by is VerdictSource.MODEL
        assert result.ladder_rung == 1

    def test_a_phantom_citation_is_retried_once_and_then_degrades(self):
        ai = FakeProvider([answer(cited=("ADR-999",)), answer(cited=("ADR-999",))])

        result = reasoner(ai).judge(package(), confirms())

        assert result.verdict is Verdict.INSUFFICIENT_EVIDENCE
        assert GuardFailure.UNRESOLVED_CITATION in result.guard_failures
        assert result.retried is True
        assert ai.call_count == 2

    def test_the_retry_asks_the_identical_question(self):
        """A retry that nudges the model - *please cite only the evidence
        given* - is a different question, so the cache key stops describing
        what was asked and the flip rate stops meaning anything."""

        ai = FakeProvider([answer(cited=("ADR-999",)), answer(cited=("ADR-999",))])

        reasoner(ai).judge(package(), confirms())

        assert len(set(ai.prompts())) == 1

    def test_malformed_twice_degrades_and_never_confirms(self):
        ai = FakeProvider(malformed_times=2)

        result = reasoner(ai).judge(package(), confirms())

        assert result.verdict is Verdict.INSUFFICIENT_EVIDENCE
        assert result.retried is True
        assert GuardFailure.MALFORMED in result.guard_failures

    def test_a_guard_failure_never_moves_sideways_to_another_model(self):
        """A second model answering a question the first one botched is a
        different question, and the comparison would mean nothing."""

        ai = FakeProvider([answer(cited=("ADR-999",))] * 4)

        reasoner(ai).judge(package(), confirms())

        assert {call["model_id"] for call in ai.calls} == {
            AISettings().ai_reasoner_model
        }

    def test_a_dead_provider_still_produces_a_verdict_from_the_arbiter(self):
        """Rung 5. The demonstration cannot be ended by a model."""

        result = reasoner(FakeProvider(fail_times=9)).judge(
            package(),
            ArbiterCheck(Verdict.CONFIRMS, "the general refusal does not apply"),
        )

        assert result.verdict is Verdict.CONFIRMS
        assert result.produced_by is VerdictSource.ARBITER
        assert result.model_id == "none"
        assert result.reasoning.startswith("No model was available")
        assert result.ladder_rung == 5

    def test_the_no_model_rung_is_allowed_unless_a_run_turns_it_off(self):
        """The default has to be permissive: rung 5 is the demonstration's
        rollback, and a rollback disarmed by default is not one."""

        assert AISettings().ai_allow_arbiter_only is True

    def test_a_run_that_reports_numbers_refuses_the_table_alone(self):
        """The other half of rung 5, and the reason it needs a switch.

        A keyless run degrades every governed fact to the table and each
        verdict honestly says so - but a figure drawn from that run would
        describe the table while being read as describing a model. Nothing in
        the output is wrong; the aggregate is. So a run whose numbers get
        reported fails instead, and the error names the fact it stopped on.
        """

        subject = reasoner(FakeProvider(fail_times=9), allow_arbiter_only=False)

        with pytest.raises(ArbiterOnlyRefused, match="does not allow a verdict"):
            subject.judge(package(), confirms())

    def test_refusing_the_table_does_not_refuse_a_model_that_answered(self):
        """The switch is about the absence of a model and nothing else. With
        one answering, a run that forbids the table is an ordinary run."""

        result = reasoner(
            FakeProvider(answer()), allow_arbiter_only=False
        ).judge(package(), confirms())

        assert result.produced_by is VerdictSource.MODEL

    def test_a_verdict_from_the_arbiter_still_cites_something_that_exists(self):
        """The citation contract is not relaxed because no model was involved:
        what the verdict rests on is in the package and can be opened."""

        result = reasoner(FakeProvider(fail_times=9)).judge(package(), confirms())

        assert result.cited_evidence_refs
        assert not set(result.cited_evidence_refs) - package().refs

    def test_an_arbiter_verdict_reports_no_agreement_rather_than_no_check(self):
        """The arbiter *was* the verdict, so there is nothing to compare it
        with - and `not_checked` would be wrong, because that value means the
        table abstained."""

        result = reasoner(FakeProvider(fail_times=9)).judge(package(), confirms())

        assert result.arbiter_agreement is None

    def test_nothing_reachable_and_an_abstaining_table_claims_nothing(self):
        result = reasoner(FakeProvider(fail_times=9)).judge(package(), abstains())

        assert result.verdict is Verdict.INSUFFICIENT_EVIDENCE
        assert result.arbiter_agreement is ArbiterAgreement.NOT_CHECKED
        assert result.ladder_rung == 6

    def test_the_ladder_tries_each_model_once_and_stops(self):
        """Three calls, not four: the retry sits on the first rung only, so the
        longest path is first model, next model, model after that. On a
        tokens-per-minute free tier an unbounded ladder is how a demonstration
        exhausts its budget while appearing to work."""

        ai = FakeProvider(fail_times=99)

        reasoner(ai).judge(package(), confirms())

        assert ai.call_count == 3
        assert len({call["model_id"] for call in ai.calls}) == 3

    def test_a_rate_limit_moves_down_the_ladder_rather_than_retrying(self):
        """The thing that just refused the request is the thing that would
        refuse it again."""

        ai = FakeProvider(answer(), rate_limit_times=1)

        result = reasoner(ai).judge(package(), confirms())

        assert result.verdict is Verdict.CONFIRMS
        assert ai.call_count == 2
        assert result.ladder_rung == 3

    def test_a_warmed_cache_answers_without_a_call(self, tmp_path):
        """Rung 0, and the reason a whole release can be replayed in a demo
        slot with the network unplugged."""

        cache = VerdictCache(tmp_path / "cache")
        ai = FakeProvider(answer())
        with_cache = reasoner(ai, cache)

        first = with_cache.judge(package(), confirms())
        again = with_cache.judge(package(), confirms())

        assert first.cached is False and first.ladder_rung == 1
        assert again.cached is True and again.ladder_rung == 0
        assert ai.call_count == 1


class TestTheThreeWayComparison:
    """The answer to *what if both models are wrong the same way?*"""

    def test_agreement_with_the_table_is_recorded_as_a_property_of_the_fact(self):
        result = reasoner(FakeProvider(answer())).judge(package(), confirms())

        assert result.arbiter_agreement is ArbiterAgreement.AGREED
        assert result.arbiter == confirms()

    def test_the_model_disagreeing_with_the_table_is_recorded_not_resolved(self):
        """The model's answer is kept, because overwriting it would make the
        model decoration and would throw away the only data that could ever
        show the table itself to be wrong. The conflict is published."""

        mechanical = ArbiterCheck(
            Verdict.CONTRADICTS, "nothing names this pair and the default is deny"
        )

        result = reasoner(FakeProvider(answer())).judge(package(), mechanical)

        assert result.verdict is Verdict.CONFIRMS
        assert result.arbiter_agreement is ArbiterAgreement.DISAGREED
        assert mechanical.basis in result.disagreement_note

    def test_a_refinement_the_table_cannot_speak_to_is_not_a_disagreement(self):
        """`partially_confirms` and `unrelated` are refinements of a two-value
        oracle's vocabulary. Calling them a disagreement would manufacture a
        conflict out of a vocabulary mismatch."""

        result = reasoner(FakeProvider(answer(verdict="unrelated"))).judge(
            package(), confirms()
        )

        assert result.arbiter_agreement is ArbiterAgreement.NOT_COMPARABLE

    def test_a_fact_the_table_abstained_on_says_nothing_checked_it(self):
        result = reasoner(FakeProvider(answer())).judge(package(), abstains())

        assert result.arbiter_agreement is ArbiterAgreement.NOT_CHECKED
        assert result.disagreement_note == ""

    def test_every_verdict_carries_its_provenance(self):
        """Two runs on two providers, or one strict and one best-effort, are
        not the same experiment - and provenance cannot be added to results
        that already exist."""

        result = reasoner(FakeProvider(answer())).judge(package(), confirms())

        assert result.model_id and result.provider and result.prompt_version
        assert result.schema_mode == "strict"
        assert result.evidence_hash == package().evidence_hash
