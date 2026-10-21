"""Resolver tests: which decision governed, at one release.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    The most important tests in the component. Everything else here produces
    inputs for this one question, and the answer is what the rest of the
    pipeline reasons about.

    Two of them carry the research claim. `test_the_superseded_record_never_
    governs` is the claim itself. `test_the_same_query_at_the_earlier_release_
    resolves_to_the_earlier_decision` is the one that proves the resolver
    reads *intervals* - a resolver that simply returns the newest decision
    passes the first and fails the second, and it is wrong on every
    historical query, which is exactly what the next component does for a
    living.

    The boundary test is third in importance and the easiest to leave out.
    The demonstration's own release sits exactly on an interval boundary, so
    a closed upper bound would put it in two windows and report an ambiguity
    that does not exist.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.components.architecture_validation._release import release_sort_key
from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
    SourceRequest,
)
from app.components.architecture_validation.decision_knowledge._index import (
    DecisionIndex,
)
from app.components.architecture_validation.decision_knowledge.sources import (
    SourceOutcome,
)
from app.components.architecture_validation.decision_knowledge.sources.base import (
    decision_record,
)
from app.components.architecture_validation.decision_knowledge.supersession import (
    CONSTRAINT_RELATIONSHIP,
    constraints_for,
    resolve_fact,
)
from app.components.architecture_validation.models import (
    ConstraintKind,
    EvidenceStrength,
    ExtractionMethod,
    FactEndpoint,
    ObservedFact,
    RelationshipKind,
    SourceTier,
)
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.recovery_gateway import SnapshotFileReader

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"
CORPUS = FIXTURES / "decisions"
SNAPSHOTS = Path(__file__).resolve().parents[3] / "data" / "snapshots"

REPOSITORY = "online-boutique"
RELEASES = ("v0.9.0", "v0.10.0")
AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def fact(
    subject: str = "frontend",
    object_: str = "cartservice",
    release: str = "v0.10.0",
    relationship: RelationshipKind = RelationshipKind.COMMUNICATES_WITH,
) -> ObservedFact:
    """One observed relationship, as normalisation would hand it over."""

    return ObservedFact(
        fact_id="f" * 16,
        release_id=release,
        release_sort_key=release_sort_key(release),
        subject=FactEndpoint(id="e1", name=subject, canonical=subject),
        relationship=relationship,
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
    tier: SourceTier = SourceTier.EXECUTABLE_CONFIG,
    source: str = "config_scan",
    valid_from: str = "v0.9.0",
    valid_to: str | None = None,
    supersedes: str | None = None,
):
    return decision_record(
        SourceRequest(REPOSITORY, valid_from, AT),
        decision_id=decision_id,
        subject=subject,
        constraint=constraint,
        object_=object_,
        source=source,
        source_repository=REPOSITORY,
        source_ref=f"{decision_id}.yaml",
        source_tier=tier,
        source_strength=EvidenceStrength.AUTHORITATIVE,
        extraction_method=ExtractionMethod.RECONSTRUCTED,
        valid_from=valid_from,
        valid_to=valid_to,
        supersedes=supersedes,
    )


def index_of(*records) -> DecisionIndex:
    """An index built straight from records, with no log in the way."""

    from app.components.architecture_validation.decision_knowledge._events import (
        recorded_event,
    )

    return DecisionIndex.from_events(
        [recorded_event(item, number) for number, item in enumerate(records, 1)]
    )


def recorded_service() -> DecisionKnowledgeService:
    """The service reading the committed decision corpus."""

    return DecisionKnowledgeService(None, JsonlDecisionStore(CORPUS))


def recorded_facts(release: str):
    architecture = SnapshotFileReader(SNAPSHOTS).read(REPOSITORY, release)
    return ObservationNormalizationService().normalise(architecture).facts


class TestTheHeadlineClaim:
    """A superseded decision never governs, and the chain is still visible."""

    def test_the_superseded_record_never_governs(self):
        index = index_of(
            record("ADR-005", valid_from="v0.9.0", valid_to="v0.10.0"),
            record("ADR-021", valid_from="v0.10.0", supersedes="ADR-005"),
        )

        resolution = resolve_fact(index, fact(release="v0.10.0"))

        assert resolution.governing.decision_id == "ADR-021"
        assert resolution.superseded_ancestor == "ADR-005"

    def test_the_same_query_at_the_earlier_release_resolves_to_the_earlier_decision(
        self,
    ):
        """The test that tells a resolver reading intervals apart from one
        returning whatever is newest. Both answer v0.10.0 correctly; only one
        answers this."""

        index = index_of(
            record("ADR-005", valid_from="v0.9.0", valid_to="v0.10.0"),
            record("ADR-021", valid_from="v0.10.0", supersedes="ADR-005"),
        )

        resolution = resolve_fact(index, fact(release="v0.9.0"))

        assert resolution.governing.decision_id == "ADR-005"

    def test_a_release_on_the_boundary_falls_in_one_window_only(self):
        """`[valid_from, valid_to)`. With a closed upper bound v0.10.0 sits in
        both windows and comes back ambiguous for no reason anyone could
        explain - and v0.10.0 is the release the demonstration runs on."""

        index = index_of(
            record("ADR-005", valid_from="v0.9.0", valid_to="v0.10.0"),
            record("ADR-021", valid_from="v0.10.0"),
        )

        resolution = resolve_fact(index, fact(release="v0.10.0"))

        assert resolution.ambiguous is False
        assert resolution.governing.decision_id == "ADR-021"

    def test_the_ancestor_is_found_even_when_the_record_does_not_name_it(self):
        """A reconstructed rule does not know what it replaced - the log does,
        because one interval ends exactly where the other begins."""

        index = index_of(
            record("rule-old", valid_from="v0.9.0", valid_to="v0.10.0"),
            record("rule-new", valid_from="v0.10.0"),
        )

        assert (
            resolve_fact(index, fact(release="v0.10.0")).superseded_ancestor
            == "rule-old"
        )


class TestWhenNothingCanBePicked:
    """Refusing to choose is a feature, and it has to be cheap."""

    def test_two_decisions_of_equal_standing_give_ambiguous_and_both_names(self):
        index = index_of(
            record("ADR-014", constraint=ConstraintKind.MAY_CALL, tier=SourceTier.DECISION_RECORD),
            record("ADR-017", constraint=ConstraintKind.MUST_NOT_CALL, tier=SourceTier.DECISION_RECORD),
        )

        resolution = resolve_fact(index, fact())

        assert resolution.ambiguous is True
        assert resolution.governing is None
        assert resolution.candidates == ("ADR-014", "ADR-017")

    def test_nothing_recorded_about_a_relationship_is_its_own_answer(self):
        resolution = resolve_fact(DecisionIndex.from_events([]), fact())

        assert resolution.uncovered is True
        assert resolution.governing is None
        assert resolution.ambiguous is False

    def test_the_three_outcomes_are_mutually_exclusive(self):
        """The one state the shape permits and nobody wants."""

        service = recorded_service()
        for release in RELEASES:
            for observed in recorded_facts(release):
                resolution = service.resolve(observed, REPOSITORY)
                answered = [
                    resolution.governing is not None,
                    resolution.uncovered,
                    resolution.ambiguous,
                ]
                assert answered.count(True) == 1


class TestWhichSourceWins:
    """A written decision outranks a reconstructed rule, and says so."""

    def test_a_declared_record_outranks_a_reconstructed_one(self):
        index = index_of(
            record(
                "ADR-014",
                constraint=ConstraintKind.MUST_NOT_CALL,
                tier=SourceTier.DECISION_RECORD,
                source="external_adr",
            ),
            record("rule-frontend-cartservice", constraint=ConstraintKind.MAY_CALL),
        )

        resolution = resolve_fact(index, fact())

        assert resolution.governing.decision_id == "ADR-014"
        assert resolution.governing.source == "external_adr"
        assert resolution.conflicting_sources == ("config_scan",)

    def test_a_source_that_agrees_is_not_reported_as_conflicting(self):
        """Two sources describing one relationship the same way is
        corroboration. Calling it a conflict would make the count useless."""

        index = index_of(
            record("ADR-030", tier=SourceTier.DECISION_RECORD, source="external_adr"),
            record("rule-frontend-cartservice"),
        )

        assert resolve_fact(index, fact()).conflicting_sources == ()


class TestTheDefaultRefusal:
    """One record about every pair, consulted only when nothing names one."""

    def test_a_permission_that_names_the_pair_beats_the_general_refusal(self):
        index = index_of(
            record("np-deny-all", subject="*", object_="*", constraint=ConstraintKind.MUST_NOT_CALL),
            record("rule-frontend-cartservice"),
        )

        resolution = resolve_fact(index, fact())

        assert resolution.governing.decision_id == "rule-frontend-cartservice"

    def test_a_pair_no_rule_names_falls_to_the_general_refusal(self):
        """What makes the absence of a permission mean something under a
        default-deny policy set, without writing 116 records that say it."""

        index = index_of(
            record("np-deny-all", subject="*", object_="*", constraint=ConstraintKind.MUST_NOT_CALL),
            record("rule-frontend-cartservice"),
        )

        resolution = resolve_fact(index, fact(subject="adservice", object_="paymentservice"))

        assert resolution.governing.decision_id == "np-deny-all"
        assert resolution.governing.constraint is ConstraintKind.MUST_NOT_CALL


class TestWhatAConstraintSpeaksAbout:
    """The mapping from the four constraints onto the two relationship kinds."""

    def test_a_dependency_is_governed_by_the_rule_that_names_its_pair(self):
        """Reversed on 2026-10-21, and the corpus is why.

        The old reading was that `depends-on` means the transport is unknown
        and a rule about who may *call* whom does not speak to it. But the
        rules here are network policies, and a network policy is not a
        statement about a transport - it is a statement about which workload
        may reach which. `cartservice -> redis-cart` is a datastore
        dependency, a policy names exactly that pair and admits exactly that
        caller, and the fact was published as *nothing in the recorded intent
        speaks to this* while the rule speaking to it sat in the log.
        """

        index = index_of(record("rule-frontend-cartservice"))

        resolution = resolve_fact(
            index, fact(relationship=RelationshipKind.DEPENDS_ON)
        )

        assert resolution.uncovered is False
        assert resolution.governing.decision_id == "rule-frontend-cartservice"

    def test_a_declared_operation_still_governs_neither_kind(self):
        """The row that genuinely does not apply is excluded by its own
        entry, not by the relationship it was asked about - which is what
        makes widening the others safe."""

        assert constraints_for(RelationshipKind.DEPENDS_ON) and (
            ConstraintKind.DECLARED_RPC
            not in constraints_for(RelationshipKind.DEPENDS_ON)
        )

    def test_a_declared_operation_governs_no_observed_relationship_yet(self):
        """It is held in the log and counted. An observed fact carries no
        operation, so there is nothing for it to be matched against."""

        assert CONSTRAINT_RELATIONSHIP[ConstraintKind.DECLARED_RPC] == ()
        assert ConstraintKind.DECLARED_RPC not in constraints_for(
            RelationshipKind.COMMUNICATES_WITH
        )

    def test_every_constraint_has_an_answer_in_the_mapping(self):
        """A fifth constraint added without a decision about what it governs
        would silently govern nothing."""

        assert set(CONSTRAINT_RELATIONSHIP) == set(ConstraintKind)


class TestTheArchitectConfirmation:
    """Mode B's loop: a reconstructed candidate becomes a decision."""

    def test_a_confirmation_raises_the_strength_and_keeps_the_history(self, tmp_path):
        service = DecisionKnowledgeService(None, JsonlDecisionStore(tmp_path))
        request = SourceRequest(REPOSITORY, "v0.10.0", AT)
        service.append_scan(
            request,
            (SourceOutcome("config_scan", True, (record("cand-003", valid_from="v0.10.0"),)),),
        )

        applied = service.confirm(
            REPOSITORY, "cand-003", ratified_by="architect", ratified_at=AT
        )
        governing = service.resolve(fact(), REPOSITORY).governing

        assert applied == 1
        assert governing.source_strength is EvidenceStrength.AUTHORITATIVE
        assert governing.extraction_method is ExtractionMethod.RECONSTRUCTED
        assert governing.ratified_by == "architect"

    def test_a_confirmation_naming_nothing_is_visible_rather_than_silent(
        self, tmp_path
    ):
        service = DecisionKnowledgeService(None, JsonlDecisionStore(tmp_path))

        assert (
            service.confirm(
                REPOSITORY, "never-recorded", ratified_by="architect", ratified_at=AT
            )
            == 0
        )

    def test_a_confirmation_changes_no_interval(self, tmp_path):
        service = DecisionKnowledgeService(None, JsonlDecisionStore(tmp_path))
        request = SourceRequest(REPOSITORY, "v0.10.0", AT)
        service.append_scan(
            request,
            (SourceOutcome("config_scan", True, (record("cand-003", valid_from="v0.10.0"),)),),
        )

        service.confirm(REPOSITORY, "cand-003", ratified_by="architect", ratified_at=AT)
        versions = service.history(REPOSITORY).versions_of(
            "frontend", "may_call", "cartservice"
        )

        assert len(versions) == 1
        assert versions[0].valid_from == "v0.10.0" and versions[0].valid_to is None


class TestAgainstTheRecordedReleases:
    """The whole of it, over the real corpus and the real facts."""

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_observed_dependency_is_governed(self, release):
        """The honest result on this system: 15 dependencies, 15 permissions,
        nothing uncovered and nothing ambiguous. A clean answer is a finding
        too - and one that can be shown to have been checked."""

        service = recorded_service()

        resolutions = [
            service.resolve(observed, REPOSITORY) for observed in recorded_facts(release)
        ]

        assert len(resolutions) == 15
        assert all(r.governing is not None for r in resolutions)
        assert all(
            r.governing.constraint is ConstraintKind.MAY_CALL for r in resolutions
        )

    def test_the_identity_rule_in_force_differs_between_the_two_releases(self):
        """The supersession, resolved. It lives in the log rather than on an
        edge, because it is a rule about how every workload declares identity
        rather than about one dependency."""

        index = recorded_service().history(REPOSITORY)
        shared = index.versions_of(
            "*", "must_call_via", "kustomize/components/service-accounts"
        )
        inline = index.versions_of(
            "*", "must_call_via", "inline ServiceAccount beside the workload"
        )

        assert shared[0].covers("v0.9.0") and not shared[0].covers("v0.10.0")
        assert inline[0].covers("v0.10.0") and not inline[0].covers("v0.9.0")

    def test_resolving_the_same_fact_twice_gives_the_same_answer(self):
        """No model, no clock, no state carried between calls."""

        service = recorded_service()
        observed = recorded_facts("v0.10.0")[0]

        assert service.resolve(observed, REPOSITORY) == service.resolve(
            observed, REPOSITORY
        )
