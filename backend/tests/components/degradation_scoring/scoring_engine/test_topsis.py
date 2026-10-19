# Tests for TOPSIS: hand-computed 3x3 examples in both modes, bounds, monotonicity,
# rank reversal (classic flips, fixed never does) and classic mode against pymcdm.

import math
from collections.abc import Sequence

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pymcdm.methods import TOPSIS
from pymcdm.normalizations import vector_normalization

from app.components.degradation_scoring.scoring_engine.models import (
    NormalisedEvent,
    RankedEvent,
    TopsisMode,
)
from app.components.degradation_scoring.scoring_engine.topsis import topsis
from app.domain.severity_report import Dimension

BR, EH, AV, PS = (
    Dimension.BLAST_RADIUS,
    Dimension.HOTSPOT,
    Dimension.ADR_VIOLATION,
    Dimension.PERSISTENCE,
)
THREE = [BR, EH, PS]
W3 = {BR: 0.5, EH: 0.3, AV: 0.0, PS: 0.2}
MODES: list[TopsisMode] = ["fixed_reference", "classic"]


def events(
    rows: Sequence[Sequence[float]], criteria: Sequence[Dimension] = THREE
) -> list[NormalisedEvent]:
    return [
        NormalisedEvent(
            event_id=f"E{i}", features={}, criteria=dict(zip(criteria, row, strict=True))
        )
        for i, row in enumerate(rows, start=1)
    ]


def severity(ranking: list[RankedEvent]) -> dict[str, float]:
    return {r.event_id: r.severity for r in ranking}


def test_fixed_reference_hand_computed_3x3() -> None:
    # w = (0.5, 0.3, 0.2), A+ = w, A- = 0.
    # E1 = (1, 0, 0.5): v = (0.5, 0, 0.1), d+ = sqrt(0.09 + 0.01) = 0.316228,
    #   d- = sqrt(0.25 + 0.01) = 0.509902, S = 0.509902 / 0.826130 = 0.617218
    # E2 = (0.5, 0.5, 0.5): d+ = d- = sqrt(0.095), S = 0.5
    # E3 = (0, 1, 1): d+ = 0.5, d- = sqrt(0.13) = 0.360555, S = 0.360555 / 0.860555 = 0.418980
    ranking = topsis(
        events([[1, 0, 0.5], [0.5, 0.5, 0.5], [0, 1, 1]]), W3, THREE, "fixed_reference"
    )

    assert [r.event_id for r in ranking] == ["E1", "E2", "E3"]
    assert [r.severity for r in ranking] == pytest.approx(
        [math.sqrt(0.26) / (math.sqrt(0.26) + math.sqrt(0.10)), 0.5,
         math.sqrt(0.13) / (math.sqrt(0.13) + 0.5)]
    )  # fmt: skip
    assert ranking[0].distance_ideal == pytest.approx(math.sqrt(0.10))
    assert ranking[0].distance_anti_ideal == pytest.approx(math.sqrt(0.26))
    # contributions of E1: (0.25, 0, 0.01) / 0.26
    assert ranking[0].contributions == pytest.approx(
        {BR: 0.25 / 0.26, EH: 0.0, AV: 0.0, PS: 0.01 / 0.26}
    )


def test_classic_hand_computed_3x3() -> None:
    # column norms are 5 (3-4-5 triangles): r = (0.6, 0, 0.8), (0.8, 0.6, 0), (0, 0.8, 0.6),
    # v = r * w: E1 = (0.3, 0, 0.16), E2 = (0.4, 0.18, 0), E3 = (0, 0.24, 0.12);
    # A+ = (0.4, 0.24, 0.16), A- = (0, 0, 0).
    # E1: d+ = sqrt(0.01 + 0.0576) = 0.26, d- = sqrt(0.09 + 0.0256) = 0.34, S = 0.34 / 0.6
    # E2: d+ = sqrt(0.0036 + 0.0256) = 0.170880, d- = sqrt(0.16 + 0.0324) = 0.438634
    # E3: d+ = sqrt(0.16 + 0.0016) = 0.401995, d- = sqrt(0.0576 + 0.0144) = 0.268328
    ranking = topsis(events([[3, 0, 4], [4, 3, 0], [0, 4, 3]]), W3, THREE, "classic")

    assert [r.event_id for r in ranking] == ["E2", "E1", "E3"]
    assert severity(ranking) == pytest.approx(
        {"E1": 0.34 / 0.6, "E2": 0.438634 / 0.609514, "E3": 0.268328 / 0.670323}, abs=1e-6
    )
    assert severity(ranking)["E1"] == pytest.approx(17 / 30)


def test_rank_reversal_classic_flips_fixed_reference_never_does() -> None:
    # E3 = (0, 0.2) is worse than E1 and E2 on every criterion, so it says nothing about
    # which of them is worse. Classic TOPSIS still swaps them, because E3 moves the anti-ideal
    # and the column norms. Fixed reference: E1 = 0.2, E2 = 0.3313 with or without E3.
    criteria, w = [BR, PS], {BR: 0.5, EH: 0.0, AV: 0.0, PS: 0.5}
    pair = events([[0.2, 0.2], [0.1, 0.5]], criteria)
    with_third = events([[0.2, 0.2], [0.1, 0.5], [0.0, 0.2]], criteria)

    before = severity(topsis(pair, w, criteria, "classic"))
    after = severity(topsis(with_third, w, criteria, "classic"))
    assert before["E2"] > before["E1"]
    assert after["E1"] > after["E2"]

    fixed_before = severity(topsis(pair, w, criteria, "fixed_reference"))
    fixed_after = severity(topsis(with_third, w, criteria, "fixed_reference"))
    assert fixed_before["E1"] == pytest.approx(0.2)
    assert fixed_before["E2"] == pytest.approx(
        math.sqrt(0.065) / (math.sqrt(0.065) + math.sqrt(0.265))
    )
    assert {k: fixed_after[k] for k in fixed_before} == fixed_before


unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
matrices = st.integers(min_value=1, max_value=8).flatmap(
    lambda n: st.lists(st.lists(unit, min_size=3, max_size=3), min_size=n, max_size=n)
)
weight_vectors = st.lists(st.floats(min_value=0.01, max_value=1.0), min_size=3, max_size=3).map(
    lambda raw: {BR: raw[0] / sum(raw), EH: raw[1] / sum(raw), AV: 0.0, PS: raw[2] / sum(raw)}
)


@settings(max_examples=200, deadline=None)
@given(rows=matrices, w=weight_vectors, mode=st.sampled_from(MODES))
def test_scores_lie_in_unit_interval_and_contributions_sum_to_one_or_zero(
    rows: list[list[float]], w: dict[Dimension, float], mode: TopsisMode
) -> None:
    ranking = topsis(events(rows), w, THREE, mode)

    assert [r.rank for r in ranking] == list(range(1, len(rows) + 1))
    for ranked in ranking:
        assert 0.0 <= ranked.severity <= 1.0
        total = sum(ranked.contributions.values())
        assert total == pytest.approx(1.0) or total == 0.0
        assert ranked.contributions[AV] == 0.0


@settings(max_examples=200, deadline=None)
@given(
    rows=matrices,
    w=weight_vectors,
    pick=st.integers(min_value=0),
    criterion=st.integers(min_value=0, max_value=2),
    raised=unit,
)
def test_fixed_reference_raising_a_criterion_never_lowers_the_score(
    rows: list[list[float]], w: dict[Dimension, float], pick: int, criterion: int, raised: float
) -> None:
    i = pick % len(rows)
    higher = [list(row) for row in rows]
    higher[i][criterion] = max(rows[i][criterion], raised)
    target = f"E{i + 1}"

    before = severity(topsis(events(rows), w, THREE, "fixed_reference"))[target]
    after = severity(topsis(events(higher), w, THREE, "fixed_reference"))[target]
    assert after >= before - 1e-12


@settings(max_examples=200, deadline=None)
@given(rows=matrices, extra=st.lists(unit, min_size=3, max_size=3), w=weight_vectors)
def test_fixed_reference_scores_never_depend_on_other_events(
    rows: list[list[float]], extra: list[float], w: dict[Dimension, float]
) -> None:
    before = severity(topsis(events(rows), w, THREE, "fixed_reference"))
    after = severity(topsis(events([*rows, extra]), w, THREE, "fixed_reference"))

    assert {k: after[k] for k in before} == before


@pytest.mark.filterwarnings("ignore:Alternatives with indices:UserWarning")
def test_classic_matches_pymcdm() -> None:
    # pymcdm's TOPSIS normalises with min-max by default; classic TOPSIS is vector normalisation
    rng = np.random.default_rng(42)
    reference = TOPSIS(normalization_function=vector_normalization)
    for _ in range(50):
        n = int(rng.integers(2, 15))
        x = rng.uniform(0.01, 1.0, size=(n, 3))
        raw = rng.uniform(0.05, 1.0, size=3)
        w = raw / raw.sum()
        expected = reference(x, w, np.ones(3, dtype=int))

        ours = severity(
            topsis(events(x.tolist()), dict(zip(THREE, w, strict=True)), THREE, "classic")
        )
        assert [ours[f"E{i}"] for i in range(1, n + 1)] == pytest.approx(expected, abs=1e-9)


def test_ties_are_broken_by_event_id() -> None:
    tied = [NormalisedEvent(event_id=name, features={}, criteria={BR: 0.5, EH: 0.5, PS: 0.5})
            for name in ("E-c", "E-a", "E-b")]  # fmt: skip

    for mode in MODES:
        assert [r.event_id for r in topsis(tied, W3, THREE, mode)] == ["E-a", "E-b", "E-c"]


def test_classic_with_identical_events_or_zero_column_scores_zero_without_nan() -> None:
    same = topsis(events([[0.4, 0.4, 0.4]] * 3), W3, THREE, "classic")
    zero_column = topsis(events([[0.0, 0.2, 0.5], [0.0, 0.6, 0.1]]), W3, THREE, "classic")

    assert [r.severity for r in same] == [0.0, 0.0, 0.0]  # d+ = d- = 0
    assert all(sum(r.contributions.values()) == 0.0 for r in same)
    assert all(not math.isnan(r.severity) for r in zero_column)
    assert all(r.contributions[BR] == 0.0 for r in zero_column)


def test_event_on_the_anti_ideal_point_scores_zero_and_contributes_nothing() -> None:
    (ranked,) = topsis(events([[0.0, 0.0, 0.0]]), W3, THREE, "fixed_reference")

    assert ranked.severity == 0.0
    assert set(ranked.contributions.values()) == {0.0}


def test_no_events_gives_an_empty_ranking() -> None:
    assert topsis([], W3, THREE, "fixed_reference") == []
