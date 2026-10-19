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

    Relationships must resolve. Every `source_id` and `target_id` has to name
    an element in the same architecture, and `RecoveredArchitecture` refuses
    to be constructed otherwise - see `IncoherentArchitecture` for why that is
    the one hard failure at this boundary.

    `relationships` may legitimately be empty. Recovery currently reports links
    between files and components rather than between one element and another,
    so a release can arrive with elements and no edges at all. Until recovery
    reports them, they are produced by a named stand-in in the recovery
    gateway and marked as such on each relationship; see `derived_by`.
    Validation itself does not read source code, so nothing inside the
    validation component derives them.
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


class IncoherentArchitecture(ValueError):
    """A relationship names an element the architecture does not contain.

    Raised from `RecoveredArchitecture`'s own constructor, so an architecture
    in this state cannot exist anywhere - not out of a reader, not out of a
    recorder, not hand-built in a test.

    This is deliberately the one hard failure on the input boundary, and the
    distinction it rests on is between *a word we do not know* and *a document
    that does not hold together*. An unrecognised relationship label is the
    first kind: it is absorbed, the original is kept, and the count is
    reported. An edge pointing at a missing node is the second kind. Absorbing
    it would put a relationship in the validated graph with nothing on one end,
    and every consumer after that would be working on a graph that cannot be
    drawn.
    """

    def __init__(self, missing: tuple[str, ...], release_id: str) -> None:
        named = ", ".join(missing)
        super().__init__(
            f"Architecture for release '{release_id}' has relationships naming "
            f"element(s) it does not contain: {named}."
        )
        self.missing = missing
        self.release_id = release_id


class StyleSource(StrEnum):
    """Who decided the architectural style.

    The style selects the adapter, and the adapter decides what every fact in
    the run looks like - so getting it from the wrong party quietly changes
    every verdict downstream. The architecture document gives recovery the job
    of detecting it, so recovery's answer is authoritative whenever there is
    one, and validation's own inference is a labelled fallback rather than a
    silent equal.

    Two values, because there are two parties. If an evaluation corpus ever
    needs a style forced by hand, that is a **third** labelled value, never an
    unlabelled override: a style nobody can trace is the thing this field
    exists to prevent.
    """

    C1 = "c1"
    INFERRED_BY_C2 = "inferred_by_c2"


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
    """One element of the architecture at a release.

    `size` and `size_unit` are recovery's measurement of the element, passed
    through untouched. Validation does not read source code, so a size
    produced here would be the one number in the output with no provenance.

    They travel as a pair or not at all. A number whose unit is unknown cannot
    be compared against the next release, which is the only thing a size is
    for.
    """

    id: str
    name: str
    kind: ElementKind
    quality: EvidenceQuality
    source_paths: tuple[str, ...] = ()
    size: float | None = None
    size_unit: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "quality": self.quality,
            "source_paths": list(self.source_paths),
            "size": self.size,
            "size_unit": self.size_unit,
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
    source_commit: str = ""
    """The commit recovery scanned, when it reported one.

    `source_reference` is a path on the machine that ran the scan, which
    identifies the input perfectly there and nowhere else. A consumer pointing
    a finding back at the model it came from needs something portable, and a
    commit means the same thing everywhere.
    """

    def to_dict(self) -> dict:
        return {
            "reader": self.reader,
            "source_schema_version": self.source_schema_version,
            "source_reference": self.source_reference,
            "source_commit": self.source_commit,
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
    separately, so the gateway's stand-in never has to guess repository layout
    and nothing between the reader and the stand-in has to know what a
    manifest is.

    `style` and `style_source` are read together and neither is useful alone.
    `style_source` of `c1` means recovery answered and the answer stands, even
    when the answer is `unknown`. `inferred_by_c2` means recovery said nothing
    and `style` is a placeholder the normaliser replaces with its own
    inference. The field has no default: an architecture that cannot say where
    its style came from is then impossible to construct rather than possible
    to construct and easy to forget about.
    """

    repository_id: str
    release_id: str
    style: ArchitectureStyle
    style_source: StyleSource
    elements: tuple[ArchitectureElement, ...]
    relationships: tuple[ArchitectureRelationship, ...]
    provenance: RecoveryProvenance
    manifest_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Refuse an architecture whose relationships do not resolve.

        Checked here rather than in each reader because there are three
        readers and a recorder, and the one that forgets is the one that
        produces the broken graph. Frozen dataclasses run this once, at
        construction, and it is a single pass over the relationships against a
        set of ids.
        """

        known = {element.id for element in self.elements}
        missing = tuple(
            sorted(
                {
                    end
                    for relationship in self.relationships
                    for end in (relationship.source_id, relationship.target_id)
                    if end not in known
                }
            )
        )
        if missing:
            raise IncoherentArchitecture(missing, self.release_id)

    @property
    def has_element_relationships(self) -> bool:
        """Whether this architecture carries any element-to-element relationship.

        False means there is nothing for validation to validate, and that is
        reported rather than filled in. The gateway's stand-in fills the gap
        while recovery's own extraction is unfinished, and becomes a no-op the
        moment recovery reports them - so it retires without a flag to
        remember or code to remove.
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
            "style_source": self.style_source,
            "elements": [item.to_dict() for item in self.elements],
            "relationships": [item.to_dict() for item in self.relationships],
            "manifest_paths": list(self.manifest_paths),
            "provenance": self.provenance.to_dict(),
        }
