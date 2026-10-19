# Tests for AHP: Saaty's (1990) published example, hand-computed consistent matrices,
# matrix validation, the CR gate, renormalisation over active criteria and the weights file.

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.components.degradation_scoring.scoring_engine.ahp import (
    RANDOM_INDEX,
    check_consistency,
    derive_weights,
    load_judgements,
    parse_matrix,
    principal_weights,
    renormalise,
)
from app.components.degradation_scoring.scoring_engine.errors import (
    InconsistentJudgementsError,
    InvalidJudgementsError,
)
from app.components.degradation_scoring.scoring_engine.models import AhpResult
from app.domain.severity_report import Dimension, WeightsProvenance

BR, EH, AV, PS = (
    Dimension.BLAST_RADIUS,
    Dimension.HOTSPOT,
    Dimension.ADR_VIOLATION,
    Dimension.PERSISTENCE,
)
ALL = [BR, EH, AV, PS]

# Saaty, T. L. (1990). How to make a decision: The analytic hierarchy process.
# European Journal of Operational Research 48(1), 9-26. House example, 8 criteria: size,
# transportation, neighbourhood, age, yard, modern facilities, condition, financing.
SAATY_1990_HOUSE = [
    ["1", "5", "3", "7", "6", "6", "1/3", "1/4"],
    ["1/5", "1", "1/3", "5", "3", "3", "1/5", "1/7"],
    ["1/3", "3", "1", "6", "3", "4", "6", "1/5"],
    ["1/7", "1/5", "1/6", "1", "1/3", "1/4", "1/7", "1/8"],
    ["1/6", "1/3", "1/3", "3", "1", "1/2", "1/5", "1/6"],
    ["1/6", "1/3", "1/4", "4", "2", "1", "1/5", "1/6"],
    ["3", "5", "1/6", "7", "5", "5", "1", "1/2"],
    ["4", "7", "5", "8", "6", "6", "2", "1"],
]
# published: weights .173 .054 .188 .018 .031 .036 .167 .333, lambda_max 9.669, CI .238, CR .169
SAATY_1990_WEIGHTS = [0.17, 0.05, 0.19, 0.02, 0.03, 0.04, 0.17, 0.33]

# perfectly consistent (a_ik = a_ij * a_jk): weights 4/7, 2/7, 1/7, lambda_max = n = 3
CONSISTENT_3 = [["1", "2", "4"], ["1/2", "1", "2"], ["1/4", "1/2", "1"]]

# the provisional ahp_v1 matrix, criteria in report order
DRAFT = [["1", "2", "3", "4"], ["1/2", "1", "2", "3"], ["1/3", "1/2", "1", "2"],
         ["1/4", "1/3", "1/2", "1"]]  # fmt: skip


def weights_file(directory: Path, **overrides: Any) -> Path:
    payload = {
        "version": "ahp_test",
        "criteria": [d.value for d in ALL],
        "scale": "saaty_1_9",
        "matrix": DRAFT,
        "elicited_by": "Test Author",
        "date": "2026-10-18",
        "provenance": "provisional-author-elicited",
    } | overrides
    path = directory / f"{payload['version']}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_saaty_1990_house_example_reproduces_weights_and_cr() -> None:
    result = principal_weights(parse_matrix(SAATY_1990_HOUSE))

    assert [round(w, 2) for w in result.weights] == SAATY_1990_WEIGHTS
    assert round(result.lambda_max, 2) == 9.67
    assert round(result.consistency_index, 2) == 0.24
    assert round(result.consistency_ratio, 2) == 0.17
    assert sum(result.weights) == pytest.approx(1.0)


def test_saaty_house_example_is_refused_by_the_consistency_gate() -> None:
    result = principal_weights(parse_matrix(SAATY_1990_HOUSE))

    with pytest.raises(InconsistentJudgementsError, match=r"CR = 0\.169 > 0\.1"):
        check_consistency(result, 0.10)


def test_consistent_matrix_has_hand_computed_weights_and_cr_zero() -> None:
    result = principal_weights(parse_matrix(CONSISTENT_3))

    assert result.weights == pytest.approx([4 / 7, 2 / 7, 1 / 7], abs=1e-12)
    assert result.lambda_max == pytest.approx(3.0, abs=1e-12)
    assert result.consistency_index == pytest.approx(0.0, abs=1e-12)
    assert result.consistency_ratio == pytest.approx(0.0, abs=1e-12)


def test_one_or_two_criteria_are_always_consistent() -> None:
    two = principal_weights(parse_matrix([["1", "3"], ["1/3", "1"]]))
    one = principal_weights(parse_matrix([["1"]]))

    assert two.weights == pytest.approx([0.75, 0.25])
    assert two.consistency_ratio == 0.0
    assert one.weights == [1.0]
    assert one.consistency_ratio == 0.0


def test_random_index_is_saatys_table() -> None:
    assert RANDOM_INDEX[3] == 0.58  # §5.6
    assert RANDOM_INDEX[4] == 0.90  # §5.6
    assert list(RANDOM_INDEX.values()) == [0, 0, 0.58, 0.90, 1.12, 1.24, 1.32, 1.41, 1.45, 1.49]


def test_cr_equal_to_the_maximum_passes() -> None:
    at_max = AhpResult(weights=[1.0], lambda_max=1.0, consistency_index=0.0, consistency_ratio=0.1)

    check_consistency(at_max, 0.10)


@pytest.mark.parametrize(
    ("matrix", "message"),
    [
        ([["1", "2"], ["2", "1"]], "not reciprocal"),
        ([["1", "2"], ["1/3", "1"]], "not reciprocal"),
        ([["2", "1"], ["1", "1/2"]], "diagonal"),
        ([["1", "10"], ["1/10", "1"]], "off the scale"),
        ([["1", "1.5"], ["2/3", "1"]], "off the scale"),
        ([["1", "0"], ["0", "1"]], "off the scale"),
        ([["1", "two"], ["1/2", "1"]], "not a number"),
        ([["1", "1/0"], ["0", "1"]], "not a number"),
        ([["1", "2"], ["1/2"]], "square"),
        ([], "square"),
        ([["1"] * 11 for _ in range(11)], "square"),
    ],
)
def test_invalid_matrix_is_rejected(matrix: list[list[str]], message: str) -> None:
    with pytest.raises(InvalidJudgementsError, match=message):
        principal_weights(parse_matrix(matrix))


def test_renormalise_rescales_active_weights_to_sum_one() -> None:
    weights = {BR: 0.4, EH: 0.3, AV: 0.2, PS: 0.1}

    assert renormalise(weights, [BR, EH, PS]) == pytest.approx(
        {BR: 0.5, EH: 0.375, AV: 0.0, PS: 0.125}
    )
    assert renormalise(weights, ALL) == pytest.approx(weights)
    assert list(renormalise(weights, [PS, BR])) == ALL  # report order, all four listed
    with pytest.raises(ValueError, match="active"):
        renormalise(weights, [])


def test_provisional_ahp_v1_loads_with_its_provenance_and_cr() -> None:
    judgements = load_judgements("ahp_v1")
    result = derive_weights(judgements, ALL, max_consistency_ratio=0.10)

    assert judgements.provenance is WeightsProvenance.PROVISIONAL_AUTHOR_ELICITED
    assert result.provenance is WeightsProvenance.PROVISIONAL_AUTHOR_ELICITED
    assert result.elicited_by == "Dahami"
    assert result.version == "ahp_v1"
    assert round(result.consistency_ratio, 2) == 0.01  # lambda_max 4.031
    assert {d: round(w, 2) for d, w in result.weights.items()} == {
        BR: 0.47, EH: 0.28, AV: 0.16, PS: 0.10
    }  # fmt: skip
    assert result.weights == result.elicited


@pytest.mark.parametrize(
    ("active", "expected"),
    [
        ([BR, EH, PS], {BR: 0.5564, EH: 0.3300, AV: 0.0, PS: 0.1136}),  # real PP1 runs
        ([BR, AV, PS], {BR: 0.6465, EH: 0.0, AV: 0.2215, PS: 0.1320}),  # fixtures with ADRs
        ([BR, PS], {BR: 0.8304, EH: 0.0, AV: 0.0, PS: 0.1696}),  # fixtures without ADRs
    ],
)
def test_inactive_criteria_get_zero_and_the_rest_renormalise_proportionally(
    active: list[Dimension], expected: dict[Dimension, float]
) -> None:
    result = derive_weights(load_judgements("ahp_v1"), active, max_consistency_ratio=0.10)
    full = derive_weights(load_judgements("ahp_v1"), ALL, max_consistency_ratio=0.10)

    assert sum(result.weights.values()) == pytest.approx(1.0)
    assert result.weights == pytest.approx(expected, abs=1e-4)
    assert result.active_criteria == active
    assert result.elicited == full.elicited
    assert result.consistency_ratio == full.consistency_ratio  # CR of the 4x4 judgements
    assert result.weights[BR] / result.weights[PS] == pytest.approx(
        full.elicited[BR] / full.elicited[PS]
    )


def test_criteria_are_matched_by_name_not_position(tmp_path: Path) -> None:
    # same judgements written with PS first: matrix rows and columns reordered with it
    order = [3, 0, 1, 2]
    path = weights_file(
        tmp_path,
        criteria=[ALL[i].value for i in order],
        matrix=[[DRAFT[i][j] for j in order] for i in order],
    )
    reordered = derive_weights(
        load_judgements("ahp_test", path.parent), ALL, max_consistency_ratio=0.1
    )
    original = derive_weights(load_judgements("ahp_v1"), ALL, max_consistency_ratio=0.1)

    assert list(reordered.weights) == ALL
    assert reordered.weights == pytest.approx(original.weights)


def test_configured_maximum_cr_is_enforced(tmp_path: Path) -> None:
    judgements = load_judgements("ahp_test", weights_file(tmp_path).parent)

    with pytest.raises(InconsistentJudgementsError):
        derive_weights(judgements, ALL, max_consistency_ratio=0.01)


@pytest.mark.parametrize(
    "overrides",
    [
        {"elicited_by": "Dahami "},
        {"elicited_by": ""},
        {"provenance": "made-up"},
        {"criteria": ["blast_radius", "hotspot", "hotspot", "persistence"]},
        {"criteria": ["blast_radius", "hotspot", "persistence"]},
        {"matrix": CONSISTENT_3},
        {"scale": "linear"},
        {"date": "yesterday"},
        {"extra": 1},
    ],
)
def test_unusable_weights_file_is_rejected(tmp_path: Path, overrides: dict[str, Any]) -> None:
    weights_file(tmp_path, **overrides)

    with pytest.raises(InvalidJudgementsError, match="cannot load AHP weights"):
        load_judgements("ahp_test", tmp_path)


def test_unknown_or_mislabelled_version_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InvalidJudgementsError, match="cannot load"):
        load_judgements("ahp_v99")
    weights_file(tmp_path).rename(tmp_path / "ahp_other.json")
    with pytest.raises(InvalidJudgementsError, match="declares version ahp_test"):
        load_judgements("ahp_other", tmp_path)


def test_weights_decision_is_logged_with_a_reason() -> None:
    with capture_logs() as logs:
        derive_weights(load_judgements("ahp_v1"), [BR, EH, PS], max_consistency_ratio=0.1)

    (entry,) = [e for e in logs if e.get("reason") == "ahp_weights"]
    assert entry["provenance"] == "provisional-author-elicited"
    assert entry["inactive"] == ["adr_violation"]
    assert entry["consistency_ratio"] == pytest.approx(0.0115, abs=1e-4)


def test_fractions_are_exact() -> None:
    assert parse_matrix([["1/3"]]) == [[Fraction(1, 3)]]
