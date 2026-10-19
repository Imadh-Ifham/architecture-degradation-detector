# Severity report domain model: the ranked, explained list of degradation events
# that degradation scoring (C4) produces for one release of one system.

import itertools
import math
from enum import StrEnum
from typing import Annotated, Self

from pydantic import ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from app.domain.boundary import BoundaryModel, NonEmptyStr
from app.domain.degradation_event import ContextTag, ReviewStatus, Scope

SCHEMA_VERSION = "1.1.0"

# Weights and contributions are sums of floats, so they are compared with a tolerance.
SUM_TOLERANCE = 1e-6

WEIGHTS_NOT_NORMALISED = "WEIGHTS_NOT_NORMALISED"
INACTIVE_DIMENSION_WEIGHTED = "INACTIVE_DIMENSION_WEIGHTED"
CONTRIBUTIONS_MISMATCH = "CONTRIBUTIONS_MISMATCH"
AUDIT_COUNTS_MISMATCH = "AUDIT_COUNTS_MISMATCH"
RANK_SEQUENCE_BROKEN = "RANK_SEQUENCE_BROKEN"
SEVERITY_ORDER_BROKEN = "SEVERITY_ORDER_BROKEN"
ACTIVE_DIMENSIONS_MISMATCH = "ACTIVE_DIMENSIONS_MISMATCH"
NORMALIZATION_BOUNDS_INVERTED = "NORMALIZATION_BOUNDS_INVERTED"

UnitInterval = Annotated[float, Field(ge=0, le=1)]


class Dimension(StrEnum):
    # The four severity criteria.
    BLAST_RADIUS = "blast_radius"
    HOTSPOT = "hotspot"
    ADR_VIOLATION = "adr_violation"
    PERSISTENCE = "persistence"


class ResolutionStatus(StrEnum):
    # How an event's elements were matched to graph nodes
    EXACT = "exact"
    PREFIX_FALLBACK = "prefix_fallback"


class EvidenceSource(StrEnum):
    # Where one evidence chunk of an explanation came from.
    METRIC = "metric"
    SUBGRAPH = "subgraph"
    COCHANGE = "cochange"
    ADR = "adr"
    COMMIT = "commit"


class QuarantineReason(StrEnum):
    # Why an event could not be scored at all. It is listed, never ranked.
    MALFORMED_PAYLOAD = "malformed_payload"
    UNRESOLVED_ELEMENT = "unresolved_element"


class SkipReason(StrEnum):
    # Why a valid event was deliberately left out of the ranking (C4-ADR-007).
    NOT_CONFIRMED = "not_confirmed"
    REJECTED = "rejected"
    INTENTIONAL = "intentional"
    SYSTEM_SCOPE_NOT_RANKABLE = "system_scope_not_rankable"
    SUPERSEDED = "superseded"


class NormalizationMode(StrEnum):
    # Which normaliser produced the [0, 1] values
    ROBUST_MINMAX = "robust_minmax"
    MINMAX_SMALL_N = "minmax_small_n"


class DataProvenance(StrEnum):
    # Whether the numbers come from hand-authored fixtures or from real data.
    # Printed on the report banner: a fixture result must never be read as a finding.
    FIXTURE = "fixture"
    FIXTURE_EVENTS_LIVE_HISTORY = "fixture-events+live-history"
    LIVE = "live"


class WeightsProvenance(StrEnum):
    # Who made the AHP pairwise judgements. Weights stay provisional until the supervisor
    # elicitation session has happened (CLAUDE.md §5.6).
    PROVISIONAL_AUTHOR_ELICITED = "provisional-author-elicited"
    SUPERVISOR_ELICITED = "supervisor-elicited"


class DimensionScore(BoundaryModel):
    # One criterion of one event: raw value, its normalised value and its weight.
    raw: float
    normalized: UnitInterval
    weight: UnitInterval
    features: dict[str, bool | float | None] = Field(default_factory=dict)
    active: bool = True

    @model_validator(mode="after")
    def _check_inactive_has_no_weight(self) -> Self:
        if not self.active and self.weight != 0:
            raise PydanticCustomError(
                INACTIVE_DIMENSION_WEIGHTED,
                "an inactive dimension must have weight 0, got {weight}",
                {"weight": self.weight},
            )
        return self


class Resolution(BoundaryModel):
    status: ResolutionStatus
    confidence: float = Field(gt=0, le=1)


class AuditSummary(BoundaryModel):
    # Claim-level faithfulness audit of one explanation

    claims_total: int = Field(ge=0)
    claims_grounded: int = Field(ge=0)
    claims_unsupported: int = Field(ge=0)
    claims_contradicted: int = Field(ge=0)
    groundedness: UnitInterval
    flagged: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_counts_add_up(self) -> Self:
        judged = self.claims_grounded + self.claims_unsupported + self.claims_contradicted
        expected = self.claims_grounded / self.claims_total if self.claims_total else 0.0
        if judged != self.claims_total or not math.isclose(
            self.groundedness, expected, abs_tol=SUM_TOLERANCE
        ):
            raise PydanticCustomError(
                AUDIT_COUNTS_MISMATCH,
                "grounded + unsupported + contradicted must equal claims_total, and "
                "groundedness must equal grounded / total",
            )
        return self


class EvidenceItem(BoundaryModel):
    id: Annotated[str, Field(pattern=r"^E[1-9]\d*$")]
    source: EvidenceSource
    text: NonEmptyStr
    provenance: NonEmptyStr


class SeverityRecord(BoundaryModel):
    # One ranked event.
    event_id: NonEmptyStr
    anti_pattern_type: NonEmptyStr
    scope: Scope
    review_status: ReviewStatus
    context_tag: ContextTag
    rank: int = Field(ge=1)
    severity: UnitInterval
    dimensions: dict[Dimension, DimensionScore]
    contributions: dict[Dimension, UnitInterval]
    resolution: Resolution
    explanation: str | None = None
    audit: AuditSummary | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_dimensions(self) -> Self:
        if set(self.dimensions) != set(Dimension) or set(self.contributions) != set(Dimension):
            raise PydanticCustomError(
                CONTRIBUTIONS_MISMATCH,
                "dimensions and contributions must each list all four dimensions",
            )
        active_weight = sum(d.weight for d in self.dimensions.values() if d.active)
        if not math.isclose(active_weight, 1.0, abs_tol=SUM_TOLERANCE):
            raise PydanticCustomError(
                WEIGHTS_NOT_NORMALISED,
                "weights of the active dimensions must sum to 1, got {total}",
                {"total": active_weight},
            )
        contribution_total = sum(self.contributions.values())
        inactive_contributes = any(
            self.contributions[name] != 0 for name, d in self.dimensions.items() if not d.active
        )
        if inactive_contributes or not (
            math.isclose(contribution_total, 1.0, abs_tol=SUM_TOLERANCE) or contribution_total == 0
        ):
            raise PydanticCustomError(
                CONTRIBUTIONS_MISMATCH,
                "contributions must sum to 1 (or all be 0), and an inactive dimension "
                "must contribute 0; got a total of {total}",
                {"total": contribution_total},
            )
        return self


class NormalizationBounds(BoundaryModel):
    lower: float
    upper: float

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.lower > self.upper:
            raise PydanticCustomError(
                NORMALIZATION_BOUNDS_INVERTED,
                "lower bound {lower} is above upper bound {upper}",
                {"lower": self.lower, "upper": self.upper},
            )
        return self


class QuarantinedEvent(BoundaryModel):
    # An event that could not be scored. `event_id` is None when the payload had none.
    event_id: str | None = None
    reason: QuarantineReason
    detail: str = ""


class SkippedEvent(BoundaryModel):
    event_id: NonEmptyStr
    reason: SkipReason


class SeverityReportV1(BoundaryModel):
    # The whole C4 output for one (system, release) run.

    model_config = ConfigDict(title="SeverityReportV1")

    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^1\.\d+\.\d+$")
    run_id: NonEmptyStr
    system_id: NonEmptyStr
    release_id: NonEmptyStr
    data_provenance: DataProvenance
    active_dimensions: list[Dimension] = Field(min_length=1)
    weights_version: NonEmptyStr
    weights_provenance: WeightsProvenance
    ahp_cr: float = Field(ge=0)
    normalization: NormalizationMode
    normalization_bounds: dict[str, NormalizationBounds] = Field(default_factory=dict)
    resolution_rate: UnitInterval
    records: list[SeverityRecord] = Field(default_factory=list)
    quarantined: list[QuarantinedEvent] = Field(default_factory=list)
    skipped: list[SkippedEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_ranking(self) -> Self:
        ranks = [record.rank for record in self.records]
        if ranks != list(range(1, len(self.records) + 1)):
            raise PydanticCustomError(
                RANK_SEQUENCE_BROKEN,
                "records must be ordered by rank 1..n with no gaps or repeats, got {ranks}",
                {"ranks": ranks},
            )
        severities = [record.severity for record in self.records]
        if any(later > earlier for earlier, later in itertools.pairwise(severities)):
            raise PydanticCustomError(
                SEVERITY_ORDER_BROKEN,
                "a lower rank must never have a higher severity",
            )
        declared = set(self.active_dimensions)
        for record in self.records:
            active = {name for name, d in record.dimensions.items() if d.active}
            if active != declared:
                raise PydanticCustomError(
                    ACTIVE_DIMENSIONS_MISMATCH,
                    "record {event_id} has active dimensions that differ from the report's",
                    {"event_id": record.event_id},
                )
        return self
