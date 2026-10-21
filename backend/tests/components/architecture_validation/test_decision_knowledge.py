"""Decision knowledge tests: the log, the index, and supersession by absence.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Covers the mechanism the component's headline claim rests on - that a rule
    the log holds and a release no longer states has its interval closed at
    that release, and that the closed one never governs again.

    Everything here runs against a list. The log's file is infrastructure and
    has its own tests; what is checked here is the comparison, which is the
    part that has to be right and the part a filesystem would only make
    slower to exercise.

    Two of these matter more than the rest. `test_a_rule_that_vanishes_has_
    its_interval_closed` is the claim itself, derived from the two committed
    releases rather than from a fixture anybody typed. And the three guards
    in `TestWhatAbsenceIsNotAllowedToMean` are what stop that mechanism
    inventing history: a scan that found nothing, a source speaking for
    another source's records, and a re-run appending a second copy of
    everything.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
    DecisionStoreMissing,
    NoDecisionsAvailable,
    SourceRequest,
)
from app.components.architecture_validation.decision_knowledge._events import (
    DECISION_RECORDED,
    DECISION_SUPERSEDED,
    RELEASE_SCANNED,
    record_hash,
    recorded_event,
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
from app.components.architecture_validation._release import release_sort_key
from app.components.architecture_validation.models import (
    ConstraintKind,
    EvidenceStrength,
    ExtractionMethod,
    FactEndpoint,
    ObservedFact,
    RelationshipKind,
    SourceTier,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"
SUBJECT = FIXTURES / "subject"
CORPUS = FIXTURES / "decisions" / "online-boutique.jsonl"
SNAPSHOTS = Path(__file__).resolve().parents[3] / "data" / "snapshots"

REPOSITORY = "online-boutique"
RELEASES = ("v0.9.0", "v0.10.0")
SCANNED_AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


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


class ListStore:
    """The decision log as a list, because the mechanism needs no disk."""

    def __init__(self, events: list[dict] | None = None) -> None:
        self.events = list(events or ())

    def append(self, repository_id, events):
        self.events.extend(events)

    def replay(self, repository_id):
        return list(self.events)


def manifest_paths(release: str) -> tuple[str, ...]:
    document = json.loads(
        (SNAPSHOTS / f"snapshot_{release}.json").read_text(encoding="utf-8")
    )
    return tuple(document["manifest_paths"])


def request_for(release: str, **overrides) -> SourceRequest:
    return SourceRequest(
        code_repository_id=REPOSITORY,
        release_id=release,
        extracted_at=SCANNED_AT,
        manifest_paths=manifest_paths(release),
        **overrides,
    )


def scanned(release: str, service: DecisionKnowledgeService):
    """Scan one release through the configured sources and append it."""

    request = request_for(release)
    return service.append_scan(request, service.collect(request, "combined"))


def service_with(store: ListStore | None = None) -> DecisionKnowledgeService:
    return DecisionKnowledgeService(WorkspaceReader(), store or ListStore())


def rule(
    decision_id: str,
    *,
    subject: str = "a",
    object_: str = "b",
    source: str = "config_scan",
    constraint: ConstraintKind = ConstraintKind.MAY_CALL,
    release: str = "v1.0.0",
    source_ref: str | None = None,
) -> object:
    """One record, built the way a source builds it."""

    return decision_record(
        SourceRequest(REPOSITORY, release, SCANNED_AT),
        decision_id=decision_id,
        subject=subject,
        constraint=constraint,
        object_=object_,
        source=source,
        source_repository=REPOSITORY,
        source_ref=source_ref or f"{decision_id}.yaml",
        source_tier=SourceTier.EXECUTABLE_CONFIG,
        source_strength=EvidenceStrength.AUTHORITATIVE,
        extraction_method=ExtractionMethod.RECONSTRUCTED,
    )


def from_source(name: str, *records) -> SourceOutcome:
    return SourceOutcome(source=name, ran=True, records=tuple(records))


class TestSupersessionByAbsence:
    """The claim the component is remembered for, and how it is established."""

    def test_a_rule_that_vanishes_has_its_interval_closed(self):
        """Nothing in the later release says the overlay used to be there.
        The log is what knows, which is why the scan alone could never
        produce a closing boundary."""

        service = service_with()
        scanned("v0.9.0", service)
        scanned("v0.10.0", service)

        overlay = service.history(REPOSITORY).versions_of(
            "*", "must_call_via", "kustomize/components/service-accounts"
        )

        assert len(overlay) == 1
        assert overlay[0].valid_from == "v0.9.0"
        assert overlay[0].valid_to == "v0.10.0"

    def test_the_rule_that_replaced_it_says_so(self):
        """Same subject, same kind of constraint, different object - the team
        still constrains this and constrains it differently."""

        service = service_with()
        scanned("v0.9.0", service)
        scanned("v0.10.0", service)

        inline = service.history(REPOSITORY).versions_of(
            "*", "must_call_via", "inline ServiceAccount beside the workload"
        )

        assert inline[0].record.supersedes == "sa-shared-component"
        assert inline[0].valid_from == "v0.10.0"
        assert inline[0].valid_to is None

    def test_one_release_changes_one_thing_and_leaves_the_rest_alone(self):
        """The policy set is identical across the two releases, so the only
        movement in the whole corpus is the one that really happened."""

        service = service_with()
        first = scanned("v0.9.0", service)
        second = scanned("v0.10.0", service)

        assert first.recorded == 26 and first.closed == 0
        assert second.recorded == 1 and second.closed == 1
        assert second.unchanged == 25

    def test_a_replacement_is_only_named_when_there_is_exactly_one(self):
        """Two candidates make the link a guess, and a guess written into a
        supersession chain is worse than an unexplained gap."""

        store = ListStore()
        service = service_with(store)
        request = SourceRequest(REPOSITORY, "v1.0.0", SCANNED_AT)
        service.append_scan(request, (from_source("config_scan", rule("old")),))

        later = SourceRequest(REPOSITORY, "v2.0.0", SCANNED_AT)
        service.append_scan(
            later,
            (
                from_source(
                    "config_scan",
                    rule("new-one", object_="c", release="v2.0.0"),
                    rule("new-two", object_="d", release="v2.0.0"),
                ),
            ),
        )

        closing = [e for e in store.events if e["event"] == DECISION_SUPERSEDED]
        assert closing[0]["superseded_by"] is None


class TestWhatAbsenceIsNotAllowedToMean:
    """Absence is a weak signal, so it is fenced on three sides."""

    def test_a_scan_that_found_nothing_closes_nothing(self):
        """A release that reconstructs no rules is a broken scan, not an
        architecture that withdrew every rule it had."""

        store = ListStore()
        service = service_with(store)
        service.append_scan(
            SourceRequest(REPOSITORY, "v1.0.0", SCANNED_AT),
            (from_source("config_scan", rule("kept")),),
        )

        service.append_scan(
            SourceRequest(REPOSITORY, "v2.0.0", SCANNED_AT),
            (SourceOutcome(source="config_scan", ran=True, records=()),),
        )

        assert service.history(REPOSITORY).open_versions()[0].valid_to is None

    def test_one_source_never_closes_another_source_records(self):
        """A decision somebody wrote down is not withdrawn because a
        configuration scan did not reconstruct it."""

        store = ListStore()
        service = service_with(store)
        service.append_scan(
            SourceRequest(REPOSITORY, "v1.0.0", SCANNED_AT),
            (
                from_source("config_scan", rule("reconstructed")),
                from_source("external_adr", rule("written", source="external_adr")),
            ),
        )

        service.append_scan(
            SourceRequest(REPOSITORY, "v2.0.0", SCANNED_AT),
            (from_source("config_scan", rule("reconstructed")),),
        )

        still_open = {v.record.decision_id for v in service.history(REPOSITORY).open_versions()}
        assert still_open == {"reconstructed", "written"}

    def test_the_same_release_scanned_twice_appends_nothing(self):
        """Recovering from a failed run is re-running it, and the published
        graph has to come out byte-identical."""

        store = ListStore()
        service = service_with(store)
        scanned("v0.10.0", service)
        after_first = list(store.events)

        scanned("v0.10.0", service)

        assert store.events == after_first


class TestTheLogAndTheIndex:
    """Replay is the only path to the state, so it is the only one to test."""

    def test_replaying_twice_gives_the_same_state(self):
        service = service_with()
        scanned("v0.9.0", service)

        first = service.history(REPOSITORY)
        again = service.history(REPOSITORY)

        assert first.versions == again.versions
        assert first.releases_seen == again.releases_seen

    def test_a_release_that_changed_nothing_is_still_recorded_as_seen(self):
        """Otherwise "nothing was superseded" and "we have never looked at
        that release" are the same answer, and they are not."""

        store = ListStore()
        service = service_with(store)
        request = SourceRequest(REPOSITORY, "v1.0.0", SCANNED_AT)
        service.append_scan(request, (from_source("config_scan", rule("same")),))

        unchanged = SourceRequest(REPOSITORY, "v1.1.0", SCANNED_AT)
        service.append_scan(unchanged, (from_source("config_scan", rule("same")),))

        assert service.history(REPOSITORY).releases_seen == ("v1.0.0", "v1.1.0")
        assert [e["event"] for e in store.events].count(RELEASE_SCANNED) == 2

    def test_scanning_an_older_release_second_does_not_open_a_rival_interval(self):
        """The order a stack is validated in is the architect's, not the log's.

        A rule first seen at `v1.1.0` opens an interval there. Scanning
        `v1.0.0` afterwards finds the same rule, stated by the same source -
        it is the same rule known to be older, not a second one. Recording it
        again leaves two open intervals over one pair, and every fact about
        that pair resolves to `ambiguous` from then on, at every release.

        This was the whole stack reading `ambiguous` with confidence 0.0 after
        a release was validated out of order.
        """

        store = ListStore()
        service = service_with(store)

        later = SourceRequest(REPOSITORY, "v1.1.0", SCANNED_AT)
        service.append_scan(
            later, (from_source("config_scan", rule("same", release="v1.1.0")),)
        )

        earlier = SourceRequest(REPOSITORY, "v1.0.0", SCANNED_AT)
        service.append_scan(
            earlier, (from_source("config_scan", rule("same", release="v1.0.0")),)
        )

        versions = service.history(REPOSITORY).versions_of("a", "may_call", "b")

        assert len(versions) == 1, (
            "one rule, one interval - a second open interval over the same "
            "pair is what the resolver reports as ambiguous"
        )
        assert versions[0].valid_from == "v1.0.0", (
            "the interval opens where the rule is now known to start"
        )
        assert versions[0].valid_to is None

    def test_a_rule_found_at_an_older_release_governs_that_release(self):
        """Backdating has to move the interval, not just suppress the rival.

        Declining to record the rule again and leaving the interval where it
        was would make the earlier release `uncovered` instead of `ambiguous`
        - a different wrong answer, and one that reads as a finding about the
        repository rather than a fault in the log.
        """

        service = service_with()

        service.append_scan(
            SourceRequest(REPOSITORY, "v1.1.0", SCANNED_AT),
            (from_source("config_scan", rule("same", release="v1.1.0")),),
        )
        service.append_scan(
            SourceRequest(REPOSITORY, "v1.0.0", SCANNED_AT),
            (from_source("config_scan", rule("same", release="v1.0.0")),),
        )

        version = service.history(REPOSITORY).versions_of("a", "may_call", "b")[0]

        assert version.covers("v1.0.0"), "the release it was just found at"
        assert version.covers("v1.1.0"), "and the one it was first seen at"

    def test_a_log_that_already_holds_duplicates_still_replays_to_one_rule(self):
        """Replay has to be idempotent, not only append-only.

        A log written *before* the scan knew how to backdate holds the same
        rule recorded once per release. Reading those as rivals makes every
        fact about the pair `ambiguous` for ever - a log that can never be read
        correctly again, and that no amount of fixing the **writer** repairs.

        So the events are built here the way that writer built them, rather
        than through `append_scan`: going through the scan would exercise the
        fix that stops them being written and never reach the one that reads
        them.
        """

        duplicates = [
            recorded_event(rule("same", release=release), sequence)
            for sequence, release in enumerate(("v1.2.0", "v1.0.0", "v1.1.0"), start=1)
        ]

        assert len({event["record_hash"] for event in duplicates}) == 1, (
            "one rule from one file - the same hash recorded three times, "
            "which is what the broken log on disk holds"
        )

        versions = DecisionIndex.from_events(duplicates).versions_of(
            "a", "may_call", "b"
        )
        still_open = [v for v in versions if v.valid_to is None]

        assert len(still_open) == 1, (
            "two open intervals over one pair is what the resolver reports "
            "as ambiguous"
        )
        assert still_open[0].valid_from == "v1.0.0", (
            "and it holds from the earliest release that stated it"
        )

    def test_two_files_stating_one_rule_stay_two_records(self):
        """The distinction `record_hash` exists to make, kept.

        Collapsing duplicates must not collapse a rule genuinely stated in two
        places: a release that drops one of them has changed something, and a
        reader that merged them could not report it.
        """

        store = ListStore()
        service = service_with(store)
        service.append_scan(
            SourceRequest(REPOSITORY, "v1.0.0", SCANNED_AT),
            (
                from_source(
                    "config_scan",
                    rule("same", release="v1.0.0"),
                    rule("same", release="v1.0.0", source_ref="elsewhere.yaml"),
                ),
            ),
        )

        versions = service.history(REPOSITORY).versions_of("a", "may_call", "b")

        assert len(versions) == 2
        assert {v.record.source_ref for v in versions} == {
            "same.yaml",
            "elsewhere.yaml",
        }

    def test_a_permission_is_not_indexed_in_both_directions(self):
        """None of the four constraints is symmetric. Indexing both orderings
        would turn every permission into a mutual one - the same error the
        scan's direction tests guard against, made structural."""

        service = service_with()
        scanned("v0.10.0", service)
        index = service.history(REPOSITORY)

        assert index.versions_of("frontend", "may_call", "cartservice")
        assert not index.versions_of("cartservice", "may_call", "frontend")

    def test_a_lookup_reduces_both_sides_to_one_identity(self):
        """The architecture calls it `cartservice` and a policy may write
        `cart-service`. A lookup that does not reduce both finds nothing and
        reports the fact as uncovered, which is a wrong answer wearing the
        clothes of a finding."""

        service = service_with()
        scanned("v0.10.0", service)

        assert service.history(REPOSITORY).versions_of(
            "front-end", "may_call", "Cart_Service"
        )

    def test_an_event_log_with_no_events_is_an_empty_history(self):
        index = DecisionIndex.from_events([])

        assert index.versions == {}
        assert index.releases_seen == ()
        assert index.open_versions() == ()

    def test_a_service_with_nowhere_to_keep_history_says_so(self):
        with pytest.raises(DecisionStoreMissing):
            DecisionKnowledgeService(WorkspaceReader()).history(REPOSITORY)


class TestTheRecordedCorpus:
    """The committed fixture, and the guard that it still matches the scan."""

    def test_the_corpus_reproduces_from_the_committed_working_trees(self):
        """A fixture that has drifted from what the code produces is worse
        than no fixture: every test over it passes and none of them mean
        anything."""

        service = service_with()
        for release in RELEASES:
            scanned(release, service)

        recorded = [
            json.loads(line)
            for line in CORPUS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        assert service._store.events == recorded

    def test_the_corpus_holds_the_supersession_and_one_scan_marker_per_release(self):
        events = [
            json.loads(line)
            for line in CORPUS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kinds = [event["event"] for event in events]

        assert kinds.count(DECISION_RECORDED) == 27
        assert kinds.count(DECISION_SUPERSEDED) == 1
        assert kinds.count(RELEASE_SCANNED) == len(RELEASES)

    def test_every_event_names_the_source_it_came_from(self):
        """KNW-D5's requirement, and what lets a verdict be traced to a line
        in a file rather than to "the configuration"."""

        for line in CORPUS.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["event"] == RELEASE_SCANNED:
                continue
            assert event["source"] in {"repo_adr", "external_adr", "config_scan"}
            assert event["source_repository"] == REPOSITORY
            assert event["record_hash"]

    def test_the_record_hash_is_stable_across_runs(self):
        """It is the identity a re-run is recognised by, so it cannot depend
        on anything that moves."""

        assert record_hash(rule("x")) == record_hash(rule("x"))

class MultiRepositoryReader:
    """Two repositories at once: the code, and the one holding decisions."""

    def __init__(self, files: dict[tuple[str, str], str]) -> None:
        self.files = files

    def read_text(self, repository_id, release_id, path):
        return self.files[(repository_id, path)]

    def list_paths(self, repository_id, release_id, pattern):
        from fnmatch import fnmatch

        return sorted(
            path
            for (held_in, path) in self.files
            if held_in == repository_id and fnmatch(path, pattern)
        )


ADR_DOCUMENT = """---
id: ADR-014
subject: frontend
constraint: must_not_call
object: cartservice
valid_from: v0.9.0
rationale: The cart is reached through checkout only.
---
"""


def policy_permitting_what_the_adr_forbids() -> str:
    """One network policy that allows exactly what ADR-014 prohibits."""

    return yaml.safe_dump(
        {
            "kind": "NetworkPolicy",
            "metadata": {"name": "cartservice"},
            "spec": {
                "podSelector": {"matchLabels": {"app": "cartservice"}},
                "ingress": [
                    {"from": [{"podSelector": {"matchLabels": {"app": "frontend"}}}]}
                ],
            },
        }
    )


def contested_fact() -> ObservedFact:
    """The observed dependency both sources describe differently."""

    return ObservedFact(
        fact_id="f" * 16,
        release_id="v0.10.0",
        release_sort_key=release_sort_key("v0.10.0"),
        subject=FactEndpoint(id="e1", name="frontend", canonical="frontend"),
        relationship=RelationshipKind.COMMUNICATES_WITH,
        object=FactEndpoint(id="e2", name="cartservice", canonical="cartservice"),
        style_resolved="microservices",
        style_source="c1",
        quality="confirmed",
    )


def both_sources_request() -> SourceRequest:
    return SourceRequest(
        code_repository_id=REPOSITORY,
        release_id="v0.10.0",
        extracted_at=SCANNED_AT,
        manifest_paths=("policy.yaml",),
    )


def both_sources_service(store: ListStore) -> DecisionKnowledgeService:
    # Both documents sit in the code repository, because that is what
    # `combined` now reads: one repository's written decisions and one
    # repository's configuration, about one system.
    reader = MultiRepositoryReader(
        {
            (REPOSITORY, "docs/adr/0014-cart.md"): ADR_DOCUMENT,
            (REPOSITORY, "policy.yaml"): policy_permitting_what_the_adr_forbids(),
        }
    )
    return DecisionKnowledgeService(reader, store)


class TestTheGate:
    """An empty store refuses the run, and the refusal says what to pick."""

    def test_a_mode_with_nothing_in_it_refuses_the_run(self):
        """The most misleading output this component could produce is a graph
        in which nothing is contradicted because nothing was ever checked."""

        with pytest.raises(NoDecisionsAvailable) as refused:
            service_with().establish(request_for("v0.10.0"), "repo_adr")

        assert refused.value.yields["repo_adr"] == 0
        assert refused.value.yields["combined"] == 26

    def test_the_refusal_names_the_mode_that_would_work(self):
        """A block that does not say what to do instead is a block somebody
        works around."""

        with pytest.raises(NoDecisionsAvailable) as refused:
            service_with().establish(request_for("v0.10.0"), "repo_adr")

        assert "choose 'combined'" in str(refused.value)

    def test_a_refused_run_scans_nothing_behind_the_users_back(self):
        """A run labelled "validated against decision records" must never
        have been validated against rules we reconstructed ourselves - and a
        refusal has to leave the history exactly as it was."""

        store = ListStore()

        with pytest.raises(NoDecisionsAvailable):
            service_with(store).establish(request_for("v0.10.0"), "repo_adr")

        assert store.events == []

    def test_a_chosen_mode_does_not_fall_back_to_a_fuller_one(self):
        """Falling back would give every verdict in the run a strength it did
        not earn, with nothing in the output saying so."""

        service = service_with()

        with pytest.raises(NoDecisionsAvailable):
            service.establish(request_for("v0.10.0"), "repo_adr")

        assert service.history(REPOSITORY).decision_count() == 0

    def test_a_mode_with_something_in_it_opens_the_run_and_records_it(self):
        outcome = service_with().establish(request_for("v0.9.0"), "combined")

        assert outcome.mode == "combined"
        assert outcome.recorded == 26
        assert outcome.in_force == 26
        assert outcome.by_source == {"repo_adr": 0, "config_scan": 26}
        assert outcome.releases_in_log == ("v0.9.0",)

    def test_the_releases_own_rules_are_in_force_when_its_facts_are_judged(self):
        """The append happens before any fact is resolved. Otherwise the first
        run of a release validates it against the release before it."""

        outcome = service_with().establish(request_for("v0.10.0"), "combined")

        assert outcome.in_force == outcome.records


class TestARuleAboutEveryCaller:
    """A policy that admits anybody sits between a named pair and the deny.

    It is the shape the resolver had no lookup for. A rule is found by
    subject and object, or by the two wildcards that are the default refusal,
    and `(*, one element)` matched neither - so a dependency into an element
    whose policy admits every source fell through to the refusal and was
    published as a violation of the policy permitting it.
    """

    def fact_into(self, element: str) -> ObservedFact:
        return ObservedFact(
            fact_id="f" * 16,
            release_id="v0.10.0",
            release_sort_key=release_sort_key("v0.10.0"),
            subject=FactEndpoint(id="e1", name="adservice", canonical="adservice"),
            relationship=RelationshipKind.COMMUNICATES_WITH,
            object=FactEndpoint(id="e2", name=element, canonical=element),
            style_resolved="microservices",
            style_source="c1",
            quality="confirmed",
        )

    def established(self) -> DecisionKnowledgeService:
        service = service_with()
        for release in RELEASES:
            scanned(release, service)
        return service

    def test_a_caller_nobody_named_is_permitted_by_the_open_policy(self):
        """`loadgenerator` admits every source, and `adservice` is not named
        anywhere near it. The permission still governs."""

        resolution = self.established().resolve(
            self.fact_into("loadgenerator"), REPOSITORY
        )

        assert not resolution.uncovered
        assert resolution.governing.decision_id == "rule-any-loadgenerator"
        assert resolution.governing.constraint is ConstraintKind.MAY_CALL

    def test_an_element_with_no_open_policy_still_falls_to_the_refusal(self):
        """The half that must not move. An open policy on one element is not
        an open policy on the next, and a lookup that leaked across them
        would confirm every dependency in the system."""

        resolution = self.established().resolve(
            self.fact_into("paymentservice"), REPOSITORY
        )

        assert resolution.governing.decision_id == "np-deny-all"
        assert resolution.governing.constraint is ConstraintKind.MUST_NOT_CALL

    def test_a_named_pair_still_beats_the_open_policy(self):
        """Specificity order, asserted rather than assumed: the pair, then
        the element, then the refusal."""

        named = ObservedFact(
            fact_id="f" * 16,
            release_id="v0.10.0",
            release_sort_key=release_sort_key("v0.10.0"),
            subject=FactEndpoint(id="e1", name="frontend", canonical="frontend"),
            relationship=RelationshipKind.COMMUNICATES_WITH,
            object=FactEndpoint(
                id="e2", name="cartservice", canonical="cartservice"
            ),
            style_resolved="microservices",
            style_source="c1",
            quality="confirmed",
        )

        resolution = self.established().resolve(named, REPOSITORY)

        assert resolution.governing.decision_id == "rule-frontend-cartservice"


class TestWhenTwoSourcesDisagree:
    """`combined`'s finding, and it needs no mechanism of its own.

    One repository that both writes its decisions down and runs a
    configuration, where the two do not agree. That is a statement about the
    system under study rather than about this component, which is why neither
    source is dropped.
    """

    def test_a_declared_record_and_a_reconstructed_rule_can_disagree(self):
        """Two events on one key, from two sources, saying different things.
        The written decision governs and the other is reported rather than
        dropped: a decision and a running configuration that do not match is
        a finding about the system under study."""

        service = both_sources_service(ListStore())
        service.establish(both_sources_request(), "combined")

        resolution = service.resolve(contested_fact(), REPOSITORY)

        assert resolution.governing.decision_id == "ADR-014"
        assert resolution.governing.source == "repo_adr"
        assert resolution.conflicting_sources == ("config_scan",)

    def test_both_sources_are_in_one_log_with_their_own_provenance(self):
        """One log, so M3 can compare what is available instead of merging
        two stores that disagree about what exists."""

        store = ListStore()
        both_sources_service(store).establish(both_sources_request(), "combined")

        sources = {
            event["source"]: event["source_repository"]
            for event in store.events
            if event["event"] == DECISION_RECORDED
        }

        assert sources == {
            "repo_adr": REPOSITORY,
            "config_scan": REPOSITORY,
        }
