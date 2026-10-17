"""Chain the links of consecutive releases into lineages (plan M3, element alignment step 4).

An element in the first release, or one with no link from the previous release, starts a
lineage ``LIN-<element_id>@<release_id>``. A link appends the new element to its predecessor's
lineage; a link that is not EXACT is a RENAME event. Nothing links across a missing release, so
a lineage always covers consecutive releases.
"""

from collections.abc import Sequence

from app.components.degradation_detection.models import (
    AlignMethod,
    Lineage,
    LineageEvent,
    LineageEventType,
    LineageMember,
    Timeline,
)
from app.components.degradation_detection.tracking.models import PairAlignment


def lineage_id(element_id: str, release_id: str) -> str:
    return f"LIN-{element_id}@{release_id}"


def build_lineages(
    timeline: Timeline, pairs: Sequence[PairAlignment]
) -> tuple[tuple[Lineage, ...], tuple[LineageEvent, ...]]:
    """Lineages in order of first appearance (then element id), and their RENAME events.

    ``pairs[k]`` aligns ``timeline.entries[k]`` with ``timeline.entries[k + 1]``.
    """
    if len(pairs) != max(len(timeline.entries) - 1, 0):
        raise ValueError("expected one pair alignment per pair of consecutive releases")

    kinds: dict[str, str] = {}  # lineage id -> kind
    members: dict[str, list[LineageMember]] = {}  # insertion order = output order
    events: list[LineageEvent] = []
    current: dict[str, str] = {}  # element id in the previous release -> lineage id

    for k, entry in enumerate(timeline.entries):
        release = entry.release
        links = {link.to_element_id: link for link in pairs[k - 1].links} if k > 0 else {}
        following: dict[str, str] = {}
        for element in sorted(release.elements, key=lambda e: e.element_id):
            link = links.get(element.element_id)
            if link is None:
                lin = lineage_id(element.element_id, release.release_id)
                kinds[lin], members[lin] = element.kind, []
            else:
                lin = current[link.from_element_id]
                if link.method is not AlignMethod.EXACT:
                    events.append(
                        LineageEvent(
                            lineage_id=lin,
                            event_type=LineageEventType.RENAME,
                            release_id=release.release_id,
                            from_element_ids=(link.from_element_id,),
                            to_element_ids=(link.to_element_id,),
                            method=link.method,
                            similarity=link.similarity,
                        )
                    )
            members[lin].append(
                LineageMember(
                    ordinal=entry.ordinal,
                    release_id=release.release_id,
                    element_id=element.element_id,
                )
            )
            following[element.element_id] = lin
        current = following

    lineages = tuple(
        Lineage(lineage_id=lin, kind=kinds[lin], members=tuple(chain))
        for lin, chain in members.items()
    )
    return lineages, tuple(events)
