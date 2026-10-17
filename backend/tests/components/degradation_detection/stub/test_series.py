"""Pure series fixtures for the M4 tests: each has a known answer by construction."""

import json
from itertools import combinations
from pathlib import Path

import pytest

from app.components.degradation_detection.stub import StubService
from app.components.degradation_detection.stub.models import DEFAULT_SEED, SeriesFixture

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "series"


def fixtures(seed: int = DEFAULT_SEED) -> dict[str, SeriesFixture]:
    files = StubService().generate(seed).series_files
    return {
        name.removesuffix(".json"): SeriesFixture.model_validate(json.loads(text))
        for name, text in files.items()
    }


def kendall_s(values: list[float]) -> int:
    return sum((b > a) - (b < a) for i, a in enumerate(values) for b in values[i + 1 :])


def present(series: SeriesFixture) -> list[tuple[int, float]]:
    return [(t, v) for t, v in zip(series.time, series.values, strict=True) if v is not None]


def test_all_planned_fixtures_exist() -> None:
    assert set(fixtures()) == {
        "rising_exact",
        "rising_noisy",
        "rising_outlier",
        "rising_gap",
        "falling_exact",
        "flat",
        "noisy_no_trend",
        "step",
        "with_ties",
        "short_n5",
        "short_n7",
    }


def test_every_fixture_has_one_value_per_time_point() -> None:
    for name, series in fixtures().items():
        assert series.name == name
        assert len(series.time) == len(series.values)
        assert list(series.time) == sorted(set(series.time))


def test_rising_exact_has_the_planted_slope_between_every_pair() -> None:
    series = fixtures()["rising_exact"]

    assert series.planted_slope == 0.8
    for (t1, v1), (t2, v2) in combinations(present(series), 2):
        assert (v2 - v1) / (t2 - t1) == pytest.approx(0.8)


def test_rising_gap_keeps_the_null_and_the_real_time_axis() -> None:
    series = fixtures()["rising_gap"]

    assert series.values.count(None) == 1
    assert list(series.time) == list(range(10))
    for (t1, v1), (t2, v2) in combinations(present(series), 2):
        assert (v2 - v1) / (t2 - t1) == pytest.approx(0.8)


def test_rising_outlier_differs_from_the_line_in_one_point() -> None:
    exact, outlier = fixtures()["rising_exact"], fixtures()["rising_outlier"]

    different = [a != b for a, b in zip(exact.values, outlier.values, strict=True)]

    assert different.count(True) == 1
    assert outlier.planted_slope == 0.8


def test_rising_noisy_is_clearly_increasing_but_not_monotone() -> None:
    series = fixtures()["rising_noisy"]
    values = [v for _, v in present(series)]

    assert len(values) == 12
    assert 50 <= kendall_s(values) < 66  # 66 would be a perfectly ordered series
    assert series.expected_trend == "increasing"


def test_falling_exact_is_strictly_decreasing() -> None:
    series = fixtures()["falling_exact"]
    values = [v for _, v in present(series)]

    assert kendall_s(values) == -45
    assert series.expected_trend == "decreasing"
    assert series.planted_slope == -0.5


def test_flat_is_constant() -> None:
    series = fixtures()["flat"]

    assert len(set(series.values)) == 1
    assert series.expected_trend == "none"
    assert series.planted_slope == 0


@pytest.mark.parametrize("seed", [DEFAULT_SEED, 1, 2, 3])
def test_noisy_no_trend_is_balanced_for_any_seed(seed: int) -> None:
    series = fixtures(seed)["noisy_no_trend"]
    values = [v for _, v in present(series)]

    assert len(set(values)) == 10
    assert abs(kendall_s(values)) <= 3
    assert series.expected_trend == "none"


def test_step_has_two_levels() -> None:
    values = list(fixtures()["step"].values)

    assert values[:5] == [values[0]] * 5 and values[5:] == [values[5]] * 5
    assert values[0] is not None and values[5] is not None
    assert values[5] > values[0]


def test_with_ties_has_ties_and_at_least_ten_points() -> None:
    values = [v for _, v in present(fixtures()["with_ties"])]

    assert len(values) >= 10
    assert len(set(values)) < len(values)
    assert values == sorted(values)


def test_short_series_are_strictly_increasing_but_below_the_minimum_length() -> None:
    for name, n in (("short_n5", 5), ("short_n7", 7)):
        values = [v for _, v in present(fixtures()[name])]

        assert len(values) == n
        assert kendall_s(values) == n * (n - 1) // 2


def test_series_are_deterministic() -> None:
    assert StubService().generate(5).series_files == StubService().generate(5).series_files


def test_committed_fixtures_match_the_generator() -> None:
    """Snapshot. Fix with `uv run python -m scripts.c3 stub series` and review the diff."""
    rendered = StubService().generate(DEFAULT_SEED).series_files

    for name, text in rendered.items():
        path = FIXTURE_DIR / name
        assert path.exists(), f"{name} has not been generated"
        assert path.read_text(encoding="utf-8") == text, f"{name} is stale"
    assert {p.name for p in FIXTURE_DIR.glob("*.json")} == set(rendered)
