"""Observation normalization data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass, field

from app.domain.recovered_architecture import RecoveredArchitecture

from ..models import ObservedFact


@dataclass(frozen=True)
class IdentityCollision:
    """Two or more element names that reduce to one identity.

    `names` holds every original, sorted, so the pair can be looked at rather
    than described. Both halves are needed: `key` is what the facts were
    merged under, and without the originals nobody can decide afterwards
    whether the merge was right.

    `element_ids` is what makes the merge drawable. Showing two elements
    becoming one needs to point at both of them in the input graph, and names
    are not how that graph is keyed.

    This is a report and not a resolution. M1 cannot tell a repository that
    spells one service two ways from a repository that has two services with
    similar names, so it says what it did and lets the run continue.
    """

    key: str
    names: tuple[str, ...]
    element_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "names": list(self.names),
            "element_ids": list(self.element_ids),
        }


@dataclass(frozen=True)
class NormalizationOutcome:
    """The facts for one release, and how they were arrived at.

    `style_resolved` is reported rather than inferred later: an architecture
    whose style could not be determined has to say so, because it caps how
    strong any verdict about it may become.

    `style_source` answers the question `style_resolved` invites - whose answer
    is this. Recovery detects the style when it can, and this subcomponent
    infers it when recovery did not, so the two cases have to be told apart by
    a reader who sees only the result.

    `relationship_count` is what recovery supplied, before the style adapter
    reduced it. A count that exceeds the number of facts is expected - an
    event-driven publish and subscribe pair collapses into one - and the
    difference is reported as a warning rather than left for a reader to
    notice.

    `release_sort_key` is returned rather than left to be worked out again.
    The run row stores it so that ordering is right in SQL as well as in
    Python, and a second parse somewhere else is a second parser that can
    disagree with this one.

    `architecture` is the input, returned unmodified beside the output. It is
    the only way anything downstream can show the before and the after
    together - which is the clearest thing this subcomponent has to put on a
    screen - and it is also how a fact's element ids resolve back to the edge
    they came from. A reference, not a copy: the input is frozen, so returning
    it costs nothing and cannot drift from what was normalised.

    `absorbed_labels` holds the distinct relationship words no adapter
    recognised. They were still normalised, into a dependency, with the
    original kept on the fact - so this is not a list of losses. It is the
    list a reader needs to know how to read the uncovered count, because a
    word nobody has written a rule for produces a fact no decision governs.

    `identity_collisions` and `merged_fact_count` are two halves of one
    answer. The first says which element names reduced to a single identity;
    the second says how many facts that cost, because two spellings of one
    relationship share a `fact_id` and only one of them survives. Both are
    zero on a healthy snapshot, and a non-zero pair is a finding about the
    subject system rather than a failure here.
    """

    architecture: RecoveredArchitecture
    facts: tuple[ObservedFact, ...]
    style_resolved: str
    style_source: str
    release_sort_key: tuple[int, ...]
    relationship_count: int = 0
    identity_collisions: tuple[IdentityCollision, ...] = field(default_factory=tuple)
    merged_fact_count: int = 0
    absorbed_labels: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
