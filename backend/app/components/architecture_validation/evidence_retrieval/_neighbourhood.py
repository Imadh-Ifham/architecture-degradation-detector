"""What else the two ends of a fact touch.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    One hop, from the architecture the run already holds, capped.

    This is where the retrieval hypothesis is answered: neighbours are
    selected by **structure** - who is adjacent to whom - and not by textual
    similarity. The question being asked is architectural, so the context for
    it is architectural. Measuring that against keyword and embedding
    baselines is the experiment the research adds later; this is the arm it
    measures.

    One hop, because it answers *what else does this element touch*, which is
    what a reviewer needs in order to judge whether a dependency is
    reasonable. Two hops on a twelve-element system is most of the graph,
    which is not context - it is noise with a token bill.

    The cap matters more than the hop count. One hop from a hub element could
    be eleven neighbours, and that one fact would then cost more than five
    others combined. A cap makes package size predictable, which makes a
    run's token cost predictable, which is what makes a demonstration on a
    free tier survivable.

    No graph library. One hop over a tuple of relationships is a
    comprehension, and a dependency taken for a traversal this size would have
    to be justified to everybody who resolves the lockfile. `networkx` has
    since been declared - by the components that consume the published graph -
    so the argument is now about this traversal rather than about the
    dependency, and it is the same argument: eight neighbours do not need a
    graph object built and thrown away.
"""

from app.domain.recovered_architecture import RecoveredArchitecture

from .._identity import canonical_name
from ..models import ObservedFact

MAX_NEIGHBOURS = 8


def neighbours(
    architecture: RecoveredArchitecture,
    fact: ObservedFact,
    preferred: frozenset[str] = frozenset(),
    limit: int = MAX_NEIGHBOURS,
) -> tuple[str, ...]:
    """Describe what else the fact's two ends are connected to.

    `preferred` are canonical names a decision already mentions. They are kept
    first, because a neighbour some rule speaks about is more use to a
    reviewer than one nothing has an opinion about - and the cap means
    something has to be kept first.

    Ties break on the sentence itself, so the same fact produces the same
    neighbourhood in the same order every run. Non-deterministic truncation
    would change the package's hash between runs, and the hash is the verdict
    cache's key.
    """

    names = {element.id: element.name for element in architecture.elements}
    ends = {fact.subject.id, fact.object.id}

    described: dict[str, str] = {}
    for relationship in architecture.relationships:
        source, target = relationship.source_id, relationship.target_id
        if source in ends and target not in ends:
            described[names.get(target, target)] = (
                f"{names.get(source, source)} also reaches {names.get(target, target)}"
            )
        elif target in ends and source not in ends:
            described[names.get(source, source)] = (
                f"{names.get(target, target)} is also reached by "
                f"{names.get(source, source)}"
            )

    ordered = sorted(
        described.items(),
        key=lambda pair: (canonical_name(pair[0]) not in preferred, pair[1]),
    )
    return tuple(sentence for _, sentence in ordered[:limit])


__all__ = ["MAX_NEIGHBOURS", "neighbours"]
