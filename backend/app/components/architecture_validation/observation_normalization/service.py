"""Observation normalization service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Turns a recovered architecture into one uniform fact shape, whatever style
    it came from.

    Research module: M1.

    This service has no dependencies and performs no I/O. It is handed an
    architecture and returns facts, which is the whole of its contract: the
    architecture document gives recovery the job of supplying the elements,
    their dependencies and the detected style, and it says that validation does
    not read source code. Reading the architecture - from recovery's graph,
    from a recorded snapshot, from anywhere - happens behind a port, outside
    this component.

    It is not a second recovery engine and it repeats none of recovery's work.
    Recovery decides *what the system is made of*; this decides *what that
    looks like* so the seven subcomponents after it can be written once rather
    than once per input shape. The value is the uniformity and the canonical
    identity, not the discovery.
"""

from app.domain.recovered_architecture import (
    ArchitectureStyle,
    RecoveredArchitecture,
    StyleSource,
)

from ._identity import collisions
from .._release import release_sort_key
from ._style import infer_style
from .models import IdentityCollision, NormalizationOutcome
from .styles import GENERIC_STYLE_NAME, KNOWN_LABELS, adapter_for


class ObservationNormalizationService:
    """Turns a recovered architecture into canonical observed facts."""

    def normalise(self, architecture: RecoveredArchitecture) -> NormalizationOutcome:
        """Normalise a recovered architecture into observed facts.

        Selects a style adapter from the registry and lets it reduce the
        architecture's relationships into the canonical triple. Downstream
        subcomponents never learn which style a fact came from, which is what
        lets one validation algorithm serve every style.

        An architecture that arrives with no relationships produces no facts
        and says so. It is not an error and nothing is derived to fill the gap:
        a release whose dependencies recovery has not reported is a release
        with nothing to validate, and reporting that honestly is the only
        correct answer available here.

        Raises:
            UnorderableRelease: the release identifier cannot be placed in
                order against other releases. Checked here, before any fact
                exists, so the run stops with one message naming the
                identifier instead of producing facts that cannot be compared.
        """

        warnings: list[str] = []

        # Before anything else, and before any fact exists: a release that
        # cannot be ordered stops here with one message naming it.
        sort_key = release_sort_key(architecture.release_id)

        style = self._resolve_style(architecture, warnings)

        adapter = adapter_for(style)
        facts = adapter.normalise(architecture)

        identity_collisions = self._report_collisions(architecture, warnings)
        absorbed = self._report_absorbed_labels(architecture, warnings)
        facts, merged = self._merge_by_identity(facts, warnings)

        style_resolved = getattr(adapter, "style", style)
        if type(adapter).__name__ == "GenericAdapter":
            style_resolved = GENERIC_STYLE_NAME
            warnings.append(
                "architecture style not resolved; normalised generically and capped"
            )

        if not architecture.has_element_relationships:
            warnings.append(
                "recovery supplied no element-to-element dependencies for this "
                "release; there is nothing to validate"
            )

        # Merged facts are subtracted: they did produce a fact, and reporting
        # them here as well would blame the adapter for an identity collision
        # that the warning above has already explained correctly.
        dropped = len(architecture.relationships) - len(facts) - merged
        if dropped > 0:
            # Only the event-driven adapter legitimately emits fewer facts than
            # relationships, by collapsing two hops into one. Anywhere else a
            # shortfall means a relationship named an element that is not in
            # the architecture, which is worth saying out loud.
            warnings.append(
                f"{dropped} relationship(s) produced no fact; "
                "either collapsed by the style adapter or naming an unknown element"
            )

        return NormalizationOutcome(
            architecture=architecture,
            facts=facts,
            style_resolved=str(style_resolved),
            style_source=architecture.style_source,
            release_sort_key=sort_key,
            relationship_count=len(architecture.relationships),
            identity_collisions=identity_collisions,
            merged_fact_count=merged,
            absorbed_labels=absorbed,
            warnings=tuple(warnings),
        )


    def _report_collisions(
        self, architecture: RecoveredArchitecture, warnings: list[str]
    ) -> tuple[IdentityCollision, ...]:
        """Say where canonicalisation reduced two element names to one.

        Over the architecture's elements rather than over the facts, because
        an element that produced no relationship is still an element whose
        identity was merged, and a reader asking "could your canonicalisation
        have merged two services" is asking about the architecture.

        Reported and not raised. M1 cannot tell a repository that spells one
        service two ways from one that has two similarly named services, and
        guessing either way would be worse than saying what happened.
        """

        found = collisions(element.name for element in architecture.elements)
        reported = []
        for key, names in found.items():
            warnings.append(
                f"element names {list(names)} all reduce to the identity "
                f"'{key}'; they are treated as one element"
            )
            reported.append(
                IdentityCollision(
                    key=key,
                    names=names,
                    # The ids as well as the names, because showing two
                    # elements becoming one means pointing at both of them in
                    # the input graph, and that graph is keyed by id.
                    element_ids=tuple(
                        sorted(
                            element.id
                            for element in architecture.elements
                            if element.name in names
                        )
                    ),
                )
            )

        return tuple(reported)

    def _report_absorbed_labels(
        self, architecture: RecoveredArchitecture, warnings: list[str]
    ) -> tuple[str, ...]:
        """Name the relationship labels no adapter recognised.

        Absorbed, not refused. The component diagram says this subcomponent
        collapses *any* architectural style into one fact shape, and raising
        on an unfamiliar word is the opposite of any - recovery will add a
        relationship type and the run has to survive it. The original word is
        kept in the fact's `observed_as`, so nothing is lost.

        What is not free is the consequence: a relationship nobody wrote a
        rule for will come back from the decision model as uncovered, and an
        uncovered fact is a row on a results table somebody has to interpret.
        That is why the words are named here rather than silently folded in.
        """

        absorbed = tuple(
            sorted(
                {
                    relationship.label
                    for relationship in architecture.relationships
                    if relationship.label.strip().lower() not in KNOWN_LABELS
                }
            )
        )
        if absorbed:
            warnings.append(
                f"relationship label(s) {list(absorbed)} are not in the canonical "
                "vocabulary; absorbed as 'depends-on' with the original kept"
            )

        return absorbed

    def _merge_by_identity(self, facts, warnings: list[str]):
        """Collapse facts that share a fact id, and say how many were lost.

        Two spellings of one element produce two relationships that hash to
        the same `fact_id`, because the hash is over the canonical triple.
        Returning both would publish two edges carrying one identity - and
        every consumer keys on that identity: the evidence cache would be
        filled twice with different content, the reasoner would be paid twice
        for one question, and the graph handed on would hold a duplicate edge
        that no amount of downstream care could separate.

        So the first one wins and the rest are counted. The first is not a
        better answer than the second; it is an arbitrary choice made visible,
        which is why the count travels with the outcome and the collision that
        caused it is reported beside it.
        """

        kept: dict[str, object] = {}
        for fact in facts:
            kept.setdefault(fact.fact_id, fact)

        merged = len(facts) - len(kept)
        if merged:
            warnings.append(
                f"{merged} fact(s) shared an identity with another and were "
                "merged; see the reported identity collisions"
            )

        return tuple(kept.values()), merged

    def _resolve_style(
        self, architecture: RecoveredArchitecture, warnings: list[str]
    ) -> ArchitectureStyle:
        """Return the style that selects the adapter, and say whose it is.

        Recovery's answer wins whenever recovery gave one, including when that
        answer is `unknown`. Second-guessing it would mean two parties deciding
        the same thing with no record of which one did, and the architecture
        document assigns the detection to recovery.

        The inference runs only in the other case, and leaves a warning saying
        so. The warning is what keeps "we worked the style out ourselves" from
        turning into "the style was detected" by the time it reaches a slide.
        """

        if architecture.style_source is StyleSource.C1:
            return architecture.style

        inferred = infer_style(architecture.elements, architecture.relationships)
        warnings.append(
            f"recovery supplied no architectural style; inferred '{inferred}' "
            "from the elements and labelled inferred_by_c2"
        )
        return inferred


__all__ = ["ObservationNormalizationService"]
