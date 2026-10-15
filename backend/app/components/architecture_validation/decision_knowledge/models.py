"""Decision knowledge data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass, field

from ..models import DecisionRecord


@dataclass(frozen=True)
class DecisionVersion:
    """One decision over one release range, as held in the index.

    The range is half-open, so a decision and the decision superseding it never
    both apply to the same release.
    """

    record: DecisionRecord
    valid_from: str
    valid_to: str | None

    def covers(self, release_id: str) -> bool:
        """Whether this version was in force at `release_id`.

        The comparison lives in `supersession.py`, with the rest of the
        interval logic, so there is one place that knows what half-open means.
        Identifiers are parsed into ordered versions there rather than
        compared as text: `"v0.10.0" > "v0.9.0"` is false as a string.
        """

        from .supersession import covers

        return covers(self, release_id)


@dataclass(frozen=True)
class KnowledgeEvent:
    """One entry in the append-only log."""

    event_type: str
    payload: dict
    recorded_at: str


@dataclass(frozen=True)
class ModeAvailability:
    """What one decision mode would find, reported before it is chosen.

    `ran` and `records` answer different questions and the gate needs both. A
    mode with no records that ran has told us something about the repository;
    a mode that could not run has not been tried. Presenting them the same way
    is how a user ends up choosing an empty mode and reading the result as a
    clean validation.

    `by_source` exists so the number can be traced. "17 rules" invites exactly
    one question, and "16 from the network policies, 1 default-deny" answers
    it without opening anything.
    """

    mode: str
    ran: bool
    records: int
    reason: str | None = None
    by_source: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "ran": self.ran,
            "records": self.records,
            "reason": self.reason,
            "by_source": dict(self.by_source),
        }


@dataclass(frozen=True)
class AppendOutcome:
    """What one release's scan added to the decision history.

    `closed` is the interesting number and the one the demonstration turns
    on: a rule the log held that this release no longer states. `unchanged`
    is the quiet majority, and reporting it is what makes a re-run visibly a
    no-op rather than silently one.
    """

    release_id: str
    recorded: int
    closed: int
    unchanged: int
    events: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "release_id": self.release_id,
            "recorded": self.recorded,
            "closed": self.closed,
            "unchanged": self.unchanged,
        }


@dataclass(frozen=True)
class DecisionStageOutcome:
    """What the decision stage did before any fact was resolved.

    One shape covering the three things that happen in order: the chosen mode
    was collected, the gate let the run through, and the history was brought
    up to date with this release.

    `in_force` is the number a reader wants and the one nothing else reports:
    how many decisions actually applied at this release, as opposed to how
    many the log holds in total.
    """

    mode: str
    release_id: str
    records: int
    in_force: int
    recorded: int
    closed: int
    unchanged: int
    declared: int = 0
    reconstructed: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    releases_in_log: tuple[str, ...] = ()

    def counts(self) -> dict:
        """The stage's numbers, for the run record.

        `declared` and `reconstructed` are the pair worth reading first. They
        say what kind of evidence the whole run rests on, which is the
        question every verdict in it inherits - and on a repository with no
        decision records the honest answer is that all of it was
        reconstructed.
        """

        return {
            "decisions": self.records,
            "in_force": self.in_force,
            "declared": self.declared,
            "reconstructed": self.reconstructed,
            "recorded": self.recorded,
            "intervals_closed": self.closed,
            "unchanged": self.unchanged,
            "releases_in_log": len(self.releases_in_log),
            **{f"from_{source}": count for source, count in self.by_source.items()},
        }
