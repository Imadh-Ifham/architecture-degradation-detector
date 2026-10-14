"""Recovered architecture domain model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    The contract architecture recovery hands to architecture validation: the
    elements of one release, the relationships observed between them, and how
    good the evidence for each was.

    Two things about this shape are deliberate.

    Relationship labels stay as recovery reported them ("http", "grpc",
    "publishes"). They are not reduced to a canonical vocabulary here, because
    the reduction depends on the architectural style and belongs with the style
    adapters in validation. This file only guarantees the *shape*.

    `relationships` may legitimately be empty. Recovery currently reports links
    between files and components rather than between one element and another,
    so a release can arrive with elements and no edges at all. Validation
    detects that and derives the edges from the deployment manifests recovery
    has already located; see `derived_by` on each relationship.
"""

from dataclasses import dataclass, field
from enum import StrEnum


SCHEMA_VERSION = "1.0.0"


class ArchitectureStyle(StrEnum):
    """The architectural style a release was recovered as.

    `UNKNOWN` is a real answer and not a failure. A style that cannot be
    determined is normalised by the generic adapter, which keeps the structure
    and caps how confident any verdict about it may become. Guessing a style
    would be worse than admitting to none, because every downstream decision
    would inherit the guess without knowing it was one.
    """

    MICROSERVICES = "microservices"
    LAYERED = "layered"
    EVENT_DRIVEN = "event_driven"
    MONOLITH = "monolith"
    UNKNOWN = "unknown"


class EvidenceQuality(StrEnum):
    """How an element or relationship was established.

    `CONFIRMED` means an artifact names the thing - a manifest declares it.
    `INFERRED` means structure suggests it - a file sits under a directory.

    This is a category, never a probability. It is used as a ceiling on how
    strong a verdict may become, not as a factor in a confidence calculation,
    because turning two names into numbers would mean inventing the numbers.
    """

    CONFIRMED = "confirmed"
    INFERRED = "inferred"


class ElementKind(StrEnum):
    """What kind of architectural element this is.

    `CHANNEL` is a topic, queue or exchange. It is an element while an
    architecture is being read, and stops being one during normalisation: an
    event-driven publish-subscribe pair through a channel is one logical
    relationship between the two services, with the channel kept as an
    attribute of it.
    """

    SERVICE = "service"
    MODULE = "module"
    LAYER = "layer"
    DATASTORE = "datastore"
    CHANNEL = "channel"
    EXTERNAL = "external"


class DerivationMethod(StrEnum):
    """Who established a relationship, and from what.

    Recorded per relationship rather than per release because a single release
    can carry both kinds at once while recovery is still being built out.
    """

    RECOVERED = "recovered"
    DERIVED_FROM_DEPLOYMENT = "derived_from_deployment"


@dataclass(frozen=True)
class ArchitectureElement:
    """One element of the architecture at a release."""

    id: str
    name: str
    kind: ElementKind
    quality: EvidenceQuality
    source_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "quality": self.quality,
            "source_paths": list(self.source_paths),
        }


@dataclass(frozen=True)
class ArchitectureRelationship:
    """One observed relationship between two elements.

    `label` is whatever recovery called it, unreduced - the style adapter maps
    it into validation's canonical vocabulary. `attributes` carries everything
    style-specific, so this shape never has to grow a field per style.
    """

    source_id: str
    target_id: str
    label: str
    quality: EvidenceQuality
    derived_by: DerivationMethod
    source_paths: tuple[str, ...] = ()
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "label": self.label,
            "quality": self.quality,
            "derived_by": self.derived_by,
            "source_paths": list(self.source_paths),
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class RecoveryProvenance:
    """Where this architecture came from, so a run can be explained later.

    `source_schema_version` is the version recovery stamped on the document
    that produced this. It is kept because a validation result that cannot say
    which input version it was computed from cannot be reproduced.
    """

    reader: str
    source_schema_version: str
    source_reference: str

    def to_dict(self) -> dict:
        return {
            "reader": self.reader,
            "source_schema_version": self.source_schema_version,
            "source_reference": self.source_reference,
        }


@dataclass(frozen=True)
class RecoveredArchitecture:
    """One release of one repository, as recovery observed it.

    `release_id` is supplied by the caller that requested the run, not read
    from the recovery output: recovery identifies a release by commit, and
    commit hashes carry no order, which the validity intervals in the decision
    knowledge model require.

    `manifest_paths` are the deployment and infrastructure files recovery
    classified. They travel with the architecture rather than being looked up
    separately, so the derivation never has to guess repository layout and
    nothing between the reader and the derivation has to know what a manifest
    is.
    """

    repository_id: str
    release_id: str
    style: ArchitectureStyle
    elements: tuple[ArchitectureElement, ...]
    relationships: tuple[ArchitectureRelationship, ...]
    provenance: RecoveryProvenance
    manifest_paths: tuple[str, ...] = ()

    @property
    def has_element_relationships(self) -> bool:
        """Whether recovery supplied any element-to-element relationship.

        Validation derives the relationships itself when this is false, and
        stops doing so on its own once recovery reports them - so the
        derivation retires without a flag to remember or code to remove.
        """

        return len(self.relationships) > 0

    def element_by_id(self, element_id: str) -> ArchitectureElement | None:
        return next((e for e in self.elements if e.id == element_id), None)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "repository_id": self.repository_id,
            "release_id": self.release_id,
            "style": self.style,
            "elements": [item.to_dict() for item in self.elements],
            "relationships": [item.to_dict() for item in self.relationships],
            "manifest_paths": list(self.manifest_paths),
            "provenance": self.provenance.to_dict(),
        }
