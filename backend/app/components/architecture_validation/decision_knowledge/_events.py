"""The events a decision history is made of, and how a scan becomes them.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    A scan reads one release and sees what is there. A validity interval is a
    statement about two: `valid_to` says a rule stopped applying. Nothing in a
    single working tree says that something used to be there, so the closing
    boundary cannot come from the scan - it comes from comparing the scan with
    what the log already holds.

    That comparison is this module, and it is the mechanism behind the only
    claim this component is remembered for. It is also the reason none of it
    touches a disk: events in, events out, and the store writes them.

      in the log, in the scan          nothing to do, the interval still holds
      not in the log, in the scan      DECISION_RECORDED, interval opens here
      in the log, NOT in the scan      DECISION_SUPERSEDED, interval closes here
      neither                          not our business

    Absence is a weaker signal than a written replacement, so two guards sit
    on it. A source that produced nothing closes nothing, because a scan that
    found no rules is a broken scan rather than an architecture that withdrew
    every rule it had. And a source only ever closes its own records: a
    decision somebody wrote down is not withdrawn because a configuration
    scan did not reconstruct it.

    Nothing is ever edited and nothing is ever removed. Closing an interval is
    itself an appended event, so the log still replays to the same state it
    always did, one event later.
"""

import hashlib
from collections.abc import Iterable, Sequence
from datetime import datetime

from .._identity import canonical_name
from .._release import release_sort_key
from ..models import (
    ConstraintKind,
    DecisionRecord,
    EvidenceStrength,
    ExtractionMethod,
    SourceTier,
)

DECISION_RECORDED = "DECISION_RECORDED"
DECISION_SUPERSEDED = "DECISION_SUPERSEDED"
DECISION_CONFIRMED = "DECISION_CONFIRMED"
RELEASE_SCANNED = "RELEASE_SCANNED"

RECORD_HASH_LENGTH = 16


def record_hash(record: DecisionRecord) -> str:
    """The identity of one rule, so re-reading it appends nothing.

    Over the canonical subject and object, the constraint and the file it was
    read from. Two scans of one release produce the same hashes, which is what
    makes re-running a failed validation safe - and the same content
    addressing normalisation uses for a fact, for the same reason.

    The reference is part of the identity on purpose. The same rule stated in
    two different files is two statements of it, and a release that drops one
    of them has changed something worth recording.
    """

    material = "|".join(
        (
            canonical_name(record.subject),
            str(record.constraint),
            canonical_name(record.object),
            record.source_ref,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:RECORD_HASH_LENGTH]


def recorded_event(
    record: DecisionRecord, sequence: int, supersedes: str | None = None
) -> dict:
    """The event that opens a rule's validity interval."""

    event = record.to_event()
    event.update(
        {
            "seq": sequence,
            "event": DECISION_RECORDED,
            "at": record.extracted_at.isoformat(),
            "record_hash": record_hash(record),
        }
    )
    if supersedes:
        event["supersedes"] = supersedes
    return event


def superseded_event(
    *,
    open_event: dict,
    release_id: str,
    sequence: int,
    at: datetime,
    superseded_by: str | None,
) -> dict:
    """The event that closes a rule's interval at the release it vanished from.

    It repeats the rule's identity rather than pointing at the event that
    opened it. A log is read by replaying it from the start, and an entry that
    only makes sense once you have found another entry is an entry somebody
    will eventually read on its own and misunderstand.
    """

    return {
        "seq": sequence,
        "event": DECISION_SUPERSEDED,
        "at": at.isoformat(),
        "record_hash": open_event["record_hash"],
        "decision_id": open_event["decision_id"],
        "subject": open_event["subject"],
        "constraint": open_event["constraint"],
        "object": open_event["object"],
        "valid_from": open_event["valid_from"],
        "valid_to": release_id,
        "source": open_event["source"],
        "source_repository": open_event["source_repository"],
        "superseded_by": superseded_by,
        "reason": f"not stated by {open_event['source']} at {release_id}",
    }


def changes(
    *,
    open_events: dict[str, dict],
    covered: set[str],
    records: Sequence[DecisionRecord],
    release_id: str,
    closing_sources: Iterable[str],
    at: datetime,
    next_sequence: int,
) -> list[dict]:
    """The events this scan adds to a log that already holds these.

    `open_events` are the recorded events whose interval is still open, keyed
    by record hash. `covered` is every hash the log already knows applies at
    this release, open or closed. `closing_sources` are the sources entitled
    to close something - those that ran *and* found at least one rule.

    The two sets are different questions and both are needed, because a log is
    not always built forwards. Re-reading an earlier release has to be a
    no-op, and it is only a no-op if a rule whose interval was *closed* at a
    later release still counts as known for this one - and if a rule that
    began at a later release cannot be withdrawn by this one.
    """

    scanned = {record_hash(record): record for record in records}
    closing = set(closing_sources)
    release = release_sort_key(release_id)
    sequence = next_sequence
    events: list[dict] = []

    vanished = [
        event
        for digest, event in sorted(open_events.items())
        if digest not in scanned
        and event["source"] in closing
        and release_sort_key(event["valid_from"]) <= release
    ]
    new = [
        (digest, record)
        for digest, record in sorted(
            scanned.items(), key=lambda item: (item[1].decision_id, item[1].source_ref)
        )
        if digest not in covered
    ]

    superseded_by_new: dict[str, str] = {}
    for event in vanished:
        replacement = _replacement_for(event, new)
        if replacement:
            superseded_by_new[replacement] = event["decision_id"]
        events.append(
            superseded_event(
                open_event=event,
                release_id=release_id,
                sequence=sequence,
                at=at,
                superseded_by=replacement,
            )
        )
        sequence += 1

    for _, record in new:
        events.append(
            recorded_event(
                record, sequence, supersedes=superseded_by_new.get(record.decision_id)
            )
        )
        sequence += 1

    return events


def _replacement_for(
    open_event: dict, new: Sequence[tuple[str, DecisionRecord]]
) -> str | None:
    """The one new rule that takes a vanished rule's place, if there is one.

    Same subject, same kind of constraint, different object: the team still
    constrains this, and constrains it differently. Two candidates mean the
    replacement is a guess, and a guess written into a supersession chain is
    worse than an unexplained gap - so zero or several both yield nothing.
    """

    candidates = [
        record.decision_id
        for _, record in new
        if canonical_name(record.subject) == canonical_name(open_event["subject"])
        and str(record.constraint) == open_event["constraint"]
        and canonical_name(record.object) != canonical_name(open_event["object"])
    ]
    return candidates[0] if len(candidates) == 1 else None


def release_scanned_event(
    *,
    release_id: str,
    sources: Sequence[str],
    recorded: int,
    closed: int,
    sequence: int,
    at: datetime,
) -> dict:
    """The marker saying a release was looked at.

    Without it a release whose configuration stated exactly the same rules as
    the one before leaves no trace, and the log cannot tell "nothing was
    superseded" from "nothing is known about that release". Those are
    different answers and the run publishes which one it is.
    """

    return {
        "seq": sequence,
        "event": RELEASE_SCANNED,
        "at": at.isoformat(),
        "release_id": release_id,
        "sources": list(sources),
        "recorded": recorded,
        "closed": closed,
    }


def confirmed_event(
    *, open_event: dict, ratified_by: str, ratified_at: datetime, sequence: int
) -> dict:
    """The event that records an architect accepting a reconstructed rule.

    It raises the record's strength and nothing else. `extraction_method`
    stays whatever it was, for the record's whole life, so a corpus of
    confirmed rules can never be mistaken for a corpus of written ones.
    """

    event = dict(open_event)
    event.update(
        {
            "seq": sequence,
            "event": DECISION_CONFIRMED,
            "at": ratified_at.isoformat(),
            "source_strength": EvidenceStrength.AUTHORITATIVE,
            "ratified_by": ratified_by,
            "ratified_at": ratified_at.isoformat(),
        }
    )
    return event


def record_from_event(event: dict) -> DecisionRecord:
    """Rebuild the record an event recorded.

    Replay has to produce the record itself, not a summary of it: the
    evidence package the reasoner is given quotes the rule's own text and
    cites the file it came from.
    """

    return DecisionRecord(
        decision_id=event["decision_id"],
        subject=event["subject"],
        constraint=ConstraintKind(event["constraint"]),
        object=event["object"],
        valid_from=event["valid_from"],
        valid_to=event.get("valid_to"),
        source=event["source"],
        source_repository=event["source_repository"],
        source_tier=SourceTier(event["source_tier"]),
        source_strength=EvidenceStrength(event["source_strength"]),
        source_ref=event["source_ref"],
        extraction_method=ExtractionMethod(event["extraction_method"]),
        extracted_at=datetime.fromisoformat(event["extracted_at"]),
        rationale=event.get("rationale"),
        supersedes=event.get("supersedes"),
        ratified_by=event.get("ratified_by"),
        ratified_at=datetime.fromisoformat(event["ratified_at"])
        if event.get("ratified_at")
        else None,
    )


__all__ = [
    "DECISION_CONFIRMED",
    "DECISION_RECORDED",
    "DECISION_SUPERSEDED",
    "RELEASE_SCANNED",
    "changes",
    "confirmed_event",
    "record_hash",
    "record_from_event",
    "recorded_event",
    "release_scanned_event",
    "superseded_event",
]
