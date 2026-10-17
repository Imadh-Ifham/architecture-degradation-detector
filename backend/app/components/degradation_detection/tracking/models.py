"""M3 models used only inside tracking: alignment decisions, similarity scores, reason codes.

``Lineage`` / ``LineageEvent`` are in the component ``models.py``, because the series builder,
M4 and the event export read them too.
"""

from enum import StrEnum

from pydantic import Field

from app.components.degradation_detection.models import (
    AlignMethod,
    InstanceTrack,
    InternalModel,
    Lineage,
    LineageEvent,
    LineageEventType,
)

# Reason codes M3 logs. Each one leaves a link out: a missed link shortens a series, a wrong one
# joins two histories and can invent a trend with a real p-value.
ALIGNMENT_AMBIGUOUS = "ALIGNMENT_AMBIGUOUS"  # best match not clearly ahead of the runner-up
ALIAS_CONFLICT = "ALIAS_CONFLICT"  # alias names a live id, or is claimed twice (split/merge?)
LINEAGE_KIND_CHANGED = "LINEAGE_KIND_CHANGED"  # same element, different kind: lineage ends
INSTANCE_MATCH_AMBIGUOUS = "INSTANCE_MATCH_AMBIGUOUS"  # best overlap tied with another instance
INSTANCE_TRACK_UNCHECKED = "INSTANCE_TRACK_UNCHECKED"  # detector did not run: track ends unresolved


class AlignOutcome(StrEnum):
    LINKED = "LINKED"
    AMBIGUOUS = "AMBIGUOUS"
    BELOW_MIN = "BELOW_MIN"  # Hungarian paired them, but the similarity is under rename_min
    ALIAS_CONFLICT = "ALIAS_CONFLICT"
    KIND_CHANGED = "KIND_CHANGED"


class SimilarityScore(InternalModel):
    """The three features of the similarity pass and their weighted total, each in [0, 1]."""

    name: float = Field(ge=0, le=1)
    neighbours: float = Field(ge=0, le=1)
    size: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)


class AlignmentDecision(InternalModel):
    """One non-trivial alignment decision between two consecutive releases.

    Exact matches are not recorded: they are the bulk of every release and trivially right.
    These rows are what ``alignment_sample.csv`` puts in front of a person to check.
    """

    from_release_id: str
    to_release_id: str
    from_element_ids: tuple[str, ...]
    to_element_ids: tuple[str, ...]
    kind: str  # kind of the old element(s)
    method: AlignMethod
    outcome: AlignOutcome
    score: SimilarityScore | None = None  # SIMILARITY only
    runner_up: float | None = Field(default=None, ge=0, le=1)  # best competing similarity


class Link(InternalModel):
    """Element ``from_element_id`` of one release is ``to_element_id`` of the next."""

    from_element_id: str
    to_element_id: str
    method: AlignMethod
    similarity: float | None = Field(default=None, ge=0, le=1)  # SIMILARITY only


class PairAlignment(InternalModel):
    """The alignment of two consecutive releases on the timeline."""

    from_release_id: str
    to_release_id: str
    links: tuple[Link, ...]  # one-to-one
    decisions: tuple[AlignmentDecision, ...]


class SplitMerge(InternalModel):
    """A split or merge between two releases (post-PP1, plan M3 step 3)."""

    event_type: LineageEventType
    from_element_ids: tuple[str, ...]
    to_element_ids: tuple[str, ...]


class TrackingResult(InternalModel):
    """What M3 knows about one system's timeline. T-10 adds series."""

    system_id: str
    lineages: tuple[Lineage, ...]
    events: tuple[LineageEvent, ...]
    decisions: tuple[AlignmentDecision, ...]
    tracks: tuple[InstanceTrack, ...]
