"""DegradationEventV2: one anti-pattern that is getting worse, sent by C3 to C4 (plan Section 3.2).

No field here expresses severity, priority or impact: C4 owns ranking, and a guardrail test
checks the generated schema. ``trend_strength`` is the largest |tau| among the affected metrics
and measures the strength of the statistical evidence, not how bad the degradation is.
"""

from enum import StrEnum
from typing import Any, Self

from pydantic import ConfigDict, Field, model_validator

from app.domain.boundary import BoundaryModel, NonEmptyStr, Sha256
from app.domain.release_package import ArchitectureStyle

SCHEMA_VERSION = "2.0.0"


class Scope(StrEnum):
    ELEMENT = "ELEMENT"
    INSTANCE = "INSTANCE"
    SYSTEM = "SYSTEM"


class Lifecycle(StrEnum):
    INTRODUCED = "introduced"
    GROWING = "growing"
    PERSISTENT = "persistent"
    RESOLVED = "resolved"


class Worsening(StrEnum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


class TestMethod(StrEnum):
    __test__ = False  # not a pytest test class, despite the name

    EXACT = "EXACT"
    PERMUTATION = "PERMUTATION"
    NORMAL = "NORMAL"
    DEGENERATE = "DEGENERATE"


class TimeAxis(StrEnum):
    ORDINAL = "ordinal"
    DAYS = "days"


class ContextTag(StrEnum):
    GENUINE = "GENUINE"
    INTENTIONAL = "INTENTIONAL"
    UNCERTAIN = "UNCERTAIN"


class ContextStage(StrEnum):
    DISABLED = "DISABLED"
    DEFAULT = "DEFAULT"
    RULE = "RULE"
    LLM = "LLM"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    NEEDS_INVESTIGATION = "NEEDS_INVESTIGATION"


class Window(BoundaryModel):
    start_release: NonEmptyStr
    end_release: NonEmptyStr
    n_releases: int = Field(ge=1)
    low_confidence_releases: list[str] = Field(default_factory=list)


class SeriesValue(BoundaryModel):
    release_id: NonEmptyStr
    value: float | None


class AffectedMetric(BoundaryModel):
    metric: NonEmptyStr
    unit: str | None = None
    worsening: Worsening
    n: int = Field(ge=1)
    s: int
    tau: float = Field(ge=-1, le=1)
    p_value: float = Field(ge=0, le=1)
    q_value: float = Field(ge=0, le=1)
    test_method: TestMethod
    sen_slope: float | None
    time_axis: TimeAxis
    series: list[SeriesValue]


class Citation(BoundaryModel):
    passage_id: NonEmptyStr
    quote: str


class Context(BoundaryModel):
    tag: ContextTag
    stage: ContextStage
    rule_id: str | None = None
    justification: str | None = None
    # Passage shape is settled with M5 (post-PP1); always empty while context is disabled.
    retrieved: list[dict[str, Any]] = Field(default_factory=list)
    cited: list[Citation] = Field(default_factory=list)


class EventProvenance(BoundaryModel):
    c1_model_refs: list[str] = Field(default_factory=list)
    c2_validation_refs: list[str] = Field(default_factory=list)
    release_package_hashes: list[Sha256]
    config_hash: Sha256


class DegradationEventV2(BoundaryModel):
    model_config = ConfigDict(title="DegradationEventV2")

    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^2\.\d+\.\d+$")
    event_id: NonEmptyStr
    event_key: Sha256
    supersedes_event_id: str | None = None
    run_id: NonEmptyStr
    system_id: NonEmptyStr
    scope: Scope
    anti_pattern_type: NonEmptyStr
    catalog: NonEmptyStr
    architecture_style: ArchitectureStyle
    instance_id: str | None = None
    members: list[str] = Field(default_factory=list)
    element_id: str | None = None
    lineage_id: str | None = None
    lifecycle: Lifecycle | None = None
    window: Window
    affected_metrics: list[AffectedMetric] = Field(min_length=1)
    trend_strength: float = Field(ge=0, le=1)
    context: Context
    review_status: ReviewStatus = ReviewStatus.PENDING
    provenance: EventProvenance

    @model_validator(mode="after")
    def _check_subject_matches_scope(self) -> Self:
        if self.scope is Scope.ELEMENT and (self.element_id is None or self.lineage_id is None):
            raise ValueError("scope ELEMENT needs element_id and lineage_id")
        if self.scope is Scope.INSTANCE and (self.instance_id is None or not self.members):
            raise ValueError("scope INSTANCE needs instance_id and members")
        return self
