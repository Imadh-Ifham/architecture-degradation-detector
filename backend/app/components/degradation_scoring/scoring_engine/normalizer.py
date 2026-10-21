# Normaliser: puts every feature on [0, 1] and combines them into one value per criterion.
# Robust min-max per system (winsorised P5-P95), small-n fallback, calibration freeze;
# a feature with zero range is left out of its criterion's mean (C4-ADR-015)

from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import structlog
from pydantic import ValidationError

from app.components.degradation_scoring.scoring_engine.errors import CalibrationError
from app.components.degradation_scoring.scoring_engine.models import (
    Calibration,
    FeatureBounds,
    NormalisedEvent,
    NormalisedSet,
    RawEvent,
)
from app.domain.severity_report import Dimension, NormalizationMode

log = structlog.get_logger(__name__)

# features scaled per criterion; AV is already on a fixed 0-1 scale and passes through
FEATURES: dict[Dimension, tuple[str, ...]] = {
    Dimension.BLAST_RADIUS: ("br_fan_in_ratio", "br_pagerank", "br_betweenness", "br_depth"),
    Dimension.HOTSPOT: ("eh_churn_decayed", "eh_authors", "eh_coupling", "eh_bugfix_ratio"),
    Dimension.PERSISTENCE: ("ps_consecutive_releases", "ps_growth_slope"),
}
AV_FEATURE = "av_weight"
SPARSE_FALLBACK = "sparse_minmax"
ZERO_RANGE = "zero_range"

Weights = Mapping[Dimension, Mapping[str, float]]


def required_keys(criteria: Sequence[Dimension]) -> list[str]:
    # every raw value the active criteria need, scaled ones first
    keys = [key for criterion in criteria for key in FEATURES.get(criterion, ())]
    return [*keys, AV_FEATURE] if Dimension.ADR_VIOLATION in criteria else keys


def fit_bounds(
    values: Sequence[float], *, robust: bool, lower_percentile: float, upper_percentile: float
) -> FeatureBounds:
    # robust: [P_lower, P_upper] (numpy linear percentiles); else plain [min, max].
    # If P_lower = P_upper but the values differ, plain min-max keeps the rare signal;
    # if all values are equal the feature is marked zero_range (C4-ADR-015).
    data = np.asarray(values, dtype=float)
    low, high = float(data.min()), float(data.max())
    if low == high:
        return FeatureBounds(lower=low, upper=high, fallback=ZERO_RANGE)
    if not robust:
        return FeatureBounds(lower=low, upper=high)
    p_low, p_high = (float(p) for p in np.percentile(data, [lower_percentile, upper_percentile]))
    if p_low == p_high and low < high:
        return FeatureBounds(lower=low, upper=high, fallback=SPARSE_FALLBACK)
    return FeatureBounds(lower=p_low, upper=p_high)


def zero_range(bounds: FeatureBounds) -> bool:
    # also true for a frozen calibration saved before the zero_range mark existed
    return bounds.upper == bounds.lower


def scale(value: float, bounds: FeatureBounds) -> float:
    # (x - lower) / (upper - lower) clipped to [0, 1]; a zero-range feature has no scale
    if zero_range(bounds):
        raise ValueError(f"zero range [{bounds.lower}, {bounds.upper}]: leave the feature out")
    return min(max((value - bounds.lower) / (bounds.upper - bounds.lower), 0.0), 1.0)


def fit_calibration(
    rows: Sequence[Mapping[str, float]],
    keys: Sequence[str],
    *,
    system_id: str,
    release_id: str,
    lower_percentile: float,
    upper_percentile: float,
    small_n_threshold: int,
) -> Calibration:
    # fits every key's bounds on this run's events; fewer than small_n_threshold -> min-max
    robust = len(rows) >= small_n_threshold
    bounds: dict[str, FeatureBounds] = {}
    if rows:
        for key in keys:
            bounds[key] = fit_bounds(
                [row[key] for row in rows],
                robust=robust,
                lower_percentile=lower_percentile,
                upper_percentile=upper_percentile,
            )
            if bounds[key].fallback == SPARSE_FALLBACK:
                log.info("normalisation_fallback", reason=SPARSE_FALLBACK, feature=key)
    return Calibration(
        system_id=system_id,
        release_id=release_id,
        mode=NormalizationMode.ROBUST_MINMAX if robust else NormalizationMode.MINMAX_SMALL_N,
        n_events=len(rows),
        lower_percentile=lower_percentile,
        upper_percentile=upper_percentile,
        bounds=bounds,
    )


def check_calibration(calibration: Calibration, keys: Sequence[str], system_id: str) -> None:
    # a frozen scale must come from the same system and cover every feature of this run
    if calibration.system_id != system_id:
        raise CalibrationError(
            f"calibration is for system {calibration.system_id!r}, not {system_id!r}"
        )
    missing = sorted(set(keys) - set(calibration.bounds))
    if missing:
        raise CalibrationError(f"calibration has no bounds for {missing}")


def criterion_value(features: Mapping[str, float], weights: Mapping[str, float]) -> float:
    # weighted mean of the criterion's normalised features (CLAUDE.md §5.1, §5.2, §5.4) over
    # the features present; zero-range features are absent, and none left gives 0 (C4-ADR-015)
    if sum(weights.values()) <= 0:
        raise ValueError(f"feature weights must sum to more than 0, got {dict(weights)}")
    present = {key: weight for key, weight in weights.items() if key in features}
    total = sum(present.values())
    if total <= 0:
        return 0.0
    return sum(weight * features[key] for key, weight in present.items()) / total


def normalise(
    events: Sequence[RawEvent],
    active: Sequence[Dimension],
    *,
    system_id: str,
    release_id: str,
    weights: Weights,
    lower_percentile: float,
    upper_percentile: float,
    small_n_threshold: int,
    calibration: Calibration | None = None,
) -> NormalisedSet:
    # fits the scale on these events, or applies a loaded one (frozen) unchanged
    criteria = [criterion for criterion in Dimension if criterion in active]
    keys = [key for criterion in criteria for key in FEATURES.get(criterion, ())]
    for event in events:
        missing = [key for key in required_keys(criteria) if key not in event.values]
        if missing:
            raise ValueError(f"{event.event_id} has no value for {missing}")
    rows = [event.values for event in events]
    frozen = calibration is not None
    if calibration is None:
        calibration = fit_calibration(
            rows,
            keys,
            system_id=system_id,
            release_id=release_id,
            lower_percentile=lower_percentile,
            upper_percentile=upper_percentile,
            small_n_threshold=small_n_threshold,
        )
    else:
        check_calibration(calibration, keys, system_id)
    constant = {key for key in keys if rows and zero_range(calibration.bounds[key])}
    if rows:
        for key in sorted(constant, key=keys.index):
            log.warning(
                "normalisation_zero_range", reason=ZERO_RANGE, feature=key, action="left_out"
            )
        for criterion in criteria:
            if set(FEATURES.get(criterion, ())) and set(FEATURES[criterion]) <= constant:
                log.warning("normalisation_constant_criterion", criterion=criterion, value=0.0)
    normalised = []
    for event, row in zip(events, rows, strict=True):
        scaled = {
            key: scale(row[key], calibration.bounds[key]) for key in keys if key not in constant
        }
        values = {
            criterion: criterion_value(scaled, weights[criterion])
            for criterion in criteria
            if criterion in FEATURES
        }
        if Dimension.ADR_VIOLATION in criteria:
            scaled[AV_FEATURE] = row[AV_FEATURE]
            values[Dimension.ADR_VIOLATION] = row[AV_FEATURE]
        normalised.append(
            NormalisedEvent(
                event_id=event.event_id,
                features=scaled,
                criteria={criterion: values[criterion] for criterion in criteria},
            )
        )
    return NormalisedSet(
        events=normalised,
        active_criteria=criteria,
        mode=calibration.mode,
        frozen=frozen,
        calibration=calibration,
    )


def calibration_filename(system_id: str) -> str:
    return f"calibration_{system_id}.json"


def save_calibration(calibration: Calibration, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(calibration.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_calibration(path: Path) -> Calibration:
    try:
        return Calibration.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CalibrationError(f"cannot load calibration {path}: {error}") from error
