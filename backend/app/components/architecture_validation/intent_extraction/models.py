"""Intent extraction data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass, field

from ..models import ConstraintKind, SourceTier


@dataclass(frozen=True)
class Constraint:
    """One requirement a decision places on the architecture."""

    subject: str
    kind: ConstraintKind
    object: str
    via: str | None = None


@dataclass(frozen=True)
class CandidateDecision:
    """A decision read from a source, not yet accepted as authoritative.

    A candidate from a weak tier stays a candidate until an architect ratifies
    it. That gate is what stops the pipeline manufacturing its own ground
    truth out of commit messages.
    """

    candidate_id: str
    constraint: Constraint
    tier: SourceTier
    source_ref: str
    excerpt: str
    rationale: str | None = None


@dataclass(frozen=True)
class ExtractionOutcome:
    """What every source found for one release.

    `sources_run` includes sources that found nothing. A decision-record
    source returning zero is a result about the repository, not a step to skip
    quietly.
    """

    candidates: tuple[CandidateDecision, ...]
    sources_run: tuple[str, ...]
    counts_by_tier: dict = field(default_factory=dict)
