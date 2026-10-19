# Tests for the scoring_engine service on the fixture run: package export, normalisation,
# AHP weights and the TOPSIS ranking, all through rank().

import pytest

from app.components.degradation_scoring import scoring_engine
from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.scoring_engine.errors import (
    InconsistentJudgementsError,
    InvalidJudgementsError,
)
from app.components.degradation_scoring.scoring_engine.models import RawEvent, ScoringResult
from app.components.degradation_scoring.scoring_engine.service import ScoringService
from app.components.degradation_scoring.service import DegradationScoringService
from app.domain.severity_report import Dimension, NormalizationMode, WeightsProvenance
from tests.components.degradation_scoring.support import (
    adr_index_document,
    default_config,
    load_fixture,
)


def score_fixtures(with_adr: bool, config: C4Config | None = None) -> ScoringResult:
    run = DegradationScoringService(config or default_config()).run_features(
        load_fixture("events/fixture_events.v1.json"),
        load_fixture("graphs/fixture_release_package.v1.5.0.json"),
        run_id="t19",
        data_provenance="fixture",
        adr_document=adr_index_document() if with_adr else None,
    )
    events = run.scoring.normalised.events
    assert [e.event_id for e in events] == [e.event_id for e in run.features.events]
    return run.scoring


def test_package_exports_only_the_service() -> None:
    assert scoring_engine.__all__ == ["ScoringService"]
    assert scoring_engine.ScoringService is ScoringService


def test_fixture_run_is_small_n_with_hand_checked_values() -> None:
    result = score_fixtures(with_adr=False).normalised
    assert result.mode is NormalizationMode.MINMAX_SMALL_N  # 9 ranked events < 10
    assert len(result.events) == 9
    assert result.active_criteria == [Dimension.BLAST_RADIUS, Dimension.PERSISTENCE]
    by_id = {e.event_id[-4:]: e for e in result.events}
    # consecutive releases span 3..6; depth spans 2..4
    assert by_id["0002"].features["ps_consecutive_releases"] == 1.0
    assert by_id["0001"].features["ps_consecutive_releases"] == 0.0
    assert by_id["0001"].features["br_depth"] == 0.5
    assert by_id["0005"].features["br_depth"] == 0.0


def test_fixture_run_with_adr_keeps_the_designed_av() -> None:
    result = score_fixtures(with_adr=True).normalised
    assert Dimension.ADR_VIOLATION in result.active_criteria
    av = {e.event_id[-4:]: e.criteria[Dimension.ADR_VIOLATION] for e in result.events}
    assert av["0001"] == 1.0
    assert av["0006"] == pytest.approx(0.14)
    assert av["0007"] == pytest.approx(0.2)
    assert av["0002"] == 0.0


@pytest.mark.parametrize(
    ("with_adr", "expected"),
    [
        (False, {"blast_radius": 0.8304, "hotspot": 0.0, "adr_violation": 0.0,
                 "persistence": 0.1696}),
        (True, {"blast_radius": 0.6465, "hotspot": 0.0, "adr_violation": 0.2215,
                "persistence": 0.1320}),
    ],
)  # fmt: skip
def test_fixture_run_weights_cover_only_the_active_criteria(
    with_adr: bool, expected: dict[str, float]
) -> None:
    result = score_fixtures(with_adr)
    weights = result.weights

    assert weights.version == "ahp_v1"
    assert weights.provenance is WeightsProvenance.PROVISIONAL_AUTHOR_ELICITED
    assert weights.active_criteria == result.normalised.active_criteria
    assert sum(weights.weights.values()) == pytest.approx(1.0)
    assert weights.weights == pytest.approx({Dimension(k): v for k, v in expected.items()}, 1e-3)


def test_configured_ahp_settings_are_used() -> None:
    events = [RawEvent(event_id="e1", values={"br_fan_in_ratio": 0.1, "br_pagerank": 0.1,
              "br_betweenness": 0.1, "br_depth": 1.0, "ps_consecutive_releases": 2.0,
              "ps_growth_slope": 0.1})]  # fmt: skip
    active = [Dimension.BLAST_RADIUS, Dimension.PERSISTENCE]
    for config, error in [
        (default_config(ahp_max_consistency_ratio=0.01), InconsistentJudgementsError),
        (default_config(weights_version="ahp_v99"), InvalidJudgementsError),
    ]:
        with pytest.raises(error):
            ScoringService(config).rank(events, active, system_id="s", release_id="r")


def test_configured_feature_weights_are_used() -> None:
    config = default_config(ps_weight_consecutive_releases=1.0, ps_weight_growth_slope=0.0)
    for item in score_fixtures(with_adr=False, config=config).normalised.events:
        assert item.criteria[Dimension.PERSISTENCE] == item.features["ps_consecutive_releases"]


@pytest.mark.parametrize("with_adr", [False, True])
def test_fixture_ranking_is_fixed_reference_and_report_ready(with_adr: bool) -> None:
    result = score_fixtures(with_adr)
    ranking = result.ranking
    active = set(result.normalised.active_criteria)

    assert result.topsis_mode == "fixed_reference"
    assert [r.rank for r in ranking] == list(range(1, 10))
    assert [r.severity for r in ranking] == sorted((r.severity for r in ranking), reverse=True)
    assert {r.event_id for r in ranking} == {e.event_id for e in result.normalised.events}
    for ranked in ranking:
        assert 0 <= ranked.severity <= 1
        assert sum(ranked.contributions.values()) == pytest.approx(1.0)
        assert all(ranked.contributions[d] == 0 for d in Dimension if d not in active)


def test_configured_topsis_mode_is_used() -> None:
    classic = score_fixtures(with_adr=False, config=default_config(topsis_mode="classic"))
    fixed = score_fixtures(with_adr=False)
    by_id = {r.event_id: r.severity for r in fixed.ranking}

    assert classic.topsis_mode == "classic"
    assert any(r.severity != pytest.approx(by_id[r.event_id]) for r in classic.ranking)
