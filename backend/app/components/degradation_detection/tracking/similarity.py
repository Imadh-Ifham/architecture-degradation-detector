"""Features of the similarity pass (plan M3, step 2).

``sim = w_name * name + w_neighbours * neighbour_jaccard + w_size * size_ratio``, each feature in
[0, 1], weights from ``align.weights``. A feature that cannot be computed (no neighbours, a
null size, sizes in different units) scores 0 rather than being left out and the weights
re-spread: re-spreading would let a name match alone reach ``rename_min``, and a wrong link is
worse than a missed one.
"""

import re
from collections.abc import Mapping, Set

from rapidfuzz import fuzz

from app.components.degradation_detection.config import AlignWeights
from app.components.degradation_detection.tracking.models import SimilarityScore
from app.domain.canonical_release import ElementSnapshot

# A lower-to-upper step ("orderService") or the last capital of an acronym ("HTTPClient").
_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SEPARATORS = re.compile(r"[\s\-_./]+")


def name_tokens(name: str) -> str:
    """Lower-case words of a name split on camelCase, ``-``, ``_``, ``.``, ``/`` and spaces."""
    words = _SEPARATORS.split(_CASE_BOUNDARY.sub(" ", name))
    return " ".join(word.lower() for word in words if word)


def name_similarity(a: str, b: str) -> float:
    """rapidfuzz token-set ratio of the two names' words, in [0, 1]."""
    return fuzz.token_set_ratio(name_tokens(a), name_tokens(b), processor=None) / 100


def neighbour_jaccard(
    old_neighbours: Set[str], new_neighbours: Set[str], links: Mapping[str, str]
) -> float:
    """Jaccard overlap of the neighbours, old ones translated through ``links`` (old -> new id).

    An old neighbour without a link stays in the union but can never be in the intersection,
    even if an element with the same id exists now: without a link it is not the same element.
    """
    translated = {("new", links[n]) if n in links else ("old", n) for n in old_neighbours}
    current = {("new", n) for n in new_neighbours}
    union = translated | current
    return len(translated & current) / len(union) if union else 0.0


def size_ratio(old: ElementSnapshot, new: ElementSnapshot) -> float:
    """``min / max`` of the two sizes; 0 when either is null, the units differ, or both are 0."""
    if old.size is None or new.size is None or old.size_unit != new.size_unit:
        return 0.0
    largest = max(old.size, new.size)
    return min(old.size, new.size) / largest if largest > 0 else 0.0


def similarity(
    old: ElementSnapshot,
    new: ElementSnapshot,
    old_neighbours: Set[str],
    new_neighbours: Set[str],
    links: Mapping[str, str],
    weights: AlignWeights,
) -> SimilarityScore:
    name = name_similarity(old.name, new.name)
    neighbours = neighbour_jaccard(old_neighbours, new_neighbours, links)
    size = size_ratio(old, new)
    total = weights.name * name + weights.neighbours * neighbours + weights.size * size
    # The weights sum to 1 (config checks it); min() only absorbs float rounding above 1.
    return SimilarityScore(name=name, neighbours=neighbours, size=size, total=min(total, 1.0))
