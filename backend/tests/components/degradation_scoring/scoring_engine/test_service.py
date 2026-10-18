# Tests for the scoring_engine service: package export and normalisation of the fixture run.

import pytest

from app.components.degradation_scoring import scoring_engine
from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.scoring_engine.models import NormalisedSet
from app.components.degradation_scoring.scoring_engine.service import ScoringService
from app.components.degradation_scoring.service import DegradationScoringService, scoring_inputs
from app.domain.severity_report import Dimension, NormalizationMode
from tests.components.degradation_scoring.support import (
    adr_index_document,
    default_config,
    load_fixture,
)


def normalise_fixtures(with_adr: bool, config: C4Config | None = None) -> NormalisedSet:
    config = config or default_config()
    run = DegradationScoringService(config).run_features(
        load_fixture("events/fixture_events.v1.json"),
        load_fixture("graphs/fixture_release_package.v1.5.0.json"),
        run_id="t17",
        data_provenance="fixture",
        adr_document=adr_index_document() if with_adr else None,
    )
    active, events = scoring_inputs(run.features)
    result = ScoringService(config).normalise(
        events, active, system_id=run.system_id, release_id=run.release_id
    )
    assert [e.event_id for e in result.events] == [e.event_id for e in run.features.events]
    return result


def test_package_exports_only_the_service() -> None:
    assert scoring_engine.__all__ == ["ScoringService"]
    assert scoring_engine.ScoringService is ScoringService


def test_fixture_run_is_small_n_with_hand_checked_values() -> None:
    result = normalise_fixtures(with_adr=False)
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
    result = normalise_fixtures(with_adr=True)
    assert Dimension.ADR_VIOLATION in result.active_criteria
    av = {e.event_id[-4:]: e.criteria[Dimension.ADR_VIOLATION] for e in result.events}
    assert av["0001"] == 1.0
    assert av["0006"] == pytest.approx(0.14)
    assert av["0007"] == pytest.approx(0.2)
    assert av["0002"] == 0.0


def test_configured_feature_weights_are_used() -> None:
    config = default_config(ps_weight_consecutive_releases=1.0, ps_weight_growth_slope=0.0)
    for item in normalise_fixtures(with_adr=False, config=config).events:
        assert item.criteria[Dimension.PERSISTENCE] == item.features["ps_consecutive_releases"]
