# ADR-violation weight (optional): AV = status_w x scope_w x explicitness for
# the most serious ADR C2 links to the event's elements; inactive without an ADR index.

from collections.abc import Collection

import structlog

from app.components.degradation_scoring.features.models import AdrContext, AdrWeightFeatures
from app.components.degradation_scoring.models import AdrIndex, AdrRecord

log = structlog.get_logger(__name__)

# §5.3's table: fixed constants (the definition, like the fix words), recorded in the manifest.
# Unknown status = 0.0 (no sign the decision is in force); unknown scope = "unspecified".
STATUS_WEIGHTS = {
    "accepted": 1.0,
    "proposed": 0.5,
    "deprecated": 0.2,
    "superseded": 0.2,
    "rejected": 0.0,
    "unknown": 0.0,
}
SCOPE_WEIGHTS = {"system": 1.0, "component": 0.7, "module": 0.7, "local": 0.4, "unspecified": 0.4}
C2_LINK_EXPLICITNESS = 1.0  # a C2 adr_ref; the semantic fallback (similarity x 0.5) is post-PP1


def adr_weight(record: AdrRecord, explicitness: float = C2_LINK_EXPLICITNESS) -> float:
    return STATUS_WEIGHTS[record.status] * SCOPE_WEIGHTS[record.scope] * explicitness


def event_adr_weight(nodes: Collection[str], index: AdrIndex) -> AdrWeightFeatures:
    # AV = max over the ADRs C2 links to any of the event's elements (owner, 2026-10-18);
    # no link = 0.0, a defined zero; links to ADRs missing from the index are logged, skipped
    linked = sorted({adr for node in nodes for adr in index.links.get(node, [])})
    known = [adr for adr in linked if adr in index.adrs]
    for missing in sorted(set(linked) - set(known)):
        log.warning("adr_link_unknown", reason="adr_link_unknown", adr=missing)
    weights = {adr: adr_weight(index.adrs[adr]) for adr in known}
    worst = max(known, key=weights.__getitem__) if known else None  # ties: smallest id
    return AdrWeightFeatures(
        av=weights[worst] if worst else 0.0,
        adr_id=worst,
        linked_adrs=known,
    )


def adr_context(index: AdrIndex | None) -> AdrContext:
    # run-level state for the manifest: active, or why not, plus the weight table used
    reason = None
    if index is None:
        reason = "no_adr_index"
    elif not index.adrs:
        reason = "empty_adr_index"
    if reason:
        log.info("adr_violation_inactive", reason=reason)
    return AdrContext(
        active=reason is None,
        inactive_reason=reason,
        status_weights=STATUS_WEIGHTS,
        scope_weights=SCOPE_WEIGHTS,
        explicitness=C2_LINK_EXPLICITNESS,
    )
