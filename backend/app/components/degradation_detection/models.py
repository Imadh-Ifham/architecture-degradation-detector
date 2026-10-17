"""Internal C3 models and enums shared by two or more subcomponents.

Pure data, no I/O. Internal models use ``extra="forbid"`` and are immutable. Models that cross a
port (``CanonicalRelease``...) and the enums that appear in the contracts (``Scope``,
``Worsening``, ``TestMethod``, ``ArchitectureStyle``...) live in ``app/domain/``.

Lineages (T-08) and instance tracks (T-09) are here because the series builder, M4 and the event
export read them too. The graph (``ArchGraph``) is used only by M2, so it
lives in ``detection/models.py``.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.canonical_release import CanonicalRelease, IntentEntry
from app.domain.degradation_event import Lifecycle, Scope, TestMethod, Worsening


class MetricLevel(StrEnum):
    ELEMENT = "element"
    SYSTEM = "system"


class TrendKind(StrEnum):
    GRADUAL_DRIFT = "GRADUAL_DRIFT"
    STEP_CHANGE = "STEP_CHANGE"


class InternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- M1 output: the timeline of one system, computed at the start of every run -------------


class TimelineEntry(InternalModel):
    # Position on this run's timeline. Computed per run, never stored as identity.
    ordinal: int = Field(ge=0)
    release: CanonicalRelease


class IntentRecord(InternalModel):
    """One intent, deduplicated across the releases of the timeline (plan M1, step 8)."""

    intent: IntentEntry  # as stated by the latest release that carries it
    first_seen_release: str
    last_seen_release: str


class Timeline(InternalModel):
    system_id: str
    entries: tuple[TimelineEntry, ...]
    intents: tuple[IntentRecord, ...] = ()


# --- M2 output: metrics and anti-pattern instances per release ----------------------------


class MetricDef(InternalModel):
    name: str
    level: MetricLevel
    unit: str
    # None: the metric supports detectors but has no worsening direction (e.g. instability).
    worsening: Worsening | None = None


class MetricObservation(InternalModel):
    release_id: str
    element_id: str | None  # None for a system-level metric
    metric: str
    value: float | None  # null stays null, never 0


class AntiPatternInstance(InternalModel):
    release_id: str
    local_instance_id: str
    anti_pattern_type: str
    catalog: str
    scope: Scope
    members: tuple[str, ...]
    measures: dict[str, float | None] = Field(default_factory=dict)


class ReleaseDetection(InternalModel):
    """Everything M2 found in one release; M3 builds series from a timeline of these."""

    release_id: str
    observations: tuple[MetricObservation, ...]
    instances: tuple[AntiPatternInstance, ...] = ()
    # Detector ids that ran on this release. A type missing here was not checked, so its absence
    # from ``instances`` says nothing (M3 must not resolve an instance track on it).
    detectors_run: tuple[str, ...] = ()


# --- M3 output: element lineages -----------------------------------------------------------


class AlignMethod(StrEnum):
    """How an element was linked to its predecessor in the previous release."""

    EXACT = "EXACT"  # same id
    ALIAS = "ALIAS"  # the new element lists the old id in ``aliases``
    SIMILARITY = "SIMILARITY"  # name + neighbours + size, one-to-one (Hungarian)


class LineageEventType(StrEnum):
    RENAME = "RENAME"
    SPLIT = "SPLIT"  # post-PP1
    MERGE = "MERGE"  # post-PP1


class LineageMember(InternalModel):
    # Position on this run's timeline, for building series. Never part of the identity.
    ordinal: int = Field(ge=0)
    release_id: str
    element_id: str


class Lineage(InternalModel):
    """One element through time, across renames. Its members are consecutive releases.

    ``lineage_id`` is ``LIN-<element_id>@<release_id>`` of the first member: unique, readable,
    and unchanged when later releases are added. A lineage never crosses a change of ``kind``
    and never spans a release it is missing from (the element that comes back starts a new one).
    """

    lineage_id: str
    kind: str
    members: tuple[LineageMember, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_members_consecutive(self) -> Self:
        ordinals = [member.ordinal for member in self.members]
        if ordinals != list(range(ordinals[0], ordinals[0] + len(ordinals))):
            raise ValueError("lineage members must be in consecutive releases")
        return self


class LineageEvent(InternalModel):
    """A change of identity inside a lineage, kept as evidence for M5."""

    lineage_id: str
    event_type: LineageEventType
    release_id: str  # the release where the new identity first appears
    from_element_ids: tuple[str, ...]
    to_element_ids: tuple[str, ...]
    method: AlignMethod
    similarity: float | None = Field(default=None, ge=0, le=1)  # SIMILARITY only


# --- M3 output: anti-pattern instance tracks -----------------------------------------------


class InstanceTransition(StrEnum):
    """What happened to a tracked instance since the previous release (by member count)."""

    INTRODUCED = "INTRODUCED"  # first release of the track
    GREW = "GREW"
    SHRANK = "SHRANK"
    PERSISTED = "PERSISTED"  # same number of members (they may have been swapped)


class TrackEnd(StrEnum):
    """Why a track has no occurrence after its last one."""

    OPEN = "OPEN"  # present in the last release of the timeline
    RESOLVED = "RESOLVED"  # the next release ran the detector and the instance was gone
    # The next release did not run the detector: nobody looked, so it is not a resolution.
    UNCHECKED = "UNCHECKED"


class InstanceOccurrence(InternalModel):
    """One M2 instance as one step of a track."""

    # Position on this run's timeline, for building series. Never part of the identity.
    ordinal: int = Field(ge=0)
    release_id: str
    local_instance_id: str
    members: tuple[str, ...]  # element ids in this release
    member_lineages: tuple[str, ...]  # lineage id of each member, same order as ``members``
    measures: dict[str, float | None] = Field(default_factory=dict)
    transition: InstanceTransition
    jaccard: float | None = Field(default=None, ge=0, le=1)  # with the previous occurrence

    @model_validator(mode="after")
    def _check_lineages_match_members(self) -> Self:
        if len(self.member_lineages) != len(self.members):
            raise ValueError("member_lineages must give one lineage id per member")
        return self


class InstanceTrack(InternalModel):
    """One anti-pattern instance through time. Its occurrences are consecutive releases.

    ``track_id`` is ``AP-<local_instance_id>@<release_id>`` of the first occurrence (e.g.
    ``AP-CyclicDependency:inventory@v1.1.0``): unique, readable and unchanged when releases are
    added, so the ``event_key`` built from it is stable across runs.

    ``lifecycle`` is the state at the end of the window (Sas, Avgeriou & Uyumaz 2022). Tracking
    sets ``introduced``, ``persistent`` or ``resolved``, or None when the track ends on a release
    that did not check its type; ``growing`` replaces ``persistent`` once M4 has found a
    significant worsening trend in an instance measure.
    """

    track_id: str
    anti_pattern_type: str
    catalog: str
    scope: Scope
    occurrences: tuple[InstanceOccurrence, ...] = Field(min_length=1)
    end: TrackEnd
    ended_at: str | None = None  # release where it was found gone, or not checked
    lifecycle: Lifecycle | None

    @model_validator(mode="after")
    def _check_track(self) -> Self:
        ordinals = [occurrence.ordinal for occurrence in self.occurrences]
        if ordinals != list(range(ordinals[0], ordinals[0] + len(ordinals))):
            raise ValueError("track occurrences must be in consecutive releases")
        if (self.end is TrackEnd.OPEN) != (self.ended_at is None):
            raise ValueError("ended_at is set exactly when the track is not OPEN")
        return self


# --- M3 output: series across releases ----------------------------------------------------


class SeriesPoint(InternalModel):
    ordinal: int = Field(ge=0)
    release_id: str
    value: float | None  # null stays null, never 0


class Series(InternalModel):
    scope: Scope
    subject_id: str
    metric: str
    points: tuple[SeriesPoint, ...]

    @model_validator(mode="after")
    def _check_ordinals_increase(self) -> Self:
        ordinals = [point.ordinal for point in self.points]
        if any(later <= earlier for earlier, later in zip(ordinals, ordinals[1:], strict=False)):
            raise ValueError("series ordinals must be strictly increasing")
        return self


# --- M4 output: trend results and event candidates ----------------------------------------


class TrendResult(InternalModel):
    scope: Scope
    subject_id: str
    metric: str
    n: int
    s: int
    var_s: float | None = None
    z: float | None = None
    tau: float
    p_value: float
    q_value: float | None = None  # set by Benjamini-Hochberg across the run
    method: TestMethod
    sen_slope: float | None = None
    intercept: float | None = None
    is_worsening: bool = False
    is_significant: bool = False


class EventCandidate(InternalModel):
    event_key: str
    scope: Scope
    subject_id: str
    anti_pattern_type: str
    catalog: str
    start_release: str
    end_release: str
    n_releases: int
    low_confidence_releases: tuple[str, ...] = ()
    trends: tuple[TrendResult, ...]
    trend_strength: float
