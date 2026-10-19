"""Splits and merges (plan M3, step 3). Post-PP1: the PP1 aligner never calls this.

Until then an alias claimed by two new elements, or a new element with two disappeared aliases,
is an ``ALIAS_CONFLICT`` and links nothing, so a split or merge breaks the lineage instead of
being guessed as a rename.
"""

from app.components.degradation_detection.config import AlignConfig
from app.components.degradation_detection.tracking.models import SplitMerge
from app.domain.canonical_release import CanonicalRelease


def detect_splits_merges(
    old: CanonicalRelease,
    new: CanonicalRelease,
    disappeared: tuple[str, ...],
    appeared: tuple[str, ...],
    links: dict[str, str],
    cfg: AlignConfig,
) -> tuple[SplitMerge, ...]:
    """Splits (one disappeared element scoring >= ``split_min`` against two or more new ones
    whose combined neighbours overlap the original's) and the mirror case, merges."""
    raise NotImplementedError("splits and merges are post-PP1 (plan M3, step 3)")
