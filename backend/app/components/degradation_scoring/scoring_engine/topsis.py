# TOPSIS: severity = closeness of an event to the ideal event.
# fixed_reference (default, C4-ADR-002): ideal = 1 and anti-ideal = 0 on every criterion, so an
# event's score never depends on the other events; classic: the best / worst event of the run.

from collections.abc import Mapping, Sequence

import numpy as np

from app.components.degradation_scoring.scoring_engine.models import (
    NormalisedEvent,
    RankedEvent,
    TopsisMode,
)
from app.domain.severity_report import Dimension


def weighted_matrix(
    x: np.ndarray, w: np.ndarray, mode: TopsisMode
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    # v = w * x and the ideal / anti-ideal points. fixed: x already on [0, 1] (§5.5),
    # A+ = w, A- = 0. classic: r = x / sqrt(sum_i x^2) per column (an all-zero column stays 0),
    # A+ = max_i v, A- = min_i v.
    if mode == "fixed_reference":
        return x * w, w.copy(), np.zeros_like(w)
    norms = np.sqrt((x**2).sum(axis=0))
    r = np.divide(x, norms, out=np.zeros_like(x), where=norms > 0)
    v = r * w
    return v, v.max(axis=0), v.min(axis=0)


def topsis(
    events: Sequence[NormalisedEvent],
    weights: Mapping[Dimension, float],
    active: Sequence[Dimension],
    mode: TopsisMode,
) -> list[RankedEvent]:
    # S_i = d-_i / (d+_i + d-_i) (0 when both are 0); contribution c_ij =
    # (v_ij - A-_j)^2 / sum_j (v_ij - A-_j)^2 (all 0 on the anti-ideal); rank by S descending,
    # ties by event_id. Inactive criteria are left out and contribute 0.
    if not events:
        return []
    x = np.array([[event.criteria[c] for c in active] for event in events], dtype=float)
    w = np.array([weights[c] for c in active], dtype=float)
    v, ideal, anti = weighted_matrix(x, w, mode)
    d_plus = np.sqrt(((v - ideal) ** 2).sum(axis=1))
    d_minus = np.sqrt(((v - anti) ** 2).sum(axis=1))
    total = d_plus + d_minus
    severity = np.divide(d_minus, total, out=np.zeros_like(total), where=total > 0)
    gaps = (v - anti) ** 2
    gap_sum = gaps.sum(axis=1, keepdims=True)
    shares = np.divide(gaps, gap_sum, out=np.zeros_like(gaps), where=gap_sum > 0)
    order = sorted(range(len(events)), key=lambda i: (-severity[i], events[i].event_id))
    return [
        RankedEvent(
            event_id=events[i].event_id,
            rank=rank,
            severity=float(severity[i]),
            distance_ideal=float(d_plus[i]),
            distance_anti_ideal=float(d_minus[i]),
            contributions={
                d: float(shares[i, active.index(d)]) if d in active else 0.0 for d in Dimension
            },
        )
        for rank, i in enumerate(order, start=1)
    ]
