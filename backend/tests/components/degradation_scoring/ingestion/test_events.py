# Tests for event validation, quarantine and skip rules (C4-T08, FR-01).

import copy
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.components.degradation_scoring.ingestion.events import ingest_events
from app.domain.degradation_event import ContextTag
from app.domain.severity_report import QuarantineReason, SkipReason
from tests.components.degradation_scoring.support import load_fixture

PAYLOADS: list[dict[str, Any]] = load_fixture("events/fixture_events.v1.json")
EXPECTED: dict[str, Any] = load_fixture("fixture_expected.json")


def base_event() -> dict[str, Any]:
    # A plain eligible event (fixture E03: ELEMENT, PENDING, GENUINE).
    return copy.deepcopy(PAYLOADS[2])


def test_fixture_counts_match_the_design_exactly() -> None:
    result = ingest_events(PAYLOADS, rank_only_confirmed=False)
    counts = EXPECTED["counts"]
    designed_eligible = [
        row["event_id"]
        for row in EXPECTED["events"]
        if row["outcome"] == "ranked" or row["outcome"] == "quarantined:unresolved_element"
    ]

    assert result.quarantine_counts() == {"malformed_payload": 3}
    assert result.skip_counts() == counts["skipped"]
    assert [e.event_id for e in result.eligible] == designed_eligible
    assert len(result.eligible) == counts["eligible"]


def test_each_skipped_event_has_its_designed_reason() -> None:
    result = ingest_events(PAYLOADS, rank_only_confirmed=False)
    designed = {
        row["event_id"]: row["outcome"].split(":")[1]
        for row in EXPECTED["events"]
        if row["outcome"].startswith("skipped")
    }

    assert {s.event_id: str(s.reason) for s in result.skipped} == designed


def test_malformed_payloads_are_quarantined_with_their_error() -> None:
    result = ingest_events(PAYLOADS, rank_only_confirmed=False)

    for item, designed in zip(result.quarantined, EXPECTED["malformed"], strict=True):
        assert item.reason is QuarantineReason.MALFORMED_PAYLOAD
        assert item.event_id == designed["event_id"]
        field = ".".join(designed["loc"]) or "<event>"
        assert item.detail.startswith(f"{field}: ")


@pytest.mark.parametrize("payload", [None, 7, "event", [], {}], ids=repr)
def test_no_exception_escapes_for_garbage(payload: object) -> None:
    result = ingest_events([payload], rank_only_confirmed=False)

    assert result.eligible == []
    assert [q.reason for q in result.quarantined] == [QuarantineReason.MALFORMED_PAYLOAD]
    assert result.quarantined[0].event_id is None


def test_confirmed_only_switch_skips_everything_not_confirmed() -> None:
    result = ingest_events(PAYLOADS, rank_only_confirmed=True)
    skipped = {s.event_id: s.reason for s in result.skipped}

    assert [e.event_id for e in result.eligible] == EXPECTED["confirmed_event_ids"]
    assert skipped["DEG-C4FX-R02-0011"] is SkipReason.REJECTED  # rejected still named first
    assert skipped["DEG-C4FX-R02-0004"] is SkipReason.NOT_CONFIRMED


def test_uncertain_events_are_ranked_and_keep_their_tag() -> None:
    result = ingest_events(PAYLOADS, rank_only_confirmed=False)
    uncertain = [e for e in result.eligible if e.context.tag is ContextTag.UNCERTAIN]

    assert [e.event_id for e in uncertain] == ["DEG-C4FX-R02-0005"]


def _system_scope(event: dict[str, Any]) -> None:
    event.update(scope="SYSTEM", element_id=None, lineage_id=None)


def _rejected(event: dict[str, Any]) -> None:
    event["review_status"] = "REJECTED"


def _intentional(event: dict[str, Any]) -> None:
    event["context"].update(tag="INTENTIONAL", stage="RULE", rule_id="R2")


# Several rules at once: the first in rejected > intentional > superseded > system > confirmed.
PRECEDENCE = {
    "rejected_beats_intentional_and_system": ([_rejected, _intentional, _system_scope], "rejected"),
    "intentional_beats_superseded": ([_intentional], "intentional"),
    "superseded_beats_system": ([_system_scope], "superseded"),
    "system_beats_not_confirmed": ([_system_scope], "system_scope_not_rankable"),
}


@pytest.mark.parametrize("case", sorted(PRECEDENCE))
def test_first_matching_skip_rule_is_recorded(case: str) -> None:
    changes, expected = PRECEDENCE[case]
    old = base_event()
    for change in changes:
        change(old)
    batch = [old]
    if case in ("intentional_beats_superseded", "superseded_beats_system"):
        newer = base_event()
        newer.update(event_id="DEG-NEWER", supersedes_event_id=old["event_id"])
        batch.append(newer)

    result = ingest_events(batch, rank_only_confirmed=case == "system_beats_not_confirmed")

    assert [str(s.reason) for s in result.skipped if s.event_id == old["event_id"]] == [expected]


def test_a_malformed_successor_does_not_supersede() -> None:
    old = base_event()
    broken = base_event()
    broken.update(event_id="DEG-BROKEN", supersedes_event_id=old["event_id"], event_key="bad")

    result = ingest_events([old, broken], rank_only_confirmed=False)

    assert [e.event_id for e in result.eligible] == [old["event_id"]]
    assert result.skipped == []


def test_every_decision_is_logged_with_a_reason_code() -> None:
    with capture_logs() as logs:
        result = ingest_events(PAYLOADS, rank_only_confirmed=False)

    reasons = sorted(entry["reason"] for entry in logs)
    quarantined = [str(q.reason) for q in result.quarantined]
    skipped = [str(s.reason) for s in result.skipped]
    assert reasons == sorted(quarantined + skipped)
