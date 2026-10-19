"""M7 - the review queue, and the loop that closes across three subcomponents.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    Two properties carry this file.

    The queue cannot hold up a run. A queue that refuses produces a warning
    naming the store and nothing else: the run completes, and the published
    document is byte-identical to one written with the queue working. The
    second half is the one that proves it - a stage record saying `completed`
    proves nothing about whether the queue is on the critical path, and two
    identical documents do.

    And a confirmation has to be visible. A ratified record is not capped by
    its tier, which is one condition in M6 that was missing until this unit
    was built: without it a confirmed candidate gains 0.10 of confidence,
    stays below the publish threshold, and stays in the queue forever.
"""

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.components.architecture_validation.architect_review import (
    ArchitectReviewService,
    QueueUnavailable,
    _queue,
)
from app.components.architecture_validation.architect_review.models import (
    EVENT_DECISION_CONFIRMED,
    EVENT_DECISION_REVOKED,
    ReviewDecision,
    ReviewStatus,
)
from app.components.architecture_validation.classification import ClassificationService, rules
from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
)
from app.components.architecture_validation.models import (
    ArbiterAgreement,
    ClassifiedFact,
    EvidenceStrength,
    ExtractionMethod,
    Resolution,
    ReviewItem,
    Route,
    ScoreTrace,
    SourceTier,
    Verdict,
    VerificationMode,
    VerificationOutcome,
)
from app.domain.validated_architecture import ValidationBucket
from app.infrastructure.decision_log import JsonlDecisionStore

from .corpus import FIXTURES, REPOSITORY, WorkspaceReader

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
RELEASE = "v0.10.0"


# ---- doubles -------------------------------------------------------------


class InMemoryQueue:
    """The queue a test can see into, with the real idempotency rule.

    `enqueue` is a no-op when the item is already there, which is what the
    unique constraint does in Postgres - and the consequence that matters is
    that an item somebody decided keeps its decision.
    """

    def __init__(self) -> None:
        self.items: dict[str, ReviewItem] = {}

    def enqueue(self, item: ReviewItem) -> str:
        self.items.setdefault(item.item_id, item)
        return item.item_id

    def get(self, item_id: str) -> ReviewItem | None:
        return self.items.get(item_id)

    def pending(self) -> list[ReviewItem]:
        return sorted(
            (i for i in self.items.values() if i.status == ReviewStatus.PENDING),
            key=lambda item: item.created_at,
        )

    def resolve(self, decision: ReviewDecision) -> None:
        status = (
            ReviewStatus.ACCEPTED if decision.accepted else ReviewStatus.REJECTED
        )
        self.items[decision.item_id] = replace(
            self.items[decision.item_id], status=str(status)
        )


class FailingQueue:
    def enqueue(self, item):
        raise RuntimeError("could not connect to the database")

    def get(self, item_id):
        raise RuntimeError("could not connect to the database")

    def pending(self):
        raise RuntimeError("could not connect to the database")

    def resolve(self, decision):
        raise RuntimeError("could not connect to the database")


class CountingRatifier:
    """Counts confirmations, and counts runs it was never asked to start."""

    def __init__(self, applies_to: int = 1) -> None:
        self.calls: list[tuple] = []
        self.runs_started = 0
        self._applies_to = applies_to

    def confirm(self, repository_id, decision_id, *, ratified_by, ratified_at) -> int:
        self.calls.append((repository_id, decision_id, ratified_by))
        return self._applies_to


# ---- builders ------------------------------------------------------------


def fact(fact_id: str = "f1", route: Route = Route.REVIEW) -> ClassifiedFact:
    return ClassifiedFact(
        fact_id=fact_id,
        bucket=ValidationBucket.NEEDS_REVIEW,
        confidence=0.60,
        score_trace=ScoreTrace(terms={"verdict_base": 0.5}, total=0.6),
        route=route,
        governing_decision="rule-candidate-1",
        source_tier=SourceTier.DOCUMENTATION,
        evidence_refs=("rule-candidate-1",),
        model_calls=2,
        source_element_id="component:a",
        target_element_id="component:b",
        relationship="communicates-with",
    )


def service(queue=None, ratifier=None) -> ArchitectReviewService:
    return ArchitectReviewService(queue, ratifier)


def accepted(item_id: str) -> ReviewDecision:
    return ReviewDecision(
        item_id=item_id, accepted=True, decided_by="architect", decided_at=NOW
    )


def rejected(item_id: str) -> ReviewDecision:
    return ReviewDecision(
        item_id=item_id, accepted=False, decided_by="architect", decided_at=NOW
    )


class TestWhatGetsQueued:
    """REV-1 and REV-2."""

    def test_every_fact_routed_to_review_is_queued_once(self):
        queue = InMemoryQueue()

        ids = service(queue).enqueue(
            (fact("f1"), fact("f2"), fact("f3")), REPOSITORY, RELEASE
        )

        assert len(ids) == 3
        assert len(queue.pending()) == 3

    def test_a_published_fact_is_never_queued(self):
        """The queue is the list of things the system would not claim on its
        own. Padding it with settled facts makes it a list of everything."""

        queue = InMemoryQueue()

        ids = service(queue).enqueue(
            (fact("f1", Route.PUBLISH), fact("f2", Route.PUBLISH)),
            REPOSITORY,
            RELEASE,
        )

        assert ids == ()
        assert queue.pending() == []

    def test_the_item_carries_the_tier_that_sent_it_here(self):
        """For the architect rather than the system: it is what lets a screen
        say *why* this needs a person instead of showing a number."""

        queue = InMemoryQueue()
        service(queue).enqueue((fact(),), REPOSITORY, RELEASE)

        item = queue.pending()[0]

        assert item.source_tier is SourceTier.DOCUMENTATION
        assert item.evidence_refs == ("rule-candidate-1",)
        assert item.candidate_decision_id == "rule-candidate-1"

    def test_the_item_holds_no_copy_of_the_evidence(self):
        """References only. A second copy here would be the one that goes
        stale, with no way to tell which was right."""

        item = _queue.items_for((fact(),), REPOSITORY, RELEASE, NOW)[0]

        assert set(vars(item)) == {
            "item_id",
            "fact_id",
            "bucket",
            "confidence",
            "source_tier",
            "evidence_refs",
            "candidate_decision_id",
            "created_at",
            "status",
        }

    def test_the_item_id_is_the_same_for_the_same_fact_in_the_same_release(self):
        """Content-addressed rather than generated, which is what makes a
        re-run a no-op instead of a second row the unique constraint then
        rejects."""

        first = _queue.item_id(REPOSITORY, RELEASE, "f1")
        again = _queue.item_id(REPOSITORY, RELEASE, "f1")
        other = _queue.item_id(REPOSITORY, "v0.9.0", "f1")

        assert first == again
        assert first != other


class TestARerun:
    """REV-D7. One item per fact per release, whatever a person did with it."""

    def test_a_re_run_does_not_queue_one_fact_twice(self):
        queue = InMemoryQueue()
        facts = (fact("f1"), fact("f2"))

        service(queue).enqueue(facts, REPOSITORY, RELEASE)
        service(queue).enqueue(facts, REPOSITORY, RELEASE)

        assert len(queue.items) == 2

    def test_a_re_run_does_not_reopen_an_item_somebody_decided(self):
        """A settled question must not depend on how many times the pipeline
        happened to run afterwards."""

        queue = InMemoryQueue()
        reviews = service(queue, CountingRatifier())
        item_id = reviews.enqueue((fact(),), REPOSITORY, RELEASE)[0]
        reviews.decide(accepted(item_id), REPOSITORY)

        reviews.enqueue((fact(),), REPOSITORY, RELEASE)

        assert queue.get(item_id).status == str(ReviewStatus.ACCEPTED)
        assert queue.pending() == []


class TestTheQueueCannotHoldUpARun:
    """REV-D6, which is the requirement this unit was asked for."""

    def test_a_queue_that_refuses_raises_one_type_the_caller_handles(self):
        with pytest.raises(QueueUnavailable, match="could not connect"):
            service(FailingQueue()).enqueue((fact(),), REPOSITORY, RELEASE)

    def test_no_queue_configured_queues_nothing_and_does_not_raise(self):
        """*Not configured* and *refused* are different: a run on a laptop
        with no database should not warn about a store it was never asked to
        write."""

        assert service(None).enqueue((fact(),), REPOSITORY, RELEASE) == ()

    def test_nothing_to_queue_is_not_a_failure_either(self):
        assert service(InMemoryQueue()).enqueue((), REPOSITORY, RELEASE) == ()


class TestRecordingADecision:
    """REV-4, REV-5 and REV-D9."""

    def test_accepting_marks_the_item_and_ratifies_the_candidate(self):
        queue, ratifier = InMemoryQueue(), CountingRatifier()
        reviews = service(queue, ratifier)
        item_id = reviews.enqueue((fact(),), REPOSITORY, RELEASE)[0]

        outcome = reviews.decide(accepted(item_id), REPOSITORY)

        assert outcome.status is ReviewStatus.ACCEPTED
        assert outcome.ratified == 1
        assert ratifier.calls == [(REPOSITORY, "rule-candidate-1", "architect")]

    def test_rejecting_records_the_rejection_and_ratifies_nothing(self):
        """A rejection says a mined candidate was wrong, which is the only
        ground truth this system produces for free. Keeping only the
        confirmations would leave a confirmation rate of 100% by
        construction."""

        queue, ratifier = InMemoryQueue(), CountingRatifier()
        reviews = service(queue, ratifier)
        item_id = reviews.enqueue((fact(),), REPOSITORY, RELEASE)[0]

        outcome = reviews.decide(rejected(item_id), REPOSITORY)

        assert outcome.status is ReviewStatus.REJECTED
        assert outcome.ratified == 0
        assert ratifier.calls == []
        assert queue.get(item_id).status == str(ReviewStatus.REJECTED)

    def test_a_decision_on_an_unknown_item_is_a_lookup_failure(self):
        with pytest.raises(LookupError, match="no review item"):
            service(InMemoryQueue(), CountingRatifier()).decide(
                accepted("nope"), REPOSITORY
            )

    def test_a_confirmation_matching_nothing_reports_zero_rather_than_raising(self):
        """The candidate has been superseded since it was queued. That is
        information for whoever pressed the button, not a fault."""

        queue = InMemoryQueue()
        reviews = service(queue, CountingRatifier(applies_to=0))
        item_id = reviews.enqueue((fact(),), REPOSITORY, RELEASE)[0]

        assert reviews.decide(accepted(item_id), REPOSITORY).ratified == 0

    def test_accepting_a_fact_with_no_candidate_ratifies_nothing(self):
        """A fact can be queued for a reason other than a weak candidate - an
        inferred dependency, an uncertain verification - and accepting it says
        the fact was read right, not that a rule was."""

        queue, ratifier = InMemoryQueue(), CountingRatifier()
        reviews = service(queue, ratifier)
        uncovered = replace(fact(), governing_decision=None)
        item_id = reviews.enqueue((uncovered,), REPOSITORY, RELEASE)[0]

        assert reviews.decide(accepted(item_id), REPOSITORY).ratified == 0
        assert ratifier.calls == []

    def test_deciding_does_not_start_a_run(self):
        """Asserted on a double that counts runs, because a comment saying so
        is not a guarantee. Five confirmations would otherwise start five
        runs, each resolving against a log the others were still writing."""

        ratifier = CountingRatifier()
        reviews = service(InMemoryQueue(), ratifier)
        item_id = reviews.enqueue((fact(),), REPOSITORY, RELEASE)[0]

        reviews.decide(accepted(item_id), REPOSITORY)

        assert ratifier.runs_started == 0


class TestTheWriteBackAgainstTheRealKnowledgeModel:
    """REV-4 end to end, over a copy of the committed corpus.

    A copy, not the corpus: an earlier session pointed the real knowledge
    service at the committed store and rewrote nineteen validity intervals,
    which failed 135 unrelated tests on the next run.
    """

    @pytest.fixture
    def knowledge(self, tmp_path):
        store = tmp_path / "decisions"
        shutil.copytree(FIXTURES / "decisions", store)
        return (
            DecisionKnowledgeService(WorkspaceReader(), JsonlDecisionStore(store)),
            store / f"{REPOSITORY}.jsonl",
        )

    def events(self, log: Path) -> list[dict]:
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def one_decision(self, log: Path) -> str:
        return self.events(log)[0]["decision_id"]

    def test_accepting_appends_exactly_one_event_and_mutates_nothing(self, knowledge):
        service_under_test, log = knowledge
        before = self.events(log)

        applied = service_under_test.confirm(
            REPOSITORY, self.one_decision(log),
            ratified_by="architect", ratified_at=NOW,
        )
        after = self.events(log)

        assert applied == 1
        assert len(after) == len(before) + 1
        assert after[: len(before)] == before
        assert after[-1]["event"] == EVENT_DECISION_CONFIRMED

    def test_the_confirmed_record_is_authoritative_and_still_reconstructed(
        self, knowledge
    ):
        """What stops the loop manufacturing its own ground truth: a confirmed
        corpus has to stay distinguishable from a written one."""

        service_under_test, log = knowledge
        decision_id = self.one_decision(log)

        service_under_test.confirm(
            REPOSITORY, decision_id, ratified_by="architect", ratified_at=NOW
        )
        history = service_under_test.history(REPOSITORY)
        version = next(
            v
            for versions in history.versions.values()
            for v in versions
            if v.record.decision_id == decision_id
        )

        assert version.record.source_strength is EvidenceStrength.AUTHORITATIVE
        assert version.record.ratified_by == "architect"
        assert version.record.extraction_method is ExtractionMethod.RECONSTRUCTED

    def test_a_confirmation_naming_nothing_applies_to_nothing(self, knowledge):
        service_under_test, log = knowledge
        before = len(self.events(log))

        applied = service_under_test.confirm(
            REPOSITORY, "rule-that-does-not-exist",
            ratified_by="architect", ratified_at=NOW,
        )

        assert applied == 0
        assert len(self.events(log)) == before

    def test_the_log_only_ever_grows(self, knowledge):
        """A reversal is its own event. A record that can be deleted makes
        *what did the system believe last Tuesday* unanswerable, and that
        question is the whole point of the bitemporal model."""

        service_under_test, log = knowledge
        decision_id = self.one_decision(log)

        service_under_test.confirm(
            REPOSITORY, decision_id, ratified_by="architect", ratified_at=NOW
        )
        after_one = len(self.events(log))
        service_under_test.confirm(
            REPOSITORY, decision_id, ratified_by="architect", ratified_at=NOW
        )

        assert len(self.events(log)) >= after_one
        assert EVENT_DECISION_REVOKED not in {e["event"] for e in self.events(log)}


class TestTheCeilingLiftsOnRatification:
    """REV-D5 and REV-6. The condition that was missing from M6."""

    def decision(self, tier=SourceTier.DOCUMENTATION, ratified=False):
        """A governing record, optionally as a confirmation leaves it.

        Ratification raises the strength as well as stamping the name,
        because that is what `confirmed_event()` in M2 does - and a builder
        that stamped only the name would be testing a state the system never
        produces.
        """

        from .test_classification import decision as build

        record = build(tier)
        if ratified:
            record = replace(
                record,
                ratified_by="architect",
                ratified_at=NOW,
                source_strength=EvidenceStrength.AUTHORITATIVE,
            )
        return record

    def classify(self, record):
        """One fact, judged and audited, against the record passed in.

        Audited on purpose. Ratification lifts the *tier* ceiling and nothing
        else, so an unverified verdict stays capped at 0.65 and below the
        publish threshold however authoritative its rule is - which is
        correct, and which the next test asserts directly.
        """

        from .test_classification import fact as observed
        from .test_classification import verdict, verification

        return ClassificationService().classify(
            observed(),
            Resolution(governing=record),
            verdict(Verdict.CONTRADICTS, ArbiterAgreement.AGREED),
            verification(VerificationOutcome.AGREE),
            VerificationMode.PERFORMED,
        )

    def test_the_tier_cap_applies_to_an_unratified_record(self):
        caps = rules.applicable(
            rules.CapContext(
                tier=SourceTier.DOCUMENTATION,
                ratified=False,
                inferred=False,
                outcome=None,
                agreement=None,
                verification_mode=None,
                produced_without_a_model=False,
            )
        )

        assert [cap.name for cap in caps] == ["source_tier_3_documentation"]

    def test_the_tier_cap_does_not_apply_once_a_person_has_vouched(self):
        """The ceiling exists because nobody had vouched for the rule. Once
        somebody has, by name, at a recorded time, the condition it protects
        against is gone."""

        caps = rules.applicable(
            rules.CapContext(
                tier=SourceTier.DOCUMENTATION,
                ratified=True,
                inferred=False,
                outcome=None,
                agreement=None,
                verification_mode=None,
                produced_without_a_model=False,
            )
        )

        assert [cap.name for cap in caps] == []

    def test_the_same_fact_before_and_after_a_confirmation(self):
        """The whole loop, across three subcomponents, in one test.

        Everything else in this file protects this one, and it is the test
        that would have caught the defect: M2 raises the strength, M6 caps on
        the tier, and until REV-6 the two together left a confirmed candidate
        exactly where it was.
        """

        before = self.classify(self.decision())
        after = self.classify(self.decision(ratified=True))

        assert before.bucket == ValidationBucket.NEEDS_REVIEW
        assert before.route == Route.REVIEW
        assert before.score_trace.ceiling_applied == "source_tier_3_documentation"

        assert after.bucket == ValidationBucket.CONTRADICTED
        assert after.route == Route.PUBLISH
        assert after.confidence > before.confidence

    def test_a_ratified_record_is_still_capped_by_everything_else(self):
        """The exemption is the tier's alone, and this is where the first
        draft of these tests was wrong rather than the code.

        A ratified rule whose verdict nobody audited is still capped at 0.65,
        so it still routes to a person. The architect vouched for the *rule*;
        they said nothing about this verdict concerning it. Confirming a
        candidate lifts one ceiling, not all of them - and a confirmation that
        published an unaudited accusation would be the loop manufacturing
        exactly what it is built not to.
        """

        from .test_classification import fact as observed
        from .test_classification import verdict, verification

        result = ClassificationService().classify(
            observed(),
            Resolution(governing=self.decision(ratified=True)),
            verdict(Verdict.CONTRADICTS, ArbiterAgreement.AGREED),
            verification(VerificationOutcome.DISAGREE),
            VerificationMode.PERFORMED,
        )

        assert result.score_trace.ceiling_applied == "verification_disagree"
        assert result.confidence == 0.45
        assert result.bucket == ValidationBucket.INSUFFICIENT_EVIDENCE
        assert result.route == Route.REVIEW
