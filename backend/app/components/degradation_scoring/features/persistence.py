# Persistence: how long a degradation has lasted and how fast it grows.
# Uses C3's data only; never re-runs trend tests or uses tau, q_value or sen_slope.

from collections.abc import Sequence

from app.components.degradation_scoring.features.models import PersistenceFeatures
from app.domain.degradation_event import AffectedMetric, DegradationEventV2, Worsening


def release_order(event: DegradationEventV2) -> list[str]:
    # releases in the order of the event's series (all metrics, first appearance wins)
    order: dict[str, None] = {}
    for metric in event.affected_metrics:
        for value in metric.series:
            order.setdefault(value.release_id, None)
    return list(order)


def releases_present(event: DegradationEventV2) -> tuple[set[str], bool]:
    # C3 V2.1.0 instance_history if sent; else releases with a non-null value (fallback, A2)
    history = getattr(event, "instance_history", None)
    if history:
        return {entry.release_id for entry in history}, False
    present = {
        value.release_id
        for metric in event.affected_metrics
        for value in metric.series
        if value.value is not None
    }
    return present, True


def consecutive_releases(order: Sequence[str], present: set[str], end_release: str) -> int:
    # length of the run of present releases that ends at the detected release
    if end_release not in order:
        return 0
    count = 0
    for release in reversed(order[: order.index(end_release) + 1]):
        if release not in present:
            break
        count += 1
    return count


def relative_slope(metric: AffectedMetric, order: Sequence[str]) -> float | None:
    # OLS slope of the non-null values over release index, divided by their mean, signed so
    # that positive = worsening (C4-ADR-010); None with fewer than two values or mean 0
    index = {release: i for i, release in enumerate(order)}
    points = [(index[v.release_id], v.value) for v in metric.series if v.value is not None]
    if len(points) < 2:
        return None
    xs = [float(x) for x, _ in points]
    ys = [y for _, y in points]
    x_mean, y_mean = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - x_mean) ** 2 for x in xs)
    if sxx == 0 or y_mean == 0:
        return None
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)) / sxx
    relative = slope / abs(y_mean)
    return -relative if metric.worsening is Worsening.DECREASE else relative


def persistence(event: DegradationEventV2) -> PersistenceFeatures:
    # consecutive_releases + growth_slope of the fastest-worsening metric (owner, 2026-10-18)
    order = release_order(event)
    present, fallback = releases_present(event)
    slopes = {
        metric.metric: slope
        for metric in event.affected_metrics
        if (slope := relative_slope(metric, order)) is not None
    }
    worst = max(slopes, key=lambda name: slopes[name]) if slopes else None
    return PersistenceFeatures(
        consecutive_releases=consecutive_releases(order, present, event.window.end_release),
        growth_slope=slopes[worst] if worst else 0.0,
        growth_slope_available=worst is not None,
        growth_metric=worst,
        presence_fallback=fallback,
    )
