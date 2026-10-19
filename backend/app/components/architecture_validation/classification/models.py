"""Classification data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass

from app.domain.validated_architecture import ValidationBucket

PUBLISH_THRESHOLD = 0.70
"""The one threshold between publishing a fact and routing it for review.

Deliberately a named constant and deliberately a round number: there is no
labelled set to sweep it against yet, and a value like 0.73 would imply a sweep
that never happened. Re-sweeping once a labelled set exists is a one-line
change plus a re-run.
"""


@dataclass(frozen=True)
class Cap:
    """The most a fact may claim, and the reason, as one row.

    This is the rule that makes the tiered intent model safe. Without it, a
    constraint inferred from a commit message could be reported as a violation
    with the same confidence as one read from an enforced network policy.

    `bucket` is the strongest bucket this cap allows, or `None` when the cap
    limits the number without changing what was concluded - an unverified
    `confirms` is still a confirmation, it is simply not one to publish
    unchecked.

    `name` is what reaches `ScoreTrace.ceiling_applied` and then a screen. It
    is why a cap is a named row rather than a float: a number that was
    silently reduced is indistinguishable from a number that was low to begin
    with.
    """

    name: str
    bucket: ValidationBucket | None
    confidence: float
