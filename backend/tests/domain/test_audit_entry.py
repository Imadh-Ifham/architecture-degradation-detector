"""Contract tests for AuditEntryV1 (plan Section 3.3; used by M7 after PP1)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.audit_entry import AuditEntryV1, Verdict

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def example() -> dict[str, Any]:
    text = (FIXTURES / "audit_entry__valid.json").read_text(encoding="utf-8")
    payload: dict[str, Any] = json.loads(text)
    return payload


def test_example_entry_parses_and_round_trips() -> None:
    entry = AuditEntryV1.model_validate(example())

    assert entry.verdict is Verdict.REJECTED
    assert entry.prev_hash is None
    assert entry.model_dump(mode="json") == example()


@pytest.mark.parametrize("verdict", ["REJECTED", "NEEDS_INVESTIGATION"])
@pytest.mark.parametrize("note", [None, "", "   "])
def test_note_is_required_when_the_architect_disagrees(verdict: str, note: str | None) -> None:
    payload = example()
    payload.update(verdict=verdict, note=note)

    with pytest.raises(ValidationError, match="note"):
        AuditEntryV1.model_validate(payload)


def test_confirmed_needs_no_note() -> None:
    payload = example()
    payload.update(verdict="CONFIRMED", note=None)

    assert AuditEntryV1.model_validate(payload).note is None


def test_timestamp_must_carry_a_timezone() -> None:
    payload = example()
    payload["timestamp"] = "2026-10-20T09:30:00"

    with pytest.raises(ValidationError, match="timestamp"):
        AuditEntryV1.model_validate(payload)
