"""CanonicalRelease: one release package after M1 normalisation (plan M1, step 3).

Every later C3 module reads releases in this form, never as raw C2 JSON. The model lives in the
domain layer, not in the component, because it crosses the ``ReleaseRepository`` port: the
PostgreSQL adapter stores and returns it, and infrastructure may not import components
(INSTRUCTIONS §7.1).

Unlike the boundary contracts these models are strict (``extra="forbid"``) and immutable: C3
builds them itself, so an unknown field is our own mistake.
"""

import datetime as dt
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.domain.release_package import ArchitectureStyle


class GateStatus(StrEnum):
    """Validation-confidence gate [D-07]."""

    ACCEPTED = "ACCEPTED"
    DOWNWEIGHTED = "DOWNWEIGHTED"  # included in the timeline, listed on events
    EXCLUDED = "EXCLUDED"  # stored, but not in the timeline


class ReleaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ElementSnapshot(ReleaseModel):
    element_id: str
    name: str
    kind: str
    size: float | None = None
    size_unit: str | None = None
    aliases: tuple[str, ...] = ()
    layer: str | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)  # C1 metrics, "c1." prefix
    extra: dict[str, Any] = Field(default_factory=dict)


class DependencyEdge(ReleaseModel):
    from_id: str
    to_id: str
    types: tuple[str, ...] = ()
    count: int = Field(ge=1)


class IntentEntry(ReleaseModel):
    intent_id: str
    element_id: str | None = None
    source_type: str
    ref: str | None = None
    decision: str
    decision_kind: str | None = None
    date: dt.date | None = None


class DatastoreAccess(ReleaseModel):
    element_id: str
    datastore: str
    mode: str | None = None


class CanonicalRelease(ReleaseModel):
    system_id: str
    release_id: str
    released_at: AwareDatetime
    architecture_style: ArchitectureStyle
    granularity: str
    validation_confidence: float
    gate_status: GateStatus
    package_hash: str
    elements: tuple[ElementSnapshot, ...]
    dependencies: tuple[DependencyEdge, ...] = ()
    intent: tuple[IntentEntry, ...] = ()
    # None means "not supplied by C2", which is different from an empty tuple.
    datastore_access: tuple[DatastoreAccess, ...] | None = None
    delegation: tuple[dict[str, Any], ...] | None = None
    c1_model_ref: str | None = None
    c2_validation_ref: str | None = None
