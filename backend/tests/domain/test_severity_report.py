# Contract tests for SeverityReportV1, the C4 output.
# A valid report, its AV-off and empty variants & one malformed variant per rule.
# Each malformed variant must fail with one specific error type, so a broken report
# names the rule it broke.

import copy
import logging
from collections.abc import Callable
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.domain.boundary import UNKNOWN_FIELD_IGNORED
from app.domain.severity_report import (
    ACTIVE_DIMENSIONS_MISMATCH,
    AUDIT_COUNTS_MISMATCH,
    CONTRIBUTIONS_MISMATCH,
    INACTIVE_DIMENSION_WEIGHTED,
    NORMALIZATION_BOUNDS_INVERTED,
    RANK_SEQUENCE_BROKEN,
    SEVERITY_ORDER_BROKEN,
    WEIGHTS_NOT_NORMALISED,
    DataProvenance,
    Dimension,
    SeverityReportV1,
    SkipReason,
)

Payload = dict[str, Any]


def record(event_id: str, rank: int, severity: float) -> Payload:
    # One ranked event with example's weights (0.41 + 0.33 + 0.16 + 0.10 = 1).
    return {
        "event_id": event_id,
        "anti_pattern_type": "CyclicDependency",
        "scope": "INSTANCE",
        "review_status": "PENDING",
        "context_tag": "GENUINE",
        "rank": rank,
        "severity": severity,
        "dimensions": {
            "blast_radius": {"raw": 0.62, "normalized": 0.74, "weight": 0.41,
                             "features": {"fan_in_ratio": 0.5, "depth": 3}},
            "hotspot": {"raw": 38.2, "normalized": 0.88, "weight": 0.33},
            "adr_violation": {"raw": 1.0, "normalized": 1.0, "weight": 0.16},
            "persistence": {"raw": 3, "normalized": 0.6, "weight": 0.10,
                            "features": {"growth_slope_available": False}},
        },
        "contributions": {"blast_radius": 0.31, "hotspot": 0.42,
                          "adr_violation": 0.17, "persistence": 0.10},
        "resolution": {"status": "exact", "confidence": 1.0},
        "explanation": "core.engine is in a cycle that 74 % of modules depend on [E1].",
        # 7 grounded of 8 claims: groundedness = 7 / 8 = 0.875.
        "audit": {"claims_total": 8, "claims_grounded": 7, "claims_unsupported": 1,
                  "claims_contradicted": 0, "groundedness": 0.875, "flagged": ["claim 4"]},
        "evidence": [{"id": "E1", "source": "metric", "text": "fan_in_ratio = 0.74",
                      "provenance": "features/blast_radius.py"}],
    }  # fmt: skip


def report() -> Payload:
    return {
        "run_id": "fixture-001",
        "system_id": "shopfront",
        "release_id": "v1.9.0",
        "data_provenance": "fixture",
        "active_dimensions": ["blast_radius", "hotspot", "adr_violation", "persistence"],
        "weights_version": "ahp_v1",
        "ahp_cr": 0.04,
        "normalization": "minmax_small_n",
        "normalization_bounds": {"fan_in_ratio": {"lower": 0.1, "upper": 0.9}},
        "resolution_rate": 0.9,
        "records": [record("evt_0472", 1, 0.781), record("evt_0101", 2, 0.5)],
        "quarantined": [{"event_id": None, "reason": "malformed_payload",
                         "detail": "event_key: string does not match pattern"}],
        "skipped": [{"event_id": "evt_0900", "reason": "system_scope_not_rankable"}],
    }  # fmt: skip


def without_adr(payload: Payload) -> Payload:
    # The AV-off run: ADR dimension inactive, the other weights renormalised to sum to 1.
    payload["active_dimensions"] = ["blast_radius", "hotspot", "persistence"]
    for item in payload["records"]:
        item["dimensions"]["adr_violation"] = {
            "raw": 0.0,
            "normalized": 0.0,
            "weight": 0.0,
            "active": False,
        }
        # 0.41 / 0.84, 0.33 / 0.84, 0.10 / 0.84, rounded so they still sum to 1 within 1e-6.
        item["dimensions"]["blast_radius"]["weight"] = 0.488095
        item["dimensions"]["hotspot"]["weight"] = 0.392857
        item["dimensions"]["persistence"]["weight"] = 0.119048
        item["contributions"] = {
            "blast_radius": 0.4,
            "hotspot": 0.5,
            "adr_violation": 0.0,
            "persistence": 0.1,
        }
    return payload  # fmt: skip


def test_example_report_parses_and_round_trips() -> None:
    parsed = SeverityReportV1.model_validate(report())

    assert parsed.schema_version == "1.0.0"
    assert parsed.data_provenance is DataProvenance.FIXTURE
    assert [r.rank for r in parsed.records] == [1, 2]
    assert parsed.records[0].audit is not None
    assert parsed.records[0].audit.groundedness == 0.875
    assert parsed.skipped[0].reason is SkipReason.SYSTEM_SCOPE_NOT_RANKABLE
    dumped = parsed.model_dump(mode="json")
    assert SeverityReportV1.model_validate(dumped) == parsed


def test_feature_values_keep_their_type() -> None:
    features = SeverityReportV1.model_validate(report()).records[0].dimensions
    persistence = features[Dimension.PERSISTENCE].features
    blast = features[Dimension.BLAST_RADIUS].features

    assert persistence["growth_slope_available"] is False
    assert blast["depth"] == 3.0
    assert type(blast["depth"]) is float


def test_example_report_validates_against_generated_schema() -> None:
    validator = Draft202012Validator(SeverityReportV1.model_json_schema())

    assert list(validator.iter_errors(report())) == []


def test_report_without_adr_dimension_is_valid() -> None:
    parsed = SeverityReportV1.model_validate(without_adr(report()))

    adr = parsed.records[0].dimensions[Dimension.ADR_VIOLATION]
    assert Dimension.ADR_VIOLATION not in parsed.active_dimensions
    assert adr.active is False
    assert adr.weight == 0


def test_rejected_events_are_listed_as_skipped() -> None:
    payload = report()
    payload["skipped"].append({"event_id": "evt_0311", "reason": "rejected"})

    skipped = SeverityReportV1.model_validate(payload).skipped

    assert skipped[-1].reason is SkipReason.REJECTED


def test_report_with_nothing_ranked_is_valid() -> None:
    payload = report()
    payload["records"] = []

    assert SeverityReportV1.model_validate(payload).records == []


def test_event_on_the_anti_ideal_point_contributes_zero_everywhere() -> None:
    payload = report()
    payload["records"][1]["contributions"] = dict.fromkeys(
        ("blast_radius", "hotspot", "adr_violation", "persistence"), 0.0
    )

    SeverityReportV1.model_validate(payload)


def test_unrated_record_needs_no_explanation_or_audit() -> None:
    payload = report()
    item = payload["records"][1]
    del item["explanation"], item["audit"], item["evidence"]

    parsed = SeverityReportV1.model_validate(payload).records[1]

    assert parsed.explanation is None
    assert parsed.audit is None


def test_unknown_field_is_ignored_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    payload = report()
    payload["generated_by"] = "a later version"

    with caplog.at_level(logging.WARNING):
        SeverityReportV1.model_validate(payload)

    assert any(rec.message == UNKNOWN_FIELD_IGNORED for rec in caplog.records)


def _set(path: list[str | int], value: Any) -> Callable[[Payload], None]:
    def mutate(payload: Payload) -> None:
        target: Any = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _delete(path: list[str | int]) -> Callable[[Payload], None]:
    def mutate(payload: Payload) -> None:
        target: Any = payload
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]

    return mutate


def _swap_ranks(payload: Payload) -> None:
    payload["records"][0]["rank"], payload["records"][1]["rank"] = 2, 1


def _raise_second_severity(payload: Payload) -> None:
    payload["records"][1]["severity"] = 0.9


def _mark_adr_inactive_in_one_record(payload: Payload) -> None:
    without_adr(payload)
    payload["active_dimensions"].append("adr_violation")


R0: list[str | int] = ["records", 0]

MALFORMED: dict[str, tuple[Callable[[Payload], None], str]] = {
    # Semantic rules: each raises its own reason code.
    "weights_sum_to_0.9": (_set([*R0, "dimensions", "persistence", "weight"], 0.0),
                           WEIGHTS_NOT_NORMALISED),
    "inactive_dimension_weighted": (_set([*R0, "dimensions", "adr_violation", "active"], False),
                                    INACTIVE_DIMENSION_WEIGHTED),
    "dimension_missing": (_delete([*R0, "dimensions", "hotspot"]), CONTRIBUTIONS_MISMATCH),
    "contributions_sum_to_0.9": (_set([*R0, "contributions", "persistence"], 0.0),
                                 CONTRIBUTIONS_MISMATCH),
    "audit_counts_do_not_add_up": (_set([*R0, "audit", "claims_unsupported"], 2),
                                   AUDIT_COUNTS_MISMATCH),
    "groundedness_is_not_grounded_over_total": (_set([*R0, "audit", "groundedness"], 0.9),
                                                AUDIT_COUNTS_MISMATCH),
    "ranks_out_of_order": (_swap_ranks, RANK_SEQUENCE_BROKEN),
    "rank_gap": (_set([*R0[:1], 1, "rank"], 3), RANK_SEQUENCE_BROKEN),
    "lower_rank_more_severe": (_raise_second_severity, SEVERITY_ORDER_BROKEN),
    "record_disagrees_on_active_dimensions": (_mark_adr_inactive_in_one_record,
                                              ACTIVE_DIMENSIONS_MISMATCH),
    "bounds_inverted": (_set(["normalization_bounds", "fan_in_ratio", "lower"], 0.95),
                        NORMALIZATION_BOUNDS_INVERTED),
    # Shape rules: pydantic's own error types.
    "severity_above_1": (_set([*R0, "severity"], 1.2), "less_than_equal"),
    "evidence_id_not_E_number": (_set([*R0, "evidence", 0, "id"], "X1"),
                                 "string_pattern_mismatch"),
    "unknown_skip_reason": (_set(["skipped", 0, "reason"], "too_boring"), "enum"),
    "unknown_review_status": (_set([*R0, "review_status"], "APPROVED"), "enum"),
    "run_id_missing": (_delete(["run_id"]), "missing"),
    "wrong_major_version": (_set(["schema_version"], "2.0.0"), "string_pattern_mismatch"),
    "zero_resolution_confidence": (_set([*R0, "resolution", "confidence"], 0.0),
                                   "greater_than"),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_report_fails_with_a_specific_error(case: str) -> None:
    mutate, expected_type = MALFORMED[case]
    payload = copy.deepcopy(report())
    mutate(payload)

    with pytest.raises(ValidationError) as caught:
        SeverityReportV1.model_validate(payload)

    assert [error["type"] for error in caught.value.errors()] == [expected_type]
