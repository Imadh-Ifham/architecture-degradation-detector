"""Architect review service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Queues what the system will not decide alone, and records what a person decided.

    Research module: M7.
"""

from datetime import UTC, datetime
from typing import Protocol

from ..models import ClassifiedFact, ReviewItem
from ..ports import ReviewQueueRepository
from . import _queue
from .models import ReviewDecision, ReviewOutcome, ReviewStatus


class Ratifier(Protocol):
    """Whatever can record that an architect accepted a candidate decision.

    Declared here rather than in `ports.py`, which is for the ways this
    component touches the outside world. This is a sibling subcomponent -
    the decision knowledge model - and naming the one method keeps the
    dependency to that method rather than to the whole of it.

    It returns how many decision versions the confirmation applied to, so a
    confirmation that matched nothing is visible rather than silent.
    """

    def confirm(
        self,
        repository_id: str,
        decision_id: str,
        *,
        ratified_by: str,
        ratified_at: datetime,
    ) -> int:
        """Append the confirmation and report how many versions it touched."""
        ...


class QueueUnavailable(RuntimeError):
    """The review queue could not be written, and the run carries on.

    Its own type so the orchestrator can tell *the queue refused* from *this
    subcomponent is not built yet*, which the stage reports differently. The
    run is already finished and correct by the time this is raised, and every
    row is rebuildable from the published document, so an unreachable queue
    makes the queue late rather than the run broken.
    """


class ArchitectReviewService:
    """Queues what the system will not decide alone, and records what a person decided."""

    def __init__(
        self,
        queue: ReviewQueueRepository | None = None,
        knowledge: Ratifier | None = None,
    ) -> None:
        """Bind the queue and the service that ratifies a candidate.

        Both default to `None`, which means *not configured*: a run on a
        laptop with no database queues nothing and says so, rather than
        warning about a store it was never asked to write. The distinction
        matters because a configured queue that refused is a fault and an
        absent one is not.
        """

        self._queue = queue
        self._knowledge = knowledge

    def enqueue(self, facts: tuple[ClassifiedFact, ...],
                repository_id: str = "", release_id: str = "") -> tuple[str, ...]:
        """Places facts needing human judgement on the review queue.

        Writes a row and renders nothing: the review surface belongs to the
        frontend, and a subcomponent that produced HTML would be impossible to
        test without one.

        A confirmed candidate is appended to the knowledge log as an event, so
        the fact revalidates against a ratified decision on the next run. That
        loop is what turns weak evidence into strong evidence rather than into
        a dead end.

        Idempotent per `(repository_id, release_id, fact_id)`. A run that
        queued an item and then failed at a later stage is re-run from the
        start, and the same fact must not arrive twice - one item per fact,
        whatever a person has already done with it.
        """

        items = _queue.items_for(
            facts, repository_id, release_id, datetime.now(UTC)
        )
        if not items:
            return ()

        if self._queue is None:
            return ()

        try:
            return tuple(self._queue.enqueue(item) for item in items)
        except Exception as error:  # noqa: BLE001
            # Deliberately broad, and bounded by what it does with the error:
            # it is re-raised as one type the caller handles by recording a
            # warning. The failures are a database being down, a driver timing
            # out, a constraint from somebody else's migration - an open set,
            # none of which may cost a run whose deliverable is already on
            # disk.
            raise QueueUnavailable(str(error)) from error

    def decide(self, decision: ReviewDecision, repository_id: str) -> ReviewOutcome:
        """Record what a person decided, and ratify the candidate when accepted.

        Two things happen on an acceptance and they are in this order: the
        item is marked, then the knowledge log is appended to. If the append
        fails the item is already marked, which is the safe half to have done
        first - a decision recorded without its ratification is visible and
        repeatable, where a ratification without a decision is a change to the
        log that nobody can account for.

        **A rejection appends nothing.** The candidate does not gain
        authority, and it is not deleted either: the item records that a mined
        candidate was wrong, which is the only ground truth this system
        produces for free. Discarding rejections would leave a confirmation
        rate of 100% by construction.

        **And this does not re-run the release.** It appends and returns. When
        the verdict changes has to be a decision somebody made rather than a
        side effect - five confirmations would otherwise start five runs, each
        resolving against a log the others were still changing.
        """

        if self._queue is None:
            raise QueueUnavailable("no review queue is configured")

        item = self._queue.get(decision.item_id)
        if item is None:
            raise LookupError(f"no review item '{decision.item_id}'")

        self._queue.resolve(decision)
        status = ReviewStatus.ACCEPTED if decision.accepted else ReviewStatus.REJECTED

        return ReviewOutcome(
            item_id=decision.item_id,
            status=status,
            ratified=self._ratify(item, decision, repository_id),
        )

    def _ratify(
        self, item: ReviewItem, decision: ReviewDecision, repository_id: str
    ) -> int:
        """Append the confirmation, and report how many versions it applied to.

        Zero is a real answer and it is returned rather than raised: a
        confirmation that matched no open record means the candidate has been
        superseded since it was queued, which is information for whoever
        pressed the button and not a fault.
        """

        if not decision.accepted or self._knowledge is None:
            return 0
        if item.candidate_decision_id is None:
            # Nothing to ratify. A fact can be queued for a reason other than
            # a weak candidate - an inferred dependency, an uncertain
            # verification - and accepting it says the fact was read right,
            # not that a rule was.
            return 0

        return self._knowledge.confirm(
            repository_id,
            item.candidate_decision_id,
            ratified_by=decision.decided_by,
            ratified_at=decision.decided_at,
        )
