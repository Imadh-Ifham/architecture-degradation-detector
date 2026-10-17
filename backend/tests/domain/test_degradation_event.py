"""Contract tests for DegradationEventV2, the C3 -> C4 output (plan Section 3.2)."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.domain.degradation_event import (
    ContextStage,
    DegradationEventV2,
    Lifecycle,
    ReviewStatus,
    Scope,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def example() -> dict[str, Any]:
    text = (FIXTURES / "degradation_event__valid_instance.json").read_text(encoding="utf-8")
    payload: dict[str, Any] = json.loads(text)
    return payload


def test_example_event_parses_and_round_trips() -> None:
    event = DegradationEventV2.model_validate(example())

    assert event.scope is Scope.INSTANCE
    assert event.lifecycle is Lifecycle.GROWING
    assert event.affected_metrics[0].q_value == 0.0081
    assert event.affected_metrics[0].series[1].value is None
    assert event.model_dump(mode="json") == example()


def test_example_event_validates_against_generated_schema() -> None:
    validator = Draft202012Validator(DegradationEventV2.model_json_schema())

    assert list(validator.iter_errors(example())) == []


def test_generated_schema_rejects_an_incomplete_event() -> None:
    payload = example()
    del payload["anti_pattern_type"]
    validator = Draft202012Validator(DegradationEventV2.model_json_schema())

    assert [error.validator for error in validator.iter_errors(payload)] == ["required"]


def test_pp1_export_shape_is_context_disabled_and_review_pending() -> None:
    payload = example()
    del payload["review_status"]

    event = DegradationEventV2.model_validate(payload)

    assert event.context.stage is ContextStage.DISABLED
    assert event.review_status is ReviewStatus.PENDING


def test_instance_scope_needs_an_instance_id() -> None:
    payload = example()
    payload["instance_id"] = None

    with pytest.raises(ValidationError, match="instance_id"):
        DegradationEventV2.model_validate(payload)


def test_element_scope_needs_element_and_lineage() -> None:
    payload = example()
    payload["scope"] = "ELEMENT"

    with pytest.raises(ValidationError, match="element_id"):
        DegradationEventV2.model_validate(payload)

    payload["element_id"] = "catalog"
    payload["lineage_id"] = "LIN-0003"
    assert DegradationEventV2.model_validate(payload).scope is Scope.ELEMENT


def test_system_scope_needs_no_subject_ids() -> None:
    payload = example()
    payload.update(scope="SYSTEM", instance_id=None, members=[], lifecycle=None)

    assert DegradationEventV2.model_validate(payload).scope is Scope.SYSTEM


def test_event_key_must_be_a_sha256_digest() -> None:
    payload = example()
    payload["event_key"] = "sha256:5b0c"

    with pytest.raises(ValidationError, match="event_key"):
        DegradationEventV2.model_validate(payload)
