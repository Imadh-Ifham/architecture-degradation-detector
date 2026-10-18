# Scoring engine: normalises the criteria, derives AHP weights and ranks events with
# fixed-reference TOPSIS . T17: normalisation and criterion values.

from collections.abc import Sequence

from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.scoring_engine.models import (
    Calibration,
    NormalisedSet,
    RawEvent,
)
from app.components.degradation_scoring.scoring_engine.normalizer import normalise
from app.domain.severity_report import Dimension


class ScoringService:
    # Ranks events by severity from their features; the entry method becomes rank() in T19.

    def __init__(self, config: C4Config) -> None:
        self._config = config
        self._weights = {
            Dimension.BLAST_RADIUS: {
                "br_fan_in_ratio": config.br_weight_fan_in_ratio,
                "br_pagerank": config.br_weight_pagerank,
                "br_betweenness": config.br_weight_betweenness,
                "br_depth": config.br_weight_depth,
            },
            Dimension.HOTSPOT: {
                "eh_churn_decayed": config.eh_weight_churn_decayed,
                "eh_authors": config.eh_weight_authors,
                "eh_coupling": config.eh_weight_coupling,
                "eh_bugfix_ratio": config.eh_weight_bugfix_ratio,
            },
            Dimension.PERSISTENCE: {
                "ps_consecutive_releases": config.ps_weight_consecutive_releases,
                "ps_growth_slope": config.ps_weight_growth_slope,
            },
        }

    def normalise(
        self,
        events: Sequence[RawEvent],
        active: Sequence[Dimension],
        *,
        system_id: str,
        release_id: str,
        calibration: Calibration | None = None,
    ) -> NormalisedSet:
        # one call = one (system, release); a given calibration is applied unchanged
        return normalise(
            events,
            active,
            system_id=system_id,
            release_id=release_id,
            weights=self._weights,
            lower_percentile=self._config.winsor_lower_percentile,
            upper_percentile=self._config.winsor_upper_percentile,
            small_n_threshold=self._config.small_n_threshold,
            calibration=calibration,
        )
