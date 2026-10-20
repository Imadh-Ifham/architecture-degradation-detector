"""Decision knowledge service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Holds the decision history and answers which decision governed at a release.

    It also owns where the decisions come from: three sources behind one
    protocol, chosen per run and recorded on the result. The sources are built
    here rather than injected one by one, because which sources exist is this
    subcomponent's own knowledge - what is injected is the two things it
    cannot provide for itself, which are the ability to read a repository and
    somewhere to keep the log.

    The decision history accumulates across runs, and that is deliberate
    rather than incidental. A scan sees one release; a validity interval is a
    statement about two, so the only way to learn that a rule stopped
    applying is to compare a release against what the log already holds.

    Research module: M2.
"""

from .models import AppendOutcome, DecisionStageOutcome, ModeAvailability
from .._identity import canonical_name
from ..models import ExtractionMethod, ObservedFact, Resolution
from ..ports import DecisionKnowledgeStore, SourceArtifactReader
from datetime import datetime

from ._events import (
    DECISION_BACKDATED,
    DECISION_RECORDED,
    DECISION_SUPERSEDED,
    changes,
    confirmed_event,
    record_hash,
    release_scanned_event,
)
from ._index import DecisionIndex
from .supersession import CONSTRAINT_RELATIONSHIP, WILDCARD, resolve_fact
from .sources import (
    MODES,
    SourceOutcome,
    SourceRequest,
    build_sources,
    registered_modes,
    sources_for,
)


class DecisionStoreMissing(RuntimeError):
    """The service was asked for history it has nowhere to keep."""


class NoDecisionsAvailable(RuntimeError):
    """There is nothing to validate against, so the run does not start.

    Carries what every mode would have found, because the refusal is also the
    only place a user learns which one to pick. A block that does not say what
    to do instead is a block somebody works around.

    Why this is a refusal and not a warning: with an empty store every fact
    resolves to no decision, every fact lands in the uncovered bucket, and the
    published graph says "nothing contradicts the architecture" - a sentence
    that is true, worthless, and indistinguishable from a clean validation of
    a healthy system.
    """

    def __init__(self, mode: str, availability: dict[str, ModeAvailability]) -> None:
        self.mode = mode
        self.availability = availability
        super().__init__(self._message())

    @property
    def yields(self) -> dict[str, int]:
        """How many decisions each mode would have supplied."""

        return {name: found.records for name, found in self.availability.items()}

    def _message(self) -> str:
        lines = [
            f"no decisions to validate against in mode '{self.mode}'",
            *(
                f"  {name:<14} {found.records} records"
                + (f"  ({found.reason})" if found.reason else "")
                for name, found in sorted(self.availability.items())
            ),
        ]
        best = max(self.availability.values(), key=lambda found: found.records)
        if best.records:
            lines.append(f"  choose '{best.mode}' instead")
        return "\n".join(lines)


class DecisionKnowledgeService:
    """Holds the decision history and answers which decision governed at a release."""

    def __init__(
        self,
        artifact_reader: SourceArtifactReader,
        store: DecisionKnowledgeStore | None = None,
    ) -> None:
        self._artifact_reader = artifact_reader
        self._store = store

    def resolve(self, fact: ObservedFact, repository_id: str) -> Resolution:
        """Resolves which decision governs a fact at the fact's release.

        Reads an append-only event log and replays it into an index of
        half-open validity intervals, so the answer to "what applied at this
        release" stays correct after a later decision supersedes an earlier
        one.

        Returns ambiguity rather than resolving it when two decisions apply and
        neither supersedes the other: an invented tiebreak cannot be shown to
        be right.

        The repository is a parameter because a fact describes a relationship
        in a release and says nothing about which system it came from, while
        the history is one system's. Replaying it per fact costs microseconds
        at this size - and an index cached across calls is an index an append
        can leave stale, which is a wrong answer rather than a slow one.
        """

        return resolve_fact(self.history(repository_id), fact)

    def confirm(
        self,
        repository_id: str,
        decision_id: str,
        *,
        ratified_by: str,
        ratified_at: datetime,
    ) -> int:
        """Record that an architect accepted a candidate decision.

        The record gains full authority and keeps its own history: it stays
        `reconstructed`, and it carries who ratified it and when, for the rest
        of its life. Clearing that would turn the pipeline into a way of
        manufacturing its own ground truth - run it once, confirm everything,
        and the store now holds decisions that look written and were inferred.

        Returns how many versions the confirmation applied to, so a
        confirmation naming nothing is visible rather than silent.
        """

        history = self._replay(repository_id)
        index = DecisionIndex.from_events(history)

        matching = [
            event
            for event in history
            if event.get("event") == DECISION_RECORDED
            and event["decision_id"] == decision_id
            and event["record_hash"] in index.open_events
        ]
        if not matching:
            return 0

        self._append(
            repository_id,
            [
                confirmed_event(
                    open_event=event,
                    ratified_by=ratified_by,
                    ratified_at=ratified_at,
                    sequence=len(history) + offset + 1,
                )
                for offset, event in enumerate(matching)
            ],
        )
        return len(matching)

    def availability(self, request: SourceRequest) -> dict[str, ModeAvailability]:
        """Report what each mode would find, without starting a run.

        Every source is collected once and the modes are summarised from the
        same results, so the number a user is shown when choosing is the
        number the run then produces. The alternative - a cheap estimate for
        the picker and the real thing for the run - is two answers to one
        question, and the day they differ the picker promises records that
        never arrive.

        Collecting is safe to do here: it reads a handful of files, calls no
        model and writes nothing.
        """

        return self._summarise_all(self._collect_all(request))

    def collect(self, request: SourceRequest, mode: str) -> tuple[SourceOutcome, ...]:
        """Run the sources one mode reads, in order."""

        return tuple(
            source.collect(request)
            for source in sources_for(mode, self._artifact_reader)
        )

    def append_scan(
        self, request: SourceRequest, outcomes: tuple[SourceOutcome, ...]
    ) -> AppendOutcome:
        """Record what this release states, and close what it no longer does.

        The whole supersession mechanism is here and it is four lines of
        bookkeeping around one comparison. What makes it trustworthy is what
        it refuses to do: a source that found nothing closes nothing, and no
        source closes another's records.

        A release that states exactly what the log already holds appends only
        the marker saying it was looked at - and appends nothing at all if it
        has been looked at before, which is what makes re-running a failed
        validation safe.
        """

        history = self._replay(request.code_repository_id)
        index = DecisionIndex.from_events(history)

        records = tuple(
            record for outcome in outcomes if outcome.ran for record in outcome.records
        )
        closing_sources = {
            outcome.source for outcome in outcomes if outcome.ran and outcome.records
        }

        new_events = changes(
            open_events=index.open_events,
            covered=index.covering(request.release_id),
            records=records,
            release_id=request.release_id,
            closing_sources=closing_sources,
            at=request.extracted_at,
            next_sequence=len(history) + 1,
        )

        recorded = len(
            [e for e in new_events if e["event"] == DECISION_RECORDED]
        )
        closed = len(
            [e for e in new_events if e["event"] == DECISION_SUPERSEDED]
        )
        backdated = len(
            [e for e in new_events if e["event"] == DECISION_BACKDATED]
        )
        already_seen = request.release_id in index.releases_seen

        if new_events or not already_seen:
            new_events.append(
                release_scanned_event(
                    release_id=request.release_id,
                    sources=sorted(outcome.source for outcome in outcomes if outcome.ran),
                    recorded=recorded,
                    closed=closed,
                    backdated=backdated,
                    sequence=len(history) + len(new_events) + 1,
                    at=request.extracted_at,
                )
            )
            self._append(request.code_repository_id, new_events)

        return AppendOutcome(
            release_id=request.release_id,
            recorded=recorded,
            closed=closed,
            unchanged=len(
                {record_hash(record) for record in records}
                & index.covering(request.release_id)
            ),
            backdated=backdated,
            events=tuple(new_events),
        )

    def establish(self, request: SourceRequest, mode: str) -> DecisionStageOutcome:
        """Collect the chosen mode, refuse an empty one, and bring the log up
        to date with this release.

        The three things happen in this order on purpose. Collecting is what
        the gate reads, so it cannot be skipped; the gate runs before anything
        is written, so a refused run leaves the history untouched; and the
        append happens before any fact is resolved, so this release's own
        rules are in force when its facts are judged.
        """

        collected = self._collect_all(request)
        available = self._summarise_all(collected)
        chosen = available[mode]
        if not chosen.records:
            raise NoDecisionsAvailable(mode, available)

        outcomes = tuple(collected[name] for name in MODES[mode])
        appended = self.append_scan(request, outcomes)
        index = self.history(request.code_repository_id)
        records = [
            record for outcome in outcomes if outcome.ran for record in outcome.records
        ]

        return DecisionStageOutcome(
            mode=mode,
            release_id=request.release_id,
            declared=len(
                [r for r in records if r.extraction_method is ExtractionMethod.DECLARED]
            ),
            reconstructed=len(
                [
                    r
                    for r in records
                    if r.extraction_method is ExtractionMethod.RECONSTRUCTED
                ]
            ),
            records=index.decision_count(),
            in_force=len(
                [
                    version
                    for versions in index.versions.values()
                    for version in versions
                    if version.covers(request.release_id)
                ]
            ),
            recorded=appended.recorded,
            closed=appended.closed,
            unchanged=appended.unchanged,
            by_source=dict(chosen.by_source),
            releases_in_log=index.releases_seen,
        )

    def rules_without_facts(
        self, repository_id: str, release_id: str, facts
    ) -> tuple[str, ...]:
        """Decisions in force about relationships nobody observed.

        A permission for a dependency the architecture does not contain. It is
        a finding about the system rather than a fault in the scan - either
        the dependency was removed and the rule outlived it, or recovery did
        not see something the configuration expects - so it is counted and
        named rather than filtered out.

        Rules about every pair are excluded: the default refusal is about
        relationships that do not exist by design.
        """

        observed = {
            (fact.subject.canonical, fact.object.canonical) for fact in facts
        }
        index = self.history(repository_id)

        return tuple(
            sorted(
                version.record.decision_id
                for versions in index.versions.values()
                for version in versions
                if version.covers(release_id)
                and CONSTRAINT_RELATIONSHIP.get(version.record.constraint) is not None
                and WILDCARD not in (version.record.subject, version.record.object)
                and (
                    canonical_name(version.record.subject),
                    canonical_name(version.record.object),
                )
                not in observed
            )
        )

    def history(self, repository_id: str) -> DecisionIndex:
        """The decision history for one repository, replayed."""

        return DecisionIndex.from_events(self._replay(repository_id))

    def _replay(self, repository_id: str) -> list[dict]:
        if self._store is None:
            raise DecisionStoreMissing(
                "This service was built without a decision store, so it can "
                "hold no history. Wire one in the composition root."
            )
        return self._store.replay(repository_id)

    def _append(self, repository_id: str, events: list[dict]) -> None:
        self._store.append(repository_id, events)

    def _collect_all(self, request: SourceRequest) -> dict:
        """Run every source once.

        Once, because the gate reads the same results the run then uses. Two
        collections would be two answers to one question, and the day they
        differ the refusal message describes a run that did not happen.
        """

        return {
            name: source.collect(request)
            for name, source in build_sources(self._artifact_reader).items()
        }

    def _summarise_all(self, collected: dict) -> dict[str, ModeAvailability]:
        return {mode: self._summarise(mode, collected) for mode in registered_modes()}

    def _summarise(self, mode: str, collected: dict) -> ModeAvailability:
        outcomes = [collected[name] for name in MODES[mode]]
        records = sum(len(outcome.records) for outcome in outcomes)

        return ModeAvailability(
            mode=mode,
            ran=any(outcome.ran for outcome in outcomes),
            records=records,
            reason=None
            if records
            else "; ".join(
                outcome.reason for outcome in outcomes if outcome.reason
            ),
            by_source={
                outcome.source: len(outcome.records)
                for outcome in outcomes
                if outcome.ran
            },
            # Kept per source rather than folded into `reason`, which is empty
            # whenever any other source supplied something - so in the mode
            # that reads all three, the one finding worth reporting is exactly
            # the one that would be dropped.
            source_notes={
                outcome.source: outcome.reason
                for outcome in outcomes
                if outcome.ran and outcome.reason
            },
        )
