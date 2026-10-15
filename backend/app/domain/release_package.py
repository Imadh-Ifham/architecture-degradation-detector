"""ReleasePackageV1.1: one validated release, sent by C2 to C3 (plan Section 3.1).

Keeps the v2 field names (ADR 0003, R1). ``layer``, ``datastore_access`` and ``delegation`` are
the optional v3 additions; when they are missing, the detectors that need them are skipped.

Shape errors keep pydantic's error types. The two semantic rules raise an error whose type is
the C3 reason code, so ingestion can report it without parsing message text. Self-loops and
duplicate edges are valid here: ingestion drops and collapses them during normalisation.
"""

import datetime as dt
from collections import Counter
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import AliasChoices, AwareDatetime, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from app.domain.boundary import BoundaryModel, NonEmptyStr

SCHEMA_VERSION = "1.1.0"

DUPLICATE_ELEMENT_ID = "DUPLICATE_ELEMENT_ID"
DANGLING_DEPENDENCY = "DANGLING_DEPENDENCY"


class ArchitectureStyle(StrEnum):
    MONOLITH = "monolith"
    MICROSERVICES = "microservices"
    LAYERED = "layered"
    EVENT_DRIVEN = "event-driven"
    GENERIC = "generic"


class Element(BoundaryModel):
    id: NonEmptyStr
    name: str | None = None
    kind: str | None = None
    size: Annotated[float, Field(ge=0)] | None = None
    size_unit: str | None = None
    aliases: list[str] = Field(default_factory=list)
    layer: str | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class Dependency(BoundaryModel):
    from_: NonEmptyStr = Field(alias="from")
    to: NonEmptyStr
    types: list[str] = Field(default_factory=list)
    count: int = Field(default=1, ge=1)


class DatastoreAccess(BoundaryModel):
    element: NonEmptyStr
    datastore: NonEmptyStr
    mode: str | None = None


class IntentEntry(BoundaryModel):
    intent_id: NonEmptyStr
    element: str | None = None
    source_type: NonEmptyStr
    # `adr_ref` is the deprecated v1.0 name of `ref`.
    ref: str | None = Field(default=None, validation_alias=AliasChoices("ref", "adr_ref"))
    decision: str
    decision_kind: str | None = None
    date: dt.date | None = None


class Provenance(BoundaryModel):
    c1_model_ref: str | None = None
    c2_validation_ref: str | None = None


class ReleasePackageV1(BoundaryModel):
    model_config = ConfigDict(title="ReleasePackageV1.1")

    schema_version: str = Field(pattern=r"^1\.\d+\.\d+$")
    system_id: NonEmptyStr
    release_id: NonEmptyStr
    released_at: AwareDatetime
    architecture_style: ArchitectureStyle = ArchitectureStyle.GENERIC
    granularity: NonEmptyStr
    elements: list[Element] = Field(min_length=1)
    dependencies: list[Dependency] = Field(default_factory=list)
    datastore_access: list[DatastoreAccess] | None = None
    # Item shape is not agreed with C1 yet, so items are accepted and stored as supplied.
    delegation: list[dict[str, Any]] | None = None
    intent: list[IntentEntry] = Field(default_factory=list)
    validation_confidence: float = Field(ge=0, le=1)
    provenance: Provenance = Field(default_factory=Provenance)

    @model_validator(mode="after")
    def _check_element_references(self) -> Self:
        counts = Counter(element.id for element in self.elements)
        duplicates = sorted(element_id for element_id, n in counts.items() if n > 1)
        if duplicates:
            raise PydanticCustomError(
                DUPLICATE_ELEMENT_ID,
                "element ids must be unique; duplicated: {ids}",
                {"ids": ", ".join(duplicates)},
            )
        endpoints = {end for edge in self.dependencies for end in (edge.from_, edge.to)}
        dangling = sorted(endpoints - counts.keys())
        if dangling:
            raise PydanticCustomError(
                DANGLING_DEPENDENCY,
                "dependency endpoints must be elements of the release; unknown: {ids}",
                {"ids": ", ".join(dangling)},
            )
        return self
