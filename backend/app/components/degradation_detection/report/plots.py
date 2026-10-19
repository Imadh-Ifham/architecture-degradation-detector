"""One PNG per event: each affected metric's series with its Sen's slope line.

The line is ``intercept + slope * t`` over the tested points, with ``t`` the release ordinal,
the time axis the slope was computed on [D-05]. A null point is a gap in the series, never 0.
Releases the gate DOWNWEIGHTED are drawn as hollow markers.

Rendering uses matplotlib's Agg canvas directly (no pyplot, no global state) and writes no
software or date metadata, so the same run gives byte-identical files with the pinned
matplotlib.
"""

import io
import math
from collections.abc import Sequence

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from app.domain.analysis_run import TrendRecord
from app.domain.degradation_event import DegradationEventV2

PANEL_HEIGHT = 2.6  # inches per affected metric
WIDTH = 7.0
DPI = 100


def event_plot(event: DegradationEventV2, trends: Sequence[TrendRecord], subject: str) -> bytes:
    """``trends`` are the event's affected metrics, in the event's order."""
    figure = Figure(figsize=(WIDTH, PANEL_HEIGHT * len(trends)), dpi=DPI)
    FigureCanvasAgg(figure)
    axes = figure.subplots(len(trends), 1, squeeze=False)[:, 0]
    low_confidence = set(event.window.low_confidence_releases)

    for ax, trend in zip(axes, trends, strict=True):
        ordinals = [p.ordinal for p in trend.points]
        drawn = [math.nan if p.value is None else p.value for p in trend.points]  # NaN = gap
        ax.plot(ordinals, drawn, marker="o", linewidth=1.5, label=trend.metric)

        low = [p for p in trend.points if p.release_id in low_confidence and p.value is not None]
        if low:
            ax.plot(
                [p.ordinal for p in low],
                [p.value for p in low],
                linestyle="none",
                marker="o",
                markerfacecolor="white",
                label="downweighted release",
            )

        tested = [p.ordinal for p in trend.points if p.value is not None]
        ends = [tested[0], tested[-1]]
        ax.plot(
            ends,
            [trend.intercept + trend.sen_slope * t for t in ends],
            linestyle="--",
            linewidth=1,
            label="Sen's slope",
        )

        ax.set_xticks(ordinals, [p.release_id for p in trend.points], rotation=45, fontsize=8)
        ax.set_ylabel(trend.unit, fontsize=8)
        ax.set_title(
            f"{trend.metric}: Sen's slope {trend.sen_slope:+.3g}/release, "
            f"p = {trend.p_value:.2g}, q = {trend.q_value:.2g}",
            fontsize=9,
        )
        ax.legend(fontsize=7, loc="best")

    figure.suptitle(f"{event.anti_pattern_type} - {subject}", fontsize=10)
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", metadata={"Software": None})
    return buffer.getvalue()
