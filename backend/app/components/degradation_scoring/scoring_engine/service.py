# Scoring engine: normalises the criteria (T17), derives AHP weights (T18) and ranks the
# events with TOPSIS (T19), fixed-reference by default.

from collections.abc import Sequence

from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.scoring_engine.ahp import derive_weights, load_judgements
from app.components.degradation_scoring.scoring_engine.models import (
    Calibration,
    CriterionWeights,
    NormalisedSet,
    RawEvent,
    ScoringResult,
)
from app.components.degradation_scoring.scoring_engine.normalizer import normalise
from app.components.degradation_scoring.scoring_engine.topsis import topsis
from app.domain.severity_report import Dimension


class ScoringService:
    # Ranks events by severity from their raw features; rank() is the entry method.

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

    def rank(
        self,
        events: Sequence[RawEvent],
        active: Sequence[Dimension],
        *,
        system_id: str,
        release_id: str,
        calibration: Calibration | None = None,
    ) -> ScoringResult:
        # normalise -> AHP weights over the active criteria -> TOPSIS in the configured mode
        normalised = self._normalise(
            events, active, system_id=system_id, release_id=release_id, calibration=calibration
        )
        weights = self._criterion_weights(normalised.active_criteria)
        ranking = topsis(
            normalised.events,
            weights.weights,
            normalised.active_criteria,
            self._config.topsis_mode,
        )
        return ScoringResult(
            topsis_mode=self._config.topsis_mode,
            normalised=normalised,
            weights=weights,
            ranking=ranking,
        )

    def _normalise(
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

    def _criterion_weights(self, active: Sequence[Dimension]) -> CriterionWeights:
        # AHP weights of the configured version; CR > max raises; renormalised over active
        return derive_weights(
            load_judgements(self._config.weights_version),
            active,
            max_consistency_ratio=self._config.ahp_max_consistency_ratio,
        )
