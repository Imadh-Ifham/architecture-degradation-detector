# Validates C3 event payloads and decides which ones C4 ranks

from collections.abc import Iterable

import structlog
from pydantic import ValidationError

from app.components.degradation_scoring.ingestion.models import EventIngestion
from app.domain.degradation_event import ContextTag, DegradationEventV2, ReviewStatus, Scope
from app.domain.severity_report import QuarantinedEvent, QuarantineReason, SkippedEvent, SkipReason

log = structlog.get_logger(__name__)


def ingest_events(payloads: Iterable[object], *, rank_only_confirmed: bool) -> EventIngestion:
    # Quarantine malformed payloads, skip ineligible events, keep the rest in input order.
    # When several skip rules apply, the first in this order is recorded, 
    # rejected, intentional, superseded, system scope, not confirmed.
    
    valid: list[DegradationEventV2] = []
    quarantined: list[QuarantinedEvent] = []
    for payload in payloads:
        try:
            valid.append(DegradationEventV2.model_validate(payload))
        except ValidationError as exc:
            quarantined.append(_malformed(payload, exc))

    superseded = {e.supersedes_event_id for e in valid if e.supersedes_event_id is not None}
    eligible: list[DegradationEventV2] = []
    skipped: list[SkippedEvent] = []
    for event in valid:
        reason = _skip_reason(event, superseded, rank_only_confirmed)
        if reason is None:
            eligible.append(event)
        else:
            skipped.append(SkippedEvent(event_id=event.event_id, reason=reason))
            log.info("event_skipped", reason=str(reason), event_id=event.event_id)
    return EventIngestion(eligible=eligible, quarantined=quarantined, skipped=skipped)


def _malformed(payload: object, exc: ValidationError) -> QuarantinedEvent:
    raw_id = payload.get("event_id") if isinstance(payload, dict) else None
    event_id = raw_id if isinstance(raw_id, str) and raw_id else None
    detail = "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '<event>'}: {error['msg']}"
        for error in exc.errors()
    )
    reason = QuarantineReason.MALFORMED_PAYLOAD
    log.warning("event_quarantined", reason=str(reason), event_id=event_id, detail=detail)
    return QuarantinedEvent(event_id=event_id, reason=reason, detail=detail)


def _skip_reason(
    event: DegradationEventV2, superseded: set[str], rank_only_confirmed: bool
) -> SkipReason | None:
    if event.review_status is ReviewStatus.REJECTED:
        return SkipReason.REJECTED
    if event.context.tag is ContextTag.INTENTIONAL:
        return SkipReason.INTENTIONAL
    if event.event_id in superseded:
        return SkipReason.SUPERSEDED
    if event.scope is Scope.SYSTEM:
        return SkipReason.SYSTEM_SCOPE_NOT_RANKABLE
    if rank_only_confirmed and event.review_status is not ReviewStatus.CONFIRMED:
        return SkipReason.NOT_CONFIRMED
    return None
