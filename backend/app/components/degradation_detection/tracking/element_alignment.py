"""Align the elements of two consecutive releases (plan M3, element alignment steps 1-2).

Three passes, each over what the previous ones left:

1. **Exact:** the same id is the same element, unless its ``kind`` changed.
2. **Alias:** a new element whose ``aliases`` name an element of the previous release. Only a
   clean one-to-one claim on an id that disappeared is a rename; anything else (the id is still
   there, two claimants, two claimed ids) is a split or merge in disguise and links nothing.
3. **Similarity:** disappeared x appeared elements of the same kind, scored by
   ``similarity.py``, paired one-to-one by the Hungarian algorithm, and kept only if the score
   reaches ``rename_min`` and beats every competitor of either element by ``ambiguity_margin``.

When unsure, break the series rather than guess: every path that is not clearly one element
links nothing, so the element ends one lineage and starts another.
"""

from collections import defaultdict
from collections.abc import Iterable

import networkx as nx
import numpy as np
import structlog
from scipy.optimize import linear_sum_assignment

from app.components.degradation_detection.config import AlignConfig
from app.components.degradation_detection.models import AlignMethod
from app.components.degradation_detection.tracking.models import (
    ALIAS_CONFLICT,
    ALIGNMENT_AMBIGUOUS,
    LINEAGE_KIND_CHANGED,
    AlignmentDecision,
    AlignOutcome,
    Link,
    PairAlignment,
    SimilarityScore,
)
from app.components.degradation_detection.tracking.similarity import similarity
from app.domain.canonical_release import CanonicalRelease, ElementSnapshot

log = structlog.get_logger(__name__)

# Float tolerance for the two threshold comparisons, so that a score exactly on rename_min or
# exactly ambiguity_margin ahead is accepted as the plan states (">=") despite rounding.
_TOLERANCE = 1e-9


class _PairAligner:
    def __init__(self, old: CanonicalRelease, new: CanonicalRelease, cfg: AlignConfig) -> None:
        self._old, self._new, self._cfg = old, new, cfg
        self._old_els = {e.element_id: e for e in old.elements}
        self._new_els = {e.element_id: e for e in new.elements}
        self._links: dict[str, Link] = {}  # keyed by old id
        self._decisions: list[AlignmentDecision] = []
        self._settled_old: set[str] = set()  # linked, or deliberately left unlinked
        self._settled_new: set[str] = set()

    def align(self) -> PairAlignment:
        self._exact_pass()
        self._alias_pass()
        self._similarity_pass()
        return PairAlignment(
            from_release_id=self._old.release_id,
            to_release_id=self._new.release_id,
            links=tuple(self._links[old_id] for old_id in sorted(self._links)),
            decisions=tuple(self._decisions),
        )

    # --- passes ------------------------------------------------------------------------------

    def _exact_pass(self) -> None:
        for element_id in sorted(self._old_els.keys() & self._new_els.keys()):
            old, new = self._old_els[element_id], self._new_els[element_id]
            if old.kind == new.kind:
                self._link(old, new, AlignMethod.EXACT)
            else:
                self._kind_changed(old, new, AlignMethod.EXACT)

    def _alias_pass(self) -> None:
        # Bipartite graph of claims: appeared element -- each previous-release id it lists as an
        # alias. Aliases naming ids the previous release does not have are older history.
        claims: nx.Graph[tuple[str, str]] = nx.Graph()
        for new_id in self._appeared():
            for alias in sorted(set(self._new_els[new_id].aliases) & self._old_els.keys()):
                claims.add_edge(("old", alias), ("new", new_id))

        components = (sorted(c) for c in nx.connected_components(claims))
        for component in sorted(components):
            old_ids = tuple(element_id for side, element_id in component if side == "old")
            new_ids = tuple(element_id for side, element_id in component if side == "new")
            # A claimed id that still exists was exact-matched (or broke on kind): not a rename.
            clean = len(old_ids) == len(new_ids) == 1 and old_ids[0] not in self._new_els
            if clean:
                old, new = self._old_els[old_ids[0]], self._new_els[new_ids[0]]
                if old.kind == new.kind:
                    self._link(old, new, AlignMethod.ALIAS)
                    self._decide(old_ids, new_ids, old.kind, AlignMethod.ALIAS, AlignOutcome.LINKED)
                else:
                    self._kind_changed(old, new, AlignMethod.ALIAS)
                continue
            log.warning(
                ALIAS_CONFLICT,
                reason=ALIAS_CONFLICT,
                release_id=self._new.release_id,
                old_ids=list(old_ids),
                new_ids=list(new_ids),
            )
            kind = self._old_els[old_ids[0]].kind
            self._decide(old_ids, new_ids, kind, AlignMethod.ALIAS, AlignOutcome.ALIAS_CONFLICT)
            self._settled_old.update(old_ids)
            self._settled_new.update(new_ids)

    def _similarity_pass(self) -> None:
        by_kind: dict[str, tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
        for old_id in self._disappeared():
            by_kind[self._old_els[old_id].kind][0].append(old_id)
        for new_id in self._appeared():
            by_kind[self._new_els[new_id].kind][1].append(new_id)

        old_adj, new_adj = _neighbours(self._old), _neighbours(self._new)
        translate = {old_id: link.to_element_id for old_id, link in self._links.items()}
        for kind in sorted(by_kind):
            old_ids, new_ids = by_kind[kind]
            if not old_ids or not new_ids:
                continue
            scores = [
                [
                    similarity(
                        self._old_els[o],
                        self._new_els[n],
                        old_adj[o],
                        new_adj[n],
                        translate,
                        self._cfg.weights,
                    )
                    for n in new_ids
                ]
                for o in old_ids
            ]
            totals = np.array([[s.total for s in row] for row in scores])
            rows, cols = linear_sum_assignment(totals, maximize=True)
            for i, j in zip(rows.tolist(), cols.tolist(), strict=True):
                competitors = np.concatenate(
                    [np.delete(totals[i, :], j), np.delete(totals[:, j], i)]
                )
                runner_up = float(competitors.max()) if competitors.size else None
                self._judge(old_ids[i], new_ids[j], kind, scores[i][j], runner_up)

    # --- helpers -----------------------------------------------------------------------------

    def _judge(
        self, old_id: str, new_id: str, kind: str, score: SimilarityScore, runner_up: float | None
    ) -> None:
        if score.total < self._cfg.rename_min - _TOLERANCE:
            outcome = AlignOutcome.BELOW_MIN
        elif runner_up is not None and (
            score.total - runner_up < self._cfg.ambiguity_margin - _TOLERANCE
        ):
            outcome = AlignOutcome.AMBIGUOUS
            log.warning(
                ALIGNMENT_AMBIGUOUS,
                reason=ALIGNMENT_AMBIGUOUS,
                release_id=self._new.release_id,
                old_id=old_id,
                new_id=new_id,
                similarity=round(score.total, 4),
                runner_up=round(runner_up, 4),
            )
        else:
            outcome = AlignOutcome.LINKED
            self._link(
                self._old_els[old_id], self._new_els[new_id], AlignMethod.SIMILARITY, score.total
            )
        self._decide((old_id,), (new_id,), kind, AlignMethod.SIMILARITY, outcome, score, runner_up)

    def _link(
        self,
        old: ElementSnapshot,
        new: ElementSnapshot,
        method: AlignMethod,
        similarity: float | None = None,
    ) -> None:
        self._links[old.element_id] = Link(
            from_element_id=old.element_id,
            to_element_id=new.element_id,
            method=method,
            similarity=similarity,
        )
        self._settled_old.add(old.element_id)
        self._settled_new.add(new.element_id)

    def _kind_changed(
        self, old: ElementSnapshot, new: ElementSnapshot, method: AlignMethod
    ) -> None:
        log.info(
            LINEAGE_KIND_CHANGED,
            reason=LINEAGE_KIND_CHANGED,
            release_id=self._new.release_id,
            old_id=old.element_id,
            new_id=new.element_id,
            old_kind=old.kind,
            new_kind=new.kind,
        )
        self._decide(
            (old.element_id,), (new.element_id,), old.kind, method, AlignOutcome.KIND_CHANGED
        )
        self._settled_old.add(old.element_id)
        self._settled_new.add(new.element_id)

    def _decide(
        self,
        old_ids: tuple[str, ...],
        new_ids: tuple[str, ...],
        kind: str,
        method: AlignMethod,
        outcome: AlignOutcome,
        score: SimilarityScore | None = None,
        runner_up: float | None = None,
    ) -> None:
        self._decisions.append(
            AlignmentDecision(
                from_release_id=self._old.release_id,
                to_release_id=self._new.release_id,
                from_element_ids=old_ids,
                to_element_ids=new_ids,
                kind=kind,
                method=method,
                outcome=outcome,
                score=score,
                runner_up=runner_up,
            )
        )

    def _disappeared(self) -> list[str]:
        return sorted(self._old_els.keys() - self._new_els.keys() - self._settled_old)

    def _appeared(self) -> list[str]:
        return sorted(self._new_els.keys() - self._old_els.keys() - self._settled_new)


def _neighbours(release: CanonicalRelease) -> dict[str, set[str]]:
    """Undirected neighbours of every element (callers and callees), self-loops left out."""
    adjacency: dict[str, set[str]] = {e.element_id: set() for e in release.elements}
    for edge in release.dependencies:
        if edge.from_id != edge.to_id:
            adjacency[edge.from_id].add(edge.to_id)
            adjacency[edge.to_id].add(edge.from_id)
    return adjacency


def align_pair(old: CanonicalRelease, new: CanonicalRelease, cfg: AlignConfig) -> PairAlignment:
    """Links and non-exact decisions between two consecutive releases."""
    return _PairAligner(old, new, cfg).align()


def align_timeline(
    releases: Iterable[CanonicalRelease], cfg: AlignConfig
) -> tuple[PairAlignment, ...]:
    """``align_pair`` over each pair of consecutive releases, in timeline order."""
    ordered = list(releases)
    return tuple(align_pair(a, b, cfg) for a, b in zip(ordered, ordered[1:], strict=False))
