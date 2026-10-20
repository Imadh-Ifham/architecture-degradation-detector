"""The decision history, replayed into something answerable.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Turns the event log back into versions: one decision over one range of
    releases, keyed by what it is about.

    Rebuilt by replaying the whole log every time rather than kept up to date
    incrementally. At this size that costs microseconds, and it means the
    replay path - the one the reproducibility claim rests on - is the only
    path there is, so it cannot rot while an incremental path is the one
    actually used.

    The key is the canonical subject, the constraint and the canonical
    object. Canonical, because the architecture calls an element
    `paymentservice` and a policy may call it `payment-service`, and a lookup
    that does not reduce both sides finds nothing and reports the fact as
    uncovered - a wrong answer that looks like a finding.

    It is keyed in one direction only. None of the four constraints is
    symmetric: `may_call(a, b)` permits a to call b and says nothing about b
    calling a. Indexing both orderings would turn every permission into a
    mutual one, which is the same error the direction tests guard the scan
    against.
"""

from dataclasses import dataclass, field

from .._identity import canonical_name
from .._release import release_sort_key
from ._events import (
    DECISION_BACKDATED,
    DECISION_CONFIRMED,
    DECISION_RECORDED,
    DECISION_SUPERSEDED,
    RELEASE_SCANNED,
    record_from_event,
)
from .models import DecisionVersion

Key = tuple[str, str, str]


def index_key(subject: str, constraint: str, object_: str) -> Key:
    """The identity a decision is looked up by."""

    return (canonical_name(subject), str(constraint), canonical_name(object_))


@dataclass(frozen=True)
class DecisionIndex:
    """Every decision the log holds, as versions with their intervals."""

    versions: dict[Key, tuple[DecisionVersion, ...]] = field(default_factory=dict)
    open_events: dict[str, dict] = field(default_factory=dict)
    releases_seen: tuple[str, ...] = ()
    by_hash: dict[str, tuple[Key, int]] = field(default_factory=dict)
    """Where each recorded rule sits, by the hash of its content.

    Needed because "do we already know this rule for this release" is a
    question about intervals, not about what is still open: a rule whose
    interval was closed at a later release is still known for the earlier one,
    and re-reading that release must not record it a second time.
    """

    @classmethod
    def from_events(cls, events: list[dict]) -> "DecisionIndex":
        """Replay a log into versions.

        A superseded event closes the open version with the same record hash.
        It is matched on the hash rather than on the decision id because one
        id can be stated by two releases from two files, and closing the wrong
        one would move a boundary rather than report one.
        """

        versions: dict[Key, list[DecisionVersion]] = {}
        open_events: dict[str, dict] = {}
        open_versions: dict[str, tuple[Key, int]] = {}
        located: dict[str, tuple[Key, int]] = {}
        releases: list[str] = []

        for event in events:
            kind = event.get("event")

            if kind == RELEASE_SCANNED:
                if event["release_id"] not in releases:
                    releases.append(event["release_id"])
                continue

            if kind == DECISION_RECORDED:
                record = record_from_event(event)
                key = index_key(record.subject, record.constraint, record.object)
                digest = event["record_hash"]

                standing_at = open_versions.get(digest)
                if standing_at is not None:
                    # The same rule, from the same file, already open. Not a
                    # second decision about this pair - the same one, recorded
                    # again by a scan that did not know the log held it.
                    #
                    # **Replay has to be idempotent, not just append-only.** A
                    # log written before the scan knew how to backdate holds
                    # these duplicates, and reading them as rivals makes every
                    # fact about the pair `ambiguous` for ever - a log that can
                    # never be read correctly again. Collapsing them here
                    # repairs such a log on read instead of requiring somebody
                    # to delete it, and leaves a correct log untouched.
                    #
                    # A rule stated in *two different files* has two hashes and
                    # stays two versions, which is the distinction `record_hash`
                    # exists to make.
                    at_key, position = standing_at
                    standing = versions[at_key][position]
                    if release_sort_key(record.valid_from) < release_sort_key(
                        standing.valid_from
                    ):
                        versions[at_key][position] = DecisionVersion(
                            record=standing.record,
                            valid_from=record.valid_from,
                            valid_to=standing.valid_to,
                        )
                        open_events[digest] = {
                            **open_events[digest],
                            "valid_from": record.valid_from,
                        }
                    continue

                entry = DecisionVersion(
                    record=record, valid_from=record.valid_from, valid_to=record.valid_to
                )
                versions.setdefault(key, []).append(entry)
                located[digest] = (key, len(versions[key]) - 1)
                if record.valid_to is None:
                    open_events[digest] = event
                    open_versions[digest] = (key, len(versions[key]) - 1)
                continue

            if kind == DECISION_CONFIRMED:
                # A confirmation does not open or close an interval. It raises
                # the strength of the version already there, which is why the
                # event carries the whole record and replay rebuilds it.
                placed = located.get(event["record_hash"])
                if placed is None:
                    continue
                key, position = placed
                standing = versions[key][position]
                versions[key][position] = DecisionVersion(
                    record=record_from_event(event),
                    valid_from=standing.valid_from,
                    valid_to=standing.valid_to,
                )
                continue

            if kind == DECISION_BACKDATED:
                # The same rule, known to be older than the log recorded. Its
                # interval opens earlier; nothing else about it changes, and
                # the record it opened stays where it is.
                placed = located.get(event["record_hash"])
                if placed is None:
                    continue
                key, position = placed
                standing = versions[key][position]
                versions[key][position] = DecisionVersion(
                    record=standing.record,
                    valid_from=event["valid_from"],
                    valid_to=standing.valid_to,
                )
                open_event = open_events.get(event["record_hash"])
                if open_event is not None:
                    # So a later scan of a release earlier still compares
                    # against where the interval now opens, not where it did.
                    open_events[event["record_hash"]] = {
                        **open_event,
                        "valid_from": event["valid_from"],
                    }
                continue

            if kind == DECISION_SUPERSEDED:
                digest = event["record_hash"]
                standing_at = open_versions.pop(digest, None)
                open_events.pop(digest, None)
                if standing_at is None:
                    continue
                key, position = standing_at
                closing = versions[key][position]
                versions[key][position] = DecisionVersion(
                    record=closing.record,
                    valid_from=closing.valid_from,
                    valid_to=event["valid_to"],
                )

        built = {key: tuple(entries) for key, entries in versions.items()}
        return cls(
            versions=built,
            open_events=open_events,
            releases_seen=tuple(releases),
            by_hash=located,
        )

    def versions_of(
        self, subject: str, constraint: str, object_: str
    ) -> tuple[DecisionVersion, ...]:
        """Every version recorded about one subject, constraint and object."""

        return self.versions.get(index_key(subject, constraint, object_), ())

    def open_versions(self) -> tuple[DecisionVersion, ...]:
        """Every version still in force, which is every one with no end."""

        return tuple(
            version
            for entries in self.versions.values()
            for version in entries
            if version.valid_to is None
        )

    def version_at(self, digest: str) -> DecisionVersion | None:
        """The version a record hash refers to, if the log holds one."""

        placed = self.by_hash.get(digest)
        if placed is None:
            return None
        key, position = placed
        return self.versions[key][position]

    def covering(self, release_id: str) -> set[str]:
        """The hashes of every rule already known to apply at this release."""

        return {
            digest
            for digest in self.by_hash
            if (version := self.version_at(digest)) is not None
            and version.covers(release_id)
        }

    def decision_count(self) -> int:
        """How many versions the log holds, closed ones included."""

        return sum(len(entries) for entries in self.versions.values())


__all__ = ["DecisionIndex", "Key", "index_key"]
