"""Contract tests for ReleasePackageV1.1, the C2 -> C3 input (plan Section 3.1)."""

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.release_package import ArchitectureStyle, ReleasePackageV1

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"

# Invalid fixture -> the error code M1 will report for it. Shape errors keep pydantic's own
# type (M1 maps them all to INPUT_SCHEMA_INVALID); semantic errors carry a C3 reason code.
INVALID = {
    "duplicate_element_id": "DUPLICATE_ELEMENT_ID",
    "dangling_dependency": "DANGLING_DEPENDENCY",
    "no_elements": "too_short",
    "unknown_style": "enum",
    "missing_release_id": "missing",
    "naive_released_at": "timezone_aware",
    "confidence_out_of_range": "less_than_equal",
    "wrong_major_version": "string_pattern_mismatch",
}


def load(name: str) -> dict[str, Any]:
    text = (FIXTURES / f"release_package__{name}.json").read_text(encoding="utf-8")
    payload: dict[str, Any] = json.loads(text)
    return payload


def unknown_field_records(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str]]:
    return [
        (r.__dict__["model"], r.__dict__["field"])
        for r in caplog.records
        if r.getMessage() == "UNKNOWN_FIELD_IGNORED"
    ]


def test_full_package_parses() -> None:
    package = ReleasePackageV1.model_validate(load("valid_full"))

    assert package.system_id == "shopfront"
    assert package.architecture_style is ArchitectureStyle.MICROSERVICES
    assert package.released_at.utcoffset() is not None
    assert [e.id for e in package.elements] == ["order-service", "payment-service"]
    assert package.elements[0].aliases == ["order-svc"]
    assert package.dependencies[0].from_ == "order-service"
    assert package.dependencies[0].to == "payment-service"
    assert package.dependencies[0].count == 3
    assert package.datastore_access is not None
    assert package.datastore_access[0].datastore == "orders_db"
    assert package.intent[0].decision_kind == "split"
    assert package.provenance.c2_validation_ref == "c2://shopfront/v1.4.0"


def test_null_metric_stays_null() -> None:
    package = ReleasePackageV1.model_validate(load("valid_full"))

    assert package.elements[1].metrics == {"lcom": None}


def test_minimal_package_gets_defaults() -> None:
    package = ReleasePackageV1.model_validate(load("valid_minimal"))

    assert package.architecture_style is ArchitectureStyle.GENERIC
    assert package.dependencies == []
    assert package.intent == []
    # Missing optional v3 inputs stay None so detectors can tell "not supplied" from "empty".
    assert package.datastore_access is None
    assert package.delegation is None
    assert package.elements[0].name is None
    assert package.elements[0].size is None


@pytest.mark.parametrize(("fixture", "code"), sorted(INVALID.items()))
def test_invalid_package_is_rejected_with_its_code(fixture: str, code: str) -> None:
    with pytest.raises(ValidationError) as caught:
        ReleasePackageV1.model_validate(load(f"invalid_{fixture}"))

    assert code in {error["type"] for error in caught.value.errors()}


def test_every_invalid_fixture_has_an_expected_code() -> None:
    on_disk = {p.stem.split("__invalid_")[1] for p in FIXTURES.glob("release_package__invalid_*")}

    assert on_disk == set(INVALID)


def test_self_loops_and_duplicate_edges_are_left_to_m1_normalisation() -> None:
    payload = load("valid_minimal")
    edge = {"from": "a", "to": "a", "types": ["call"], "count": 1}
    payload["dependencies"] = [edge, edge]

    assert len(ReleasePackageV1.model_validate(payload).dependencies) == 2


def test_unknown_fields_are_ignored_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    payload = load("valid_minimal")
    payload["build_number"] = 77
    payload["elements"][0]["colour"] = "red"

    with caplog.at_level(logging.WARNING, logger="app.domain"):
        package = ReleasePackageV1.model_validate(payload)

    assert not hasattr(package, "build_number")
    assert sorted(unknown_field_records(caplog)) == [
        ("Element", "colour"),
        ("ReleasePackageV1", "build_number"),
    ]


def test_known_fields_and_aliases_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    payload = load("valid_full")
    payload["intent"][0]["adr_ref"] = payload["intent"][0].pop("ref")

    with caplog.at_level(logging.WARNING, logger="app.domain"):
        ReleasePackageV1.model_validate(payload)

    assert unknown_field_records(caplog) == []


def test_adr_ref_is_accepted_as_alias_of_ref() -> None:
    payload = load("valid_full")
    payload["intent"][0]["adr_ref"] = payload["intent"][0].pop("ref")

    assert ReleasePackageV1.model_validate(payload).intent[0].ref == "ADR-021"


def test_delegation_items_are_kept_as_supplied() -> None:
    payload = load("valid_minimal")
    payload["delegation"] = [{"anything": "c1 sends", "n": 2}]

    assert ReleasePackageV1.model_validate(payload).delegation == [{"anything": "c1 sends", "n": 2}]


def test_earlier_minor_version_is_still_accepted() -> None:
    payload = load("valid_minimal")
    payload["schema_version"] = "1.0.0"

    assert ReleasePackageV1.model_validate(payload).schema_version == "1.0.0"
