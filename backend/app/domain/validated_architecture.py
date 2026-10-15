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
    "edges", and a mismatch between producer and consumer does not raise - it
    silently yields a graph with no edges at all. Consumers should read it with
    `nx.node_link_graph(document, edges="links")`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


SCHEMA_VERSION = "1.0.0"
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
    """One architectural element, with its validation rollup."""

    id: str
    name: str
    kind: str
    rollup: ValidationRollup

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
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
    """

    repository_id: str
    release_id: str
    architecture_style: str
    nodes: tuple[ValidatedNode, ...]
    edges: tuple[ValidatedEdge, ...]
    stamp: ValidationRunStamp
    validation_confidence: float = 0.0

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
                "architecture_style": self.architecture_style,
                "validation_confidence": self.validation_confidence,
                "run": self.stamp.to_dict(),
            },
            "nodes": [node.to_dict() for node in self.nodes],
            NODE_LINK_EDGE_KEY: [edge.to_dict() for edge in self.edges],
        }
