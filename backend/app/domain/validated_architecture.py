"""Validated architecture domain model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    The contract architecture validation hands to degradation detection: the
    architecture of one release as a graph, with each validation verdict
    carried on the relationship it describes.

    The verdict travels on the edge on purpose. A flat findings list alongside
    a topology would have to be joined back onto it by the consumer, and a join
    is a place where two sides can disagree about what the topology was.

    `to_node_link()` emits the node-link structure directly, with the edge list
    under the key "links". That key is written here by hand rather than taken
    from a library default: NetworkX 3.6 changed its default from "links" to
    "edges". Consumers must read it with
    `nx.node_link_graph(document, edges="links")`.

    **How a mismatch fails was measured rather than assumed, and it is not
    what this docstring used to say.** It claimed the mismatch does not raise
    and silently yields a graph with no edges. On the installed NetworkX
    (3.7) that is false: reading a "links" document as "edges" raises
    `KeyError`, the reverse raises, and so does a consumer who passes nothing
    and takes the default. The silent empty graph belongs to the 3.4-to-3.6
    transition and is no longer the failure here - which is better news, since
    an immediate error in the consumer's own call is worth more than a
    plausible empty answer computed over for weeks. The keyword stays
    mandatory either way, because the library's default is "edges" and this
    document is written under "links".

    Schema 1.1.0 adds six fields the consuming component asked for after
    loading the committed 1.0.0 fixture into its own ingestion: when the
    release happened, which git field said so, an ordering key that does not
    depend on dates at all, a reference to the model this was computed from,
    and per-element size. Every one is additive; the single removal is
    `validation_confidence`'s default, which is explained on the field.

    Schema 1.2.0 adds two fields to each edge, both additive, and a consumer
    that ignores either reads exactly what it read before.

    `route` is whether the finding was published or held for an architect. It
    was not derivable from anything already published - the bucket says what
    was concluded, not what happens to the conclusion - and a screen counting
    held-back facts off the bucket reported none, for every run.

    `evidence_hash` names the sealed package the verdict was reached from. It
    is what joins an edge back to the request that produced it, so a reader
    can be shown the model's own sentences about a contradiction instead of a
    bucket name, and it is what a re-run has to reproduce for two verdicts to
    be comparable.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


SCHEMA_VERSION = "1.2.0"
GENERATOR_NAME = "architecture_validation"
GENERATOR_VERSION = "0.1.0"

NODE_LINK_EDGE_KEY = "links"


class ValidationBucket(StrEnum):
    """What validation concluded about one relationship.

    `UNCOVERED` is a finding rather than a gap in the output: the architecture
    has a dependency that nothing in the recorded intent speaks to. It is
    reached without calling a model at all, because there is no decision to
    reason about.
    """

    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    AMBIGUOUS = "ambiguous"
    UNCOVERED = "uncovered"
    CONVENTION_DEVIATION = "convention_deviation"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NEEDS_REVIEW = "needs_review"


class RunMode(StrEnum):
    """Whether the run validated documented intent or reconstructed it.

    Published so a consumer can weight the result honestly. A reconstruction
    run reasoned against decisions mined from the repository's own history
    rather than against decisions somebody wrote down.
    """

    ADR_BACKED = "adr_backed"
    RECONSTRUCTION = "reconstruction"


class ReleaseDateSource(StrEnum):
    """Which field a release date was read from.

    Published beside the date rather than kept in a log, because the three
    differ in ways that change an ordering. An annotated tag's own date is
    when the release was cut. A commit's author date is when the work was
    written and survives history being rewritten. A caller-supplied date is
    whatever a person said.

    The committer date is deliberately absent. It is rewritten by every
    rebase, cherry-pick and amend, so on a tidied history it reads as the day
    somebody last replayed the commit - which looks exactly like a release
    that happened today.
    """

    TAGGER = "tagger"
    AUTHOR = "author"
    CALLER = "caller"


class SizeUnitConflict(ValueError):
    """Two elements of one release measure size in different units.

    Refused rather than published. The consumer's size trend compares one
    release against the next, and a series that is `loc` in one place and
    `bytes` in another is a graph of nothing - with no error anywhere, because
    both are numbers.
    """

    def __init__(self, units: tuple[str, ...], release_id: str) -> None:
        super().__init__(
            f"Release '{release_id}' measures element size in more than one "
            f"unit: {', '.join(units)}. A size trend across mixed units "
            "compares nothing, so the release is not published."
        )
        self.units = units
        self.release_id = release_id


@dataclass(frozen=True)
class ValidationRollup:
    """Per-element counts, so a consumer can weight an element without
    walking every edge attached to it."""

    confirmed: int = 0
    contradicted: int = 0
    uncovered: int = 0
    needs_review: int = 0

    def to_dict(self) -> dict:
        return {
            "confirmed": self.confirmed,
            "contradicted": self.contradicted,
            "uncovered": self.uncovered,
            "needs_review": self.needs_review,
        }


@dataclass(frozen=True)
class ValidatedNode:
    """One architectural element, with its validation rollup.

    `canonical` is this component's own normalised identity, and it is what a
    consumer should follow an element by across releases. `id` is recovery's
    identifier: it is stable across the releases on record, but the derivation
    belongs to another component and is not a hash of the name or of the path,
    so resting a history on it would be resting on a coincidence.

    `size` is passed through from recovery and never computed here. This
    component does not read source code, so a size it produced would be the
    one number in the output with no provenance. `None` means recovery did not
    supply one, and stays `None` rather than becoming zero.
    """

    id: str
    name: str
    kind: str
    rollup: ValidationRollup
    canonical: str = ""
    size: float | None = None
    size_unit: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "canonical": self.canonical or self.name,
            "name": self.name,
            "kind": self.kind,
            "size": self.size,
            "size_unit": self.size_unit,
            "validation_rollup": self.rollup.to_dict(),
        }


@dataclass(frozen=True)
class ValidatedEdge:
    """One validated relationship.

    `governing_decision` is the decision that applied *at this release*, which
    is not necessarily the newest decision about this relationship. A
    superseded decision must never appear here.

    `model_calls` is published so a reader can see which verdicts cost a model
    call and which were settled by deterministic code - zero is the expected
    value for an uncovered or ambiguous relationship.

    `produced_by`, `verification_outcome` and `arbiter_agreement` travel for
    the same reason. An edge decided without a model and an edge nothing
    audited are both capped before they reach a consumer, so one that ignores
    them is not wrong - but a degradation study that averages a rule-only
    verdict with a three-judge one is averaging two different things.

    `route` is whether this edge was published or held for a person, and it
    is here because it could not be worked out from anything else that is.
    The bucket is what was concluded and the route is what happens to the
    conclusion; they are two axes, and a reader with only the first of them
    counted the facts awaiting an architect as zero.

    `evidence_hash` names the sealed evidence package this verdict was
    reached from. It is the identifier the model request was keyed on, so it
    is what joins a published edge back to the exact question that produced
    it - and it is the reason a reader can be shown the model's own words
    about a contradiction rather than a bucket name. It is also the thing a
    second run has to reproduce for the verdict to be comparable, which is
    worth publishing to a consumer on its own account.
    """

    fact_id: str
    source_id: str
    target_id: str
    relationship: str
    bucket: ValidationBucket
    confidence: float
    governing_decision: str | None
    evidence_refs: tuple[str, ...]
    source_tier: str | None
    model_calls: int
    produced_by: str = ""
    verification_outcome: str | None = None
    arbiter_agreement: str | None = None
    route: str = ""
    evidence_hash: str = ""
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "source": self.source_id,
            "target": self.target_id,
            "relationship": self.relationship,
            "bucket": self.bucket,
            "confidence": self.confidence,
            "governing_decision": self.governing_decision,
            "evidence_refs": list(self.evidence_refs),
            "source_tier": self.source_tier,
            "model_calls": self.model_calls,
            "produced_by": self.produced_by,
            "verification_outcome": self.verification_outcome,
            "arbiter_agreement": self.arbiter_agreement,
            "route": self.route,
            "evidence_hash": self.evidence_hash,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class ValidationRunStamp:
    """What produced this document.

    Every field here exists so that a result found in six months can be
    reproduced or discarded on evidence rather than on memory. A verdict with
    no model id and no prompt version is not a research result; it is an
    anecdote.
    """

    run_id: str
    generated_at: datetime
    mode: RunMode
    reasoner_model: str | None
    verifier_model: str | None
    prompt_versions: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at.isoformat(),
            "mode": self.mode,
            "reasoner_model": self.reasoner_model,
            "verifier_model": self.verifier_model,
            "prompt_versions": list(self.prompt_versions),
        }


@dataclass(frozen=True)
class ValidatedArchitectureGraph:
    """One release of one repository, validated.

    This is the whole handover. Nothing else crosses the boundary.

    `validation_confidence` has no default, deliberately and at a consumer's
    request. It gates a release downstream - below a threshold the release is
    excluded from the whole analysis - so a document built without setting it
    would publish `0.0` and silently drop the release with no error anywhere.
    A required field turns that into a `TypeError` at the point of the
    mistake.

    `released_at` may be `None` and travels as `None`. When no tag date and no
    caller supplied one, nothing is invented: a plausible wrong date orders a
    timeline wrongly and cannot be told apart from a right one.

    `release_order_key` is the ordering this component already computes, and
    it does not depend on dates at all. Both are published because they fail
    differently - when a date order and a version order disagree, that is a
    back-ported release rather than a bug, and one field alone cannot see it.
    """

    repository_id: str
    release_id: str
    architecture_style: str
    nodes: tuple[ValidatedNode, ...]
    edges: tuple[ValidatedEdge, ...]
    stamp: ValidationRunStamp
    validation_confidence: float
    architecture_style_source: str = ""
    released_at: datetime | None = None
    released_at_source: str | None = None
    release_order_key: tuple[int, ...] = ()
    c1_model_ref: str = ""
    summary: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Refuse a document that cannot be read as the contract claims.

        Both checks are here rather than in the publisher because a graph in
        either state must not be constructible at all - not out of the
        publisher, not out of a replay, not hand-built in a test.
        """

        if not 0.0 <= self.validation_confidence <= 1.0:
            raise ValueError(
                f"validation_confidence is {self.validation_confidence}, and "
                "the contract bounds it to 0..1. A consumer gates a release "
                "on this number, so a value outside the range fails in their "
                "code rather than here."
            )

        units = tuple(
            sorted({node.size_unit for node in self.nodes if node.size_unit})
        )
        if len(units) > 1:
            raise SizeUnitConflict(units, self.release_id)

    @property
    def size_unit(self) -> str | None:
        """The one unit this release measures size in, if it measures any."""

        return next((node.size_unit for node in self.nodes if node.size_unit), None)

    def to_node_link(self) -> dict:
        """Emit the node-link document consumers read.

        The edge list is written under "links" (see the module docstring).
        """

        return {
            "directed": True,
            "multigraph": False,
            "graph": {
                "schema_version": SCHEMA_VERSION,
                "generator": {
                    "name": GENERATOR_NAME,
                    "version": GENERATOR_VERSION,
                },
                "repository_id": self.repository_id,
                "release_id": self.release_id,
                "released_at": (
                    self.released_at.isoformat() if self.released_at else None
                ),
                "released_at_source": self.released_at_source,
                "release_order_key": list(self.release_order_key),
                "c1_model_ref": self.c1_model_ref,
                "architecture_style": self.architecture_style,
                "architecture_style_source": self.architecture_style_source,
                "validation_confidence": self.validation_confidence,
                "run": self.stamp.to_dict(),
                "summary": dict(self.summary),
            },
            "nodes": [node.to_dict() for node in self.nodes],
            NODE_LINK_EDGE_KEY: [edge.to_dict() for edge in self.edges],
        }
