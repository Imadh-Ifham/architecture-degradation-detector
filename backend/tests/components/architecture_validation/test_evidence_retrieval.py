"""Evidence retrieval tests: the packet the model is allowed to see.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Everything the model ever reads is assembled by this subcomponent, so
    these tests are really about two questions: can a citation be checked, and
    can the evidence behind a verdict be shown to a person.

    Three carry more weight than the rest. `test_the_rule_carries_the_claim_
    its_location_and_the_quote` is the shape the whole prompt rests on - a
    quoted fragment of configuration on its own is evidence without a
    question. `test_an_absence_is_evidenced_by_the_list_that_does_not_contain
    _it` covers the one verdict class that would otherwise be unfalsifiable.
    And the two hash tests are a matched pair: a hash that is stable but
    insensitive serves a cached answer to a question nobody asked, which is
    worse than having no cache at all.
"""

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
    NothingToReasonAbout,
)
from app.components.architecture_validation.evidence_retrieval._budget import fit
from app.components.architecture_validation.evidence_retrieval._neighbourhood import (
    MAX_NEIGHBOURS,
    neighbours,
)
from app.components.architecture_validation.models import (
    ConstraintKind,
    EvidenceItem,
    EvidenceRole,
    EvidenceStrength,
    ExtractionMethod,
    FactEndpoint,
    ObservedFact,
    RelationshipKind,
    Resolution,
    SourceTier,
    Span,
)
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.recovery_gateway import SnapshotFileReader

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"
SUBJECT = FIXTURES / "subject"
SNAPSHOTS = Path(__file__).resolve().parents[3] / "data" / "snapshots"

REPOSITORY = "online-boutique"
RELEASES = ("v0.9.0", "v0.10.0")
AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)

POLICY = "kustomize/components/network-policies/network-policy-cartservice.yaml"


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


def recorded_fact(subject="frontend", object_="cartservice", release="v0.10.0"):
    """One of the real facts, picked by the names a person would use."""

    return next(
        fact
        for fact in facts(release)
        if fact.subject.name == subject and fact.object.name == object_
    )


def fact(subject="frontend", object_="cart", release="v0.10.0"):
    """A fact built here, for the cases the recording does not contain.

    The id is derived from the names, the way normalisation derives it from
    content - two different facts have to be two different ids, or a test
    about them hashing differently is really a test about one fact.
    """

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
    )


def record(
    decision_id: str,
    *,
    subject: str = "frontend",
    object_: str = "cartservice",
    constraint: ConstraintKind = ConstraintKind.MAY_CALL,
    span: Span | None = Span(path=POLICY, start_line=16, end_line=16),
    rationale: str | None = None,
):
    return decision_record(
        SourceRequest(REPOSITORY, "v0.10.0", AT),
        decision_id=decision_id,
        subject=subject,
        constraint=constraint,
        object_=object_,
        source="config_scan",
        source_repository=REPOSITORY,
        source_ref=span.path if span else "kustomize/components/service-accounts",
        source_span=span,
        source_tier=SourceTier.EXECUTABLE_CONFIG,
        source_strength=EvidenceStrength.AUTHORITATIVE,
        extraction_method=ExtractionMethod.RECONSTRUCTED,
        rationale=rationale,
    )


def service() -> EvidenceRetrievalService:
    return EvidenceRetrievalService(WorkspaceReader())


def knowledge() -> DecisionKnowledgeService:
    return DecisionKnowledgeService(
        WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
    )


def assemble(observed, resolution, release="v0.10.0"):
    return service().assemble(observed, resolution, architecture(release))


def resolution_for(observed, release="v0.10.0"):
    """The real resolution for a real fact, from the committed corpus."""

    return knowledge().resolve(observed, REPOSITORY)


class TestThePackageFromAResolution:
    """What goes in, and what each item is for."""

    def test_the_rule_carries_the_claim_its_location_and_the_quote(self):
        """A quoted fragment of configuration is evidence without a question.
        On its own, `app: frontend` does not say whose policy admits it or
        what admitting it means - so the item carries the rule as a sentence,
        where it is, and the lines themselves."""

        package = assemble(fact(), Resolution(governing=record("rule-a")))
        lines = package.items[0].text.splitlines()

        assert lines[0] == "frontend may call cartservice"
        assert lines[1] == f"{POLICY}:16"
        assert lines[2].strip() == "app: frontend"

    def test_the_quote_is_the_spans_own_lines_and_not_one_more(self):
        package = assemble(
            fact(),
            Resolution(
                governing=record(
                    "rule-a", span=Span(path=POLICY, start_line=12, end_line=13)
                )
            ),
        )
        quoted = package.items[0].text.splitlines()[2:]

        assert [line.strip() for line in quoted] == ["ingress:", "- from:"]

    def test_a_record_with_no_document_is_rendered_rather_than_quoted(self):
        """A rule about a directory, or one ratified by a person, has no lines.
        It is still evidence and still citable - only unquotable."""

        package = assemble(
            fact(),
            Resolution(
                governing=record(
                    "sa-shared-component",
                    subject="*",
                    object_="kustomize/components/service-accounts",
                    constraint=ConstraintKind.MUST_CALL_VIA,
                    span=None,
                )
            ),
        )
        item = package.items[0]

        assert item.span is None
        assert item.text == "* must call via kustomize/components/service-accounts"
        assert item.ref == "sa-shared-component"

    def test_a_rationale_becomes_an_item_of_its_own(self):
        """Separate, because the prompt presents why a rule exists differently
        from what the rule says - and the budget drops it first of the two."""

        package = assemble(
            fact(),
            Resolution(governing=record("rule-a", rationale="The cart is reached through checkout.")),
        )
        roles = [item.role for item in package.items]

        assert roles == [EvidenceRole.RULE, EvidenceRole.RATIONALE]
        assert package.items[1].text == "The cart is reached through checkout."

    def test_the_replaced_record_is_present_as_context_not_as_the_rule(self):
        """Showing that the earlier decision was considered and correctly
        rejected is the demonstration's point. A prompt that presented it as
        just another rule would invite the model to cite the very decision
        this component exists to reject - so the role carries the difference."""

        package = assemble(
            fact(),
            Resolution(
                governing=record("ADR-021"),
                superseded_ancestor="ADR-005",
                superseded=record("ADR-005"),
            ),
        )
        by_role = {item.role: item for item in package.items}

        assert package.items[0].role is EvidenceRole.RULE
        assert package.items[0].ref == "ADR-021"
        assert by_role[EvidenceRole.SUPERSEDED].ref == "ADR-005"

    def test_an_absence_is_evidenced_by_the_list_that_does_not_contain_it(self):
        """The sharpest verdict this component can reach rests on nothing
        permitting a dependency, and nothing has no span. So the package
        carries the permissions that DO exist and the reader checks the
        list."""

        package = assemble(
            fact(subject="adservice", object_="payment"),
            Resolution(
                governing=record(
                    "np-deny-all",
                    subject="*",
                    object_="*",
                    constraint=ConstraintKind.MUST_NOT_CALL,
                ),
                permitted_instead=(
                    record("rule-checkout-payment", subject="checkoutservice", object_="paymentservice"),
                ),
            ),
        )
        permitted = next(
            item for item in package.items if item.role is EvidenceRole.PERMITTED_SET
        )

        assert "checkoutservice may call paymentservice" in permitted.text
        assert "adservice" not in permitted.text
        assert f"{POLICY}:16" in permitted.text

    def test_a_disagreeing_source_is_named_without_pretending_to_be_a_quote(self):
        package = assemble(
            fact(),
            Resolution(governing=record("ADR-014"), conflicting_sources=("config_scan",)),
        )
        implication = next(
            item for item in package.items if item.role is EvidenceRole.IMPLICATION
        )

        assert "config_scan" in implication.text
        assert implication.span is None

    def test_the_items_come_out_in_the_order_the_roles_are_declared_in(self):
        """The order is the truncation order and the order a prompt reads
        them in, so it is fixed here rather than at either end."""

        package = assemble(
            fact(),
            Resolution(
                governing=record("ADR-021", rationale="why"),
                superseded=record("ADR-005"),
                conflicting_sources=("config_scan",),
            ),
        )

        assert [item.role for item in package.items] == [
            EvidenceRole.RULE,
            EvidenceRole.RATIONALE,
            EvidenceRole.SUPERSEDED,
            EvidenceRole.IMPLICATION,
        ]


class TestWhatTheGuardWillCheckAgainst:
    """`refs` is the universe of legal citations, so it has to be exact."""

    def test_every_item_is_citable_and_no_two_share_a_reference(self):
        package = assemble(
            fact(),
            Resolution(
                governing=record("ADR-021", rationale="why"),
                superseded=record("ADR-005"),
                conflicting_sources=("config_scan", "repo_adr"),
            ),
        )

        assert all(item.ref for item in package.items)
        assert len(package.refs) == len(package.items)

    def test_a_fact_with_no_governing_decision_is_refused(self):
        """The orchestrator short-circuits an uncovered or ambiguous fact
        before here, so arriving at all means the pipeline's own ordering has
        gone wrong - and an empty package would hide that behind a verdict
        with nothing under it."""

        with pytest.raises(NothingToReasonAbout):
            assemble(fact(), Resolution(governing=None, uncovered=True))

    def test_the_package_names_the_fact_it_is_for(self):
        """The verdict, the verification and the cache entry are all filed
        against it."""

        observed = recorded_fact()
        package = assemble(observed, knowledge().resolve(observed, REPOSITORY))

        assert package.fact_id == observed.fact_id


class TestTheHash:
    """Two failures, opposite to each other, and both silent."""

    def test_the_same_question_hashes_the_same_way_every_time(self):
        """If this is unstable the cache never hits: the rate limit bites, the
        demonstration cannot be warmed, and the reproducibility claim is
        false - while everything still appears to work."""

        observed = recorded_fact()
        resolution = knowledge().resolve(observed, REPOSITORY)

        assert (
            assemble(observed, resolution).evidence_hash
            == assemble(observed, resolution).evidence_hash
        )

    def test_a_changed_question_gets_a_different_hash(self):
        """The matched half. Stable but insensitive serves a cached answer to
        a question nobody asked, which is worse than no cache - the output is
        wrong rather than slow."""

        plain = assemble(fact(), Resolution(governing=record("rule-a")))
        with_reason = assemble(
            fact(), Resolution(governing=record("rule-a", rationale="because"))
        )

        assert plain.evidence_hash != with_reason.evidence_hash

    def test_two_different_facts_about_one_rule_hash_differently(self):
        """The fact is part of the question, so it is part of the hash."""

        resolution = Resolution(governing=record("rule-a"))

        assert (
            assemble(fact(subject="frontend"), resolution).evidence_hash
            != assemble(fact(subject="checkoutservice"), resolution).evidence_hash
        )


class TestAgainstTheRecordedReleases:
    """All thirty packages, from the real corpus and the real facts."""

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_fact_produces_a_citable_package(self, release):
        store = knowledge()
        built = [
            assemble(observed, store.resolve(observed, REPOSITORY), release)
            for observed in facts(release)
        ]

        assert len(built) == 15
        assert all(package.evidence_hash for package in built)
        assert all(item.ref for package in built for item in package.items)

    @pytest.mark.parametrize("release", RELEASES)
    def test_fifteen_facts_are_fifteen_distinct_questions(self, release):
        """If two facts hashed alike, one would be answered with the other's
        cached verdict."""

        store = knowledge()
        hashes = {
            assemble(observed, store.resolve(observed, REPOSITORY), release).evidence_hash
            for observed in facts(release)
        }

        assert len(hashes) == 15

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_quoted_span_resolves_to_the_file_it_names(self, release):
        """The whole point of a span: a reader can open it."""

        store = knowledge()
        for observed in facts(release):
            package = assemble(observed, store.resolve(observed, REPOSITORY), release)
            for item in package.items:
                if item.span is None:
                    continue
                located = SUBJECT / release / item.span.path

                assert located.exists()
                assert item.span.end_line <= len(
                    located.read_text(encoding="utf-8").splitlines()
                )

class TestTheNeighbourhood:
    """Context chosen by structure, not by wording.

    This is the arm the retrieval experiment measures: neighbours are here
    because they are adjacent, not because their names read alike.
    """

    def test_it_is_one_hop_and_no_further(self):
        """Two hops on a twelve-element system is most of the graph, which is
        not context - it is noise with a token bill."""

        package = assemble(recorded_fact(), resolution_for(recorded_fact()))
        context = [
            item.text
            for item in package.items
            if item.role is EvidenceRole.STRUCTURAL_CONTEXT
        ]

        # paymentservice is two hops from frontend: only checkoutservice reaches it.
        assert context
        assert not any("paymentservice" in sentence for sentence in context)

    def test_it_names_the_direction(self):
        """"Also reached by" and "also reaches" are different facts, and a
        reviewer judging whether a dependency is reasonable needs to know
        which one they are looking at."""

        package = assemble(recorded_fact(), resolution_for(recorded_fact()))
        context = [
            item.text
            for item in package.items
            if item.role is EvidenceRole.STRUCTURAL_CONTEXT
        ]

        assert "cartservice is also reached by checkoutservice" in context
        assert "frontend is also reached by loadgenerator" in context

    def test_it_never_exceeds_the_cap(self):
        """One hop from a hub could be eleven neighbours, and that one fact
        would then cost more than five others combined."""

        for observed in facts("v0.10.0"):
            package = assemble(observed, resolution_for(observed))
            context = [
                item
                for item in package.items
                if item.role is EvidenceRole.STRUCTURAL_CONTEXT
            ]

            assert len(context) <= MAX_NEIGHBOURS

    def test_the_two_ends_of_the_fact_are_not_their_own_neighbours(self):
        package = assemble(recorded_fact(), resolution_for(recorded_fact()))
        context = " ".join(
            item.text
            for item in package.items
            if item.role is EvidenceRole.STRUCTURAL_CONTEXT
        )

        assert "frontend also reaches cartservice" not in context

    def test_a_name_a_decision_mentions_is_kept_first(self):
        """The cap means something has to be kept first, and a neighbour some
        rule has an opinion about is more use than one nothing mentions."""

        observed = recorded_fact(subject="frontend", object_="cartservice")
        preferred = neighbours(
            architecture(), observed, frozenset({"checkout"}), limit=1
        )

        assert preferred == ("cartservice is also reached by checkoutservice",)

    def test_the_same_fact_gives_the_same_neighbourhood_in_the_same_order(self):
        """The package's hash is the cache key, so an order that varied
        between runs would miss the cache without saying so."""

        observed = recorded_fact()
        resolution = resolution_for(observed)

        assert [item.ref for item in assemble(observed, resolution).items] == [
            item.ref for item in assemble(observed, resolution).items
        ]


class TestTheBudget:
    """What is dropped is decided in advance, and reported."""

    def test_a_package_within_its_budget_is_not_marked_truncated(self):
        package = assemble(recorded_fact(), resolution_for(recorded_fact()))

        assert package.truncated is False
        assert package.dropped_roles == ()

    def test_a_truncated_package_says_so_and_keeps_the_rule(self):
        """A verdict can rest on the rule alone. It can never rest on a
        neighbour."""

        package = service().assemble(
            recorded_fact(), resolution_for(recorded_fact()), architecture(), budget=2
        )

        assert package.truncated is True
        assert len(package.items) == 2
        assert package.items[0].role is EvidenceRole.RULE

    def test_a_role_that_loses_every_item_is_named(self):
        """Saying "a kind of evidence is missing" is sharper than saying
        "something was dropped", and M6 can weigh it."""

        package = service().assemble(
            recorded_fact(), resolution_for(recorded_fact()), architecture(), budget=1
        )

        assert EvidenceRole.STRUCTURAL_CONTEXT in package.dropped_roles

    def test_the_weakest_role_goes_first(self):
        kept, dropped = fit(
            (
                EvidenceItem(ref="r", role=EvidenceRole.RULE, text="rule"),
                EvidenceItem(ref="c", role=EvidenceRole.STRUCTURAL_CONTEXT, text="n"),
                EvidenceItem(ref="i", role=EvidenceRole.IMPLICATION, text="imp"),
            ),
            limit=2,
        )

        assert [item.ref for item in kept] == ["r", "i"]
        assert dropped == (EvidenceRole.STRUCTURAL_CONTEXT,)

    def test_what_survives_is_a_prefix_of_what_was_offered(self):
        """So a reader of two packages for one fact, at two budgets, sees the
        shorter one inside the longer one rather than a different question."""

        whole = assemble(recorded_fact(), resolution_for(recorded_fact()))
        short = service().assemble(
            recorded_fact(), resolution_for(recorded_fact()), architecture(), budget=3
        )

        assert [item.ref for item in short.items] == [
            item.ref for item in whole.items if item.ref in {i.ref for i in short.items}
        ]

    def test_truncating_changes_the_hash(self):
        """A shorter question is a different question, and must not be
        answered from the fuller one's cache entry."""

        whole = assemble(recorded_fact(), resolution_for(recorded_fact()))
        short = service().assemble(
            recorded_fact(), resolution_for(recorded_fact()), architecture(), budget=2
        )

        assert whole.evidence_hash != short.evidence_hash
