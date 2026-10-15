"""Models of the synthetic stub: its output files and the ground-truth manifest.

The manifest is true by construction: it is written from the scenario definition, never from
the output of the code under test. Evaluation (T-14) compares what C3 reports against it.

How to read it when scoring events:

* ``expected_events`` must be reported (unless ``required`` is false).
* ``expected_non_events`` must not be reported, although a fixed threshold would flag them.
* ``collateral`` elements really do change because of a planted scenario (a service that starts
  calling the hub gains an outgoing dependency). An event on one of them, or a second event of
  another type on the subject of an expected event, is neither a hit nor a false alarm.
* An event on any other element is a false alarm.
"""

from typing import Literal

from pydantic import AwareDatetime

from app.components.degradation_detection.models import InternalModel
from app.domain.canonical_release import GateStatus
from app.domain.degradation_event import Lifecycle, Scope, Worsening

DEFAULT_SEED = 20261013
GROUND_TRUTH_FILE = "ground_truth.yaml"


class ReleaseTruth(InternalModel):
    release_id: str
    file: str
    released_at: AwareDatetime
    validation_confidence: float
    gate_status: GateStatus


class RejectedPackage(InternalModel):
    release_id: str
    file: str
    reason: str


class RenameTruth(InternalModel):
    from_id: str
    to_id: str
    at_release: str


class InstanceTruth(InternalModel):
    """One planted anti-pattern instance and its members in every release where it exists."""

    scenario: str
    anti_pattern_type: str
    first_release: str
    members_by_release: dict[str, tuple[str, ...]]


class ExpectedEvent(InternalModel):
    scenario: str
    scope: Scope
    # Any one of these types is correct (S8 depends on a presence threshold).
    anti_pattern_types: tuple[str, ...]
    element_id: str | None = None  # id in the last release
    members: tuple[str, ...] = ()  # ids in the last release
    lifecycle: Lifecycle | None = None
    required: bool = True
    description: str


class ExpectedNonEvent(InternalModel):
    scenario: str
    element_id: str
    static_flag: str  # what a fixed-threshold baseline would flag at the last release
    description: str


class TrendTruth(InternalModel):
    """A series that worsens by construction and must come out significant."""

    scenario: str
    scope: Scope
    subject: str  # element id in the last release, the scenario id of an instance, or the system
    metric: str
    worsening: Worsening


class FlatTruth(InternalModel):
    """A series with no trend by construction; it must not come out significant."""

    scenario: str
    scope: Scope
    subject: str
    metric: str


class Collateral(InternalModel):
    element_id: str
    scenario: str
    description: str


class SeriesLengths(InternalModel):
    element: int
    system: int
    instance: dict[str, int]  # scenario id -> number of releases the instance exists in


class GroundTruth(InternalModel):
    schema_version: str = "1.0.0"
    system_id: str
    seed: int
    architecture_style: str
    granularity: str
    releases: tuple[ReleaseTruth, ...]
    rejected: tuple[RejectedPackage, ...]
    renames: tuple[RenameTruth, ...]
    instances: tuple[InstanceTruth, ...]
    expected_events: tuple[ExpectedEvent, ...]
    expected_non_events: tuple[ExpectedNonEvent, ...]
    expected_trends: tuple[TrendTruth, ...]
    expected_flat: tuple[FlatTruth, ...]
    collateral: tuple[Collateral, ...]
    series_lengths: SeriesLengths


class SeriesFixture(InternalModel):
    """A bare series with a known answer, for the M4 statistics tests."""

    name: str
    description: str
    time: tuple[int, ...]
    values: tuple[float | None, ...]  # null stays null
    expected_trend: Literal["increasing", "decreasing", "none"]
    planted_slope: float | None = None  # per time unit, when the series is built on a line


class StubOutput(InternalModel):
    """Every generated file as text, keyed by file name. Writing them is the caller's job."""

    seed: int
    system_files: dict[str, str]
    series_files: dict[str, str]
    ground_truth: GroundTruth
