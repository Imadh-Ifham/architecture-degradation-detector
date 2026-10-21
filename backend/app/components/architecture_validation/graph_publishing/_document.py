"""Building the published document.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    One completed run and one recovered architecture in, one
    `ValidatedArchitectureGraph` out.

    A pure function, kept apart from the service, because this is where a
    field gets dropped silently and the filesystem has nothing to do with it.
    Every assertion about the shape of the handover can then be made without
    writing a file, starting a database or running a pipeline.

    Nothing here recomputes a number that already exists. Every figure is
    carried from the stage that produced it: a publisher that re-derived a
    count would be a second implementation of that count, and the two would
    disagree on exactly the run somebody was looking at. The one thing it does
    compute is the per-element rollup, which exists nowhere else and is a
    count over the edges of this same document.
"""

from app.domain.recovered_architecture import ArchitectureElement, RecoveredArchitecture
from app.domain.validated_architecture import (
    RunMode,
    ValidatedArchitectureGraph,
    ValidatedEdge,
    ValidatedNode,
    ValidationBucket,
    ValidationRollup,
    ValidationRunStamp,
)

from .._identity import canonical_name
from .._release import release_sort_key
from ..models import ClassifiedFact, ValidationRunResult

ROLLUP_BUCKETS = {
    ValidationBucket.CONFIRMED: "confirmed",
    ValidationBucket.CONTRADICTED: "contradicted",
    ValidationBucket.UNCOVERED: "uncovered",
    ValidationBucket.NEEDS_REVIEW: "needs_review",
}
"""Which buckets the per-element rollup counts, and it is four of seven.

The rollup is a consumer's shortcut for weighting an element without walking
its edges, and the shape was agreed at four counters. The three that are
missing - ambiguous, insufficient evidence, convention deviation - are all
*refusals to assert*, so an element whose every edge refused is correctly
described by four zeroes rather than misdescribed by a fifth counter nobody
reads. The full bucket is on every edge for anyone who wants it.
"""

RECONSTRUCTED_MODES = {"reconstructed", "combined"}
"""Decision modes that make a run a reconstruction rather than ADR-backed.

`combined` counts as a reconstruction on purpose. A run that mixed written
decisions with mined ones cannot claim the stronger label for the whole of
itself, and the per-fact `source_tier` is where the difference is visible.
"""


def build(
    run: ValidationRunResult,
    architecture: RecoveredArchitecture,
    summary: dict,
) -> ValidatedArchitectureGraph:
    """Assemble the document this component hands over."""

    edges = tuple(_edge(fact) for fact in run.facts)

    return ValidatedArchitectureGraph(
        repository_id=run.repository_id,
        release_id=run.release_id,
        architecture_style=run.style_resolved or "",
        architecture_style_source=run.style_source or "",
        nodes=tuple(_node(element, edges) for element in architecture.elements),
        edges=edges,
        stamp=_stamp(run),
        validation_confidence=run.validation_confidence,
        released_at=run.released_at,
        released_at_source=_date_source(run),
        release_order_key=release_sort_key(run.release_id),
        c1_model_ref=_model_ref(architecture),
        summary=summary,
    )


def _edge(fact: ClassifiedFact) -> ValidatedEdge:
    """One classified fact, as the relationship it describes.

    The endpoints and the relationship are read off the classified fact rather
    than looked up in the architecture: the alternative is joining two lists
    by `fact_id` on the way out, which is the join that putting the verdict on
    the edge exists to avoid.
    """

    return ValidatedEdge(
        fact_id=fact.fact_id,
        source_id=fact.source_element_id,
        target_id=fact.target_element_id,
        relationship=fact.relationship,
        bucket=fact.bucket,
        confidence=fact.confidence,
        governing_decision=fact.governing_decision,
        evidence_refs=fact.evidence_refs,
        source_tier=fact.source_tier,
        model_calls=fact.model_calls,
        produced_by=fact.produced_by,
        verification_outcome=fact.verification_outcome,
        arbiter_agreement=fact.arbiter_agreement,
        route=fact.route,
        evidence_hash=fact.verdict.evidence_hash if fact.verdict else "",
        confidence_terms=dict(fact.score_trace.terms),
        confidence_ceiling=fact.score_trace.ceiling_applied,
        confidence_maximum=fact.score_trace.maximum,
        attributes=dict(fact.attributes),
    )


def _node(
    element: ArchitectureElement, edges: tuple[ValidatedEdge, ...]
) -> ValidatedNode:
    """One element, with the counts of the edges leaving it.

    Counted over outgoing edges only. A dependency is a statement about its
    subject - *this element reaches that one, against the recorded intent* -
    so counting it at both ends would report one finding twice and make a
    release's rollups sum to double its facts.

    Every element appears, including one with no edges at all. The new service
    at a release that nothing yet points at is an observation, and dropping
    unconnected elements would delete it.
    """

    counts = dict.fromkeys(ROLLUP_BUCKETS.values(), 0)
    for edge in edges:
        if edge.source_id != element.id:
            continue
        counter = ROLLUP_BUCKETS.get(edge.bucket)
        if counter is not None:
            counts[counter] += 1

    return ValidatedNode(
        id=element.id,
        name=element.name,
        kind=element.kind,
        canonical=canonical_name(element.name),
        size=element.size,
        size_unit=element.size_unit,
        rollup=ValidationRollup(**counts),
    )


def _stamp(run: ValidationRunResult) -> ValidationRunStamp:
    """What produced every verdict in this document.

    The models are the ones that answered, which the run carries, not the ones
    configured. A result that cannot say what produced it cannot be reproduced
    or discarded on evidence.
    """

    return ValidationRunStamp(
        run_id=run.run_id,
        generated_at=run.generated_at,
        mode=(
            RunMode.RECONSTRUCTION
            if run.decision_mode in RECONSTRUCTED_MODES
            else RunMode.ADR_BACKED
        ),
        reasoner_model=run.reasoner_model,
        verifier_model=run.verifier_model,
        prompt_versions=run.prompt_versions,
    )


def _date_source(run: ValidationRunResult) -> str | None:
    """Which field the release date came from, or nothing when it has none.

    The run carries the date and the caller carries how it was obtained, so
    this reports `caller` for any date that reached the run and `None` for a
    release whose date could not be established. The finer distinction between
    a tag's own date and a commit's author date is made by the adapter that
    read git, and travels on the request.
    """

    if run.released_at is None:
        return None
    return run.released_at_source


def _model_ref(architecture: RecoveredArchitecture) -> str:
    """What this was computed from, in a form that means the same elsewhere.

    `source_reference` is a path on the machine that ran the scan: it
    identifies the input perfectly there and nowhere else. A consumer pointing
    a degradation event back at the model it came from needs something
    portable, so the commit travels when recovery reported one and the path
    only when it did not.
    """

    provenance = architecture.provenance
    return provenance.source_commit or provenance.source_reference
