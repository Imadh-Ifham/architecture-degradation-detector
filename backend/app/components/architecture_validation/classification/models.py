"""Classification data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass

from app.domain.validated_architecture import ValidationBucket

from ..models import EvidenceStrength


PUBLISH_THRESHOLD = 0.70
"""The one threshold between publishing a fact and routing it for review.

Deliberately a named constant and deliberately a round number: there is no
labelled set to sweep it against yet, and a value like 0.73 would imply a sweep
that never happened. Re-sweeping once a labelled set exists is a one-line
change plus a re-run.
"""


@dataclass(frozen=True)
class CeilingRule:
    """The strongest bucket a given source strength may reach.

    This is the rule that makes the tiered intent model safe. Without it, a
    constraint inferred from a commit message could be reported as a
    violation with the same confidence as one read from an enforced network
    policy.
    """

    strength: EvidenceStrength
    ceiling: ValidationBucket
