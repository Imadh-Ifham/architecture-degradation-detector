# Validates C3 event payloads and decides which ones C4 ranks

from collections.abc import Iterable

import structlog
from pydantic import ValidationError

from app.components.degradation_scoring.ingestion.models import EventIngestion, PayloadRecord
from app.domain.degradation_event import ContextTag, DegradationEventV2, ReviewStatus, Scope
from app.domain.severity_report import QuarantinedEvent, QuarantineReason, SkippedEvent, SkipReason

log = structlog.get_logger(__name__)


def ingest_events(payloads: Iterable[object], *, rank_only_confirmed: bool) -> EventIngestion:
    # Quarantine malformed payloads, skip ineligible events, keep the rest in input order.
    # When several skip rules apply, the first in this order is recorded,
    # rejected, intentional, superseded, system scope, not confirmed.

    valid: list[tuple[int, DegradationEventV2]] = []
    quarantined: list[QuarantinedEvent] = []
    records: dict[int, PayloadRecord] = {}
    for index, payload in enumerate(payloads):
        try:
            valid.append((index, DegradationEventV2.model_validate(payload)))
        except ValidationError as exc:
            item = _malformed(payload, exc)
            quarantined.append(item)
            records[index] = PayloadRecord(
                payload_index=index,
                event_id=item.event_id,
                outcome="quarantined",
                reason=str(item.reason),
                detail=item.detail,
            )

    superseded = {e.supersedes_event_id for _, e in valid if e.supersedes_event_id is not None}
    eligible: list[DegradationEventV2] = []
    skipped: list[SkippedEvent] = []
    for index, event in valid:
        reason = _skip_reason(event, superseded, rank_only_confirmed)
        if reason is None:
            eligible.append(event)
        else:
            skipped.append(SkippedEvent(event_id=event.event_id, reason=reason))
            log.info("event_skipped", reason=str(reason), event_id=event.event_id)
        records[index] = PayloadRecord(
            payload_index=index,
            event_id=event.event_id,
            scope=str(event.scope),
            anti_pattern_type=event.anti_pattern_type,
            review_status=str(event.review_status),
            context_tag=str(event.context.tag),
            outcome="eligible" if reason is None else "skipped",
            reason=None if reason is None else str(reason),
        )
    return EventIngestion(
        eligible=eligible,
        quarantined=quarantined,
        skipped=skipped,
        payloads=[records[index] for index in sorted(records)],
    )


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
