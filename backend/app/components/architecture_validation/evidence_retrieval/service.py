"""Evidence retrieval service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Assembles exactly what the model is allowed to reason from, for one fact.

    This is the fence around the model, and the fence is the argument. The
    model never reads the repository - it reads one package - and that single
    property is what makes three other things true: a citation can be checked
    against a finite set, two runs over one release ask an identical question,
    and the cost of a run is decided here rather than by whatever a file
    happens to contain.

    Every item carries three things. A `ref`, because the model must name what
    it used and the guard checks those names against this package. A `role`,
    because a replaced decision has to be presented as context rather than as
    a rule - without that the model may cite the very decision this component
    exists to reject. And a `span` where one exists, because evidence a reader
    can be shown is worth more than evidence they are told about.

    Nothing here ranks or scores. Items are selected by identity - this fact,
    this decision - which is the retrieval hypothesis the research measures
    against keyword and embedding baselines.

    Research module: M3.
"""

import hashlib
import json

from app.domain.recovered_architecture import RecoveredArchitecture

from .._identity import canonical_name
from ..models import (
    EvidenceItem,
    EvidencePackage,
    EvidenceRole,
    ObservedFact,
    Resolution,
    Span,
)
from ..ports import SourceArtifactReader
from ._budget import MAX_ITEMS, fit
from ._neighbourhood import neighbours

HASH_LENGTH = 16


class EvidenceRetrievalService:
    """Assembles exactly what the model is allowed to reason from, for one fact."""

    def __init__(self, artifact_reader: SourceArtifactReader) -> None:
        self._artifact_reader = artifact_reader

    def assemble(
        self,
        fact: ObservedFact,
        resolution: Resolution,
        architecture: RecoveredArchitecture,
        budget: int = MAX_ITEMS,
    ) -> EvidencePackage:
        """Builds the evidence package for one fact.

        Collects the governing rule, its rationale, the record it replaced and
        the fact's immediate structural neighbourhood, each with a span that
        points at a real location.

        Everything is ordered deterministically, because the package's hash is
        both the cache key and the guarantee that two runs over one release
        produce the same question.
        """

        if resolution.governing is None:
            raise NothingToReasonAbout(
                f"fact {fact.fact_id} has no governing decision, so there is "
                "nothing to assemble evidence against. An uncovered or "
                "ambiguous fact reaches its bucket without a model call."
            )

        offered = tuple(self._items(fact, resolution, architecture))
        items, dropped = fit(offered, budget)

        return EvidencePackage(
            fact_id=fact.fact_id,
            evidence_hash=_hash(fact.fact_id, items),
            items=items,
            truncated=len(items) < len(offered),
            dropped_roles=dropped,
        )

    def _items(
        self,
        fact: ObservedFact,
        resolution: Resolution,
        architecture: RecoveredArchitecture,
    ):
        """Every item, in the order the roles are declared in.

        The order is the truncation order and it is also the order a prompt
        reads them in, so it is fixed here rather than at either end.
        """

        governing = resolution.governing
        yield self._quoted(
            ref=governing.decision_id,
            role=EvidenceRole.RULE,
            record=governing,
            architecture=architecture,
            release_id=fact.release_id,
        )

        if governing.rationale:
            yield EvidenceItem(
                ref=f"{governing.decision_id}#why",
                role=EvidenceRole.RATIONALE,
                text=governing.rationale,
                span=governing.source_span,
            )

        if resolution.superseded is not None:
            yield self._quoted(
                ref=resolution.superseded.decision_id,
                role=EvidenceRole.SUPERSEDED,
                record=resolution.superseded,
                architecture=architecture,
                release_id=fact.release_id,
            )

        if resolution.permitted_instead:
            yield self._permitted(fact, resolution, architecture)

        for sentence in neighbours(architecture, fact, _mentioned(resolution)):
            yield EvidenceItem(
                ref=f"context:{_slug(sentence)}",
                role=EvidenceRole.STRUCTURAL_CONTEXT,
                text=sentence,
            )

        for source in resolution.conflicting_sources:
            yield EvidenceItem(
                ref=f"{governing.decision_id}#conflict:{source}",
                role=EvidenceRole.IMPLICATION,
                text=(
                    f"{source} describes this relationship differently from "
                    f"{governing.source}, which is the source that governs it."
                ),
            )

    def _quoted(
        self, *, ref, role, record, architecture, release_id
    ) -> EvidenceItem:
        """One item whose text is the lines its record was read from.

        Quoted rather than paraphrased, and quoted from the span the scan
        recorded rather than from a search of the document: whoever parsed the
        file knows which line a rule came from, and a second reader of one
        file is two chances to disagree about what it says.
        """

        if record.source_span is None:
            return EvidenceItem(ref=ref, role=role, text=_rendered(record))

        span = record.source_span
        quoted = self._lines(architecture.repository_id, release_id, span)

        return EvidenceItem(
            ref=ref,
            role=role,
            text="\n".join(
                (_rendered(record), f"{span.path}:{_range(span)}", quoted)
            ),
            span=span,
        )

    def _permitted(self, fact, resolution, architecture) -> EvidenceItem:
        """The list that does not contain the pair in question.

        The one item that evidences an absence. "Nothing permits this" has no
        file and no line, so the package carries every permission that *does*
        exist for the element this fact points at - and the conclusion becomes
        an observation over a finite list rather than an assumption the model
        has to supply.
        """

        lines = [
            f"{record.subject} may call {record.object}"
            + (f"  [{record.source_span.path}:{record.source_span.start_line}]"
               if record.source_span else "")
            for record in resolution.permitted_instead
        ]

        return EvidenceItem(
            ref=f"permitted:{fact.object.canonical}",
            role=EvidenceRole.PERMITTED_SET,
            text=(
                f"Everything permitted to reach {fact.object.name}, and nothing "
                "else is:\n" + "\n".join(lines)
            ),
        )

    def _lines(self, repository_id: str, release_id: str, span: Span) -> str:
        """The span's own lines, and not one more.

        Read through the port the decision sources already read through, so
        this component still has exactly one way to reach a repository and no
        module in it opens a file.
        """

        document = self._artifact_reader.read_text(
            repository_id, release_id, span.path
        ).splitlines()

        return "\n".join(document[span.start_line - 1 : span.end_line])


class NothingToReasonAbout(ValueError):
    """Asked to assemble evidence for a fact no decision governs.

    Raised rather than returning an empty package. The orchestrator
    short-circuits an uncovered or an ambiguous fact before it reaches here,
    so arriving at all means the pipeline's own ordering has gone wrong - and
    an empty package would hide that behind a verdict with nothing under it.
    """


def _mentioned(resolution: Resolution) -> frozenset[str]:
    """Canonical names some decision in this resolution speaks about.

    They are kept first when the neighbourhood is capped: a neighbour a rule
    has an opinion about is more use to a reviewer than one nothing mentions.
    """

    records = [
        record
        for record in (resolution.governing, resolution.superseded, *resolution.permitted_instead)
        if record is not None
    ]
    return frozenset(
        canonical_name(name)
        for record in records
        for name in (record.subject, record.object)
    )


def _slug(sentence: str) -> str:
    """A short, stable reference for one context sentence."""

    return sentence.replace(" ", "-").lower()[:48]


def _rendered(record) -> str:
    """The rule as a sentence.

    Always present, even when the lines are quoted beneath it. A quoted
    fragment of configuration is evidence and not a question: on its own,
    `app: frontend` does not say which workload admits it or what that means.
    The sentence is derived from the record's own fields rather than written,
    so it adds no claim the record does not already make - it only makes the
    claim legible.
    """

    return f"{record.subject} {str(record.constraint).replace('_', ' ')} {record.object}"


def _range(span: Span) -> str:
    return (
        str(span.start_line)
        if span.start_line == span.end_line
        else f"{span.start_line}-{span.end_line}"
    )


def _hash(fact_id: str, items: tuple[EvidenceItem, ...]) -> str:
    """The identity of one question.

    Over a canonical form with sorted keys and explicit separators, because
    the hash is the verdict cache's key: a hash that varies between runs on
    identical input means the cache never hits, and a hash that stays the same
    when the evidence changed means a cached answer is served to a question
    nobody asked. The first failure is slow and silent; the second is wrong
    and silent.
    """

    material = {
        "fact_id": fact_id,
        "items": [
            {
                "ref": item.ref,
                "role": str(item.role),
                "text": item.text,
                "span": item.span.to_dict() if item.span else None,
            }
            for item in items
        ],
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:HASH_LENGTH]


__all__ = ["EvidenceRetrievalService", "NothingToReasonAbout"]
