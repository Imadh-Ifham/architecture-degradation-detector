"""Run report (plan T-13): ``report.md`` and one PNG per event, rendered from a stored run.

The input is the stored form of a run (``app/domain/analysis_run.py``), so ``c3 run`` (from
memory) and ``c3 report --run-id`` (from the database) take the same path and give the same
files. Rendering does no I/O; the caller writes the files under ``out/<run_id>/``.
"""

from app.components.degradation_detection.report.markdown import render_markdown, subject_label
from app.components.degradation_detection.report.models import REPORT_FILE, ReportFiles, plot_path
from app.components.degradation_detection.report.plots import event_plot
from app.domain.analysis_run import StoredRun, TrendRecord
from app.domain.degradation_event import DegradationEventV2, Scope


class ReportService:
    def render(self, stored: StoredRun) -> ReportFiles:
        files = {REPORT_FILE: render_markdown(stored).encode("utf-8")}
        trends = {(t.scope, t.subject_id, t.metric): t for t in stored.outputs.trends}
        for event in stored.outputs.events:
            plotted = [_trend_of(event, metric.metric, trends) for metric in event.affected_metrics]
            files[plot_path(event.event_id)] = event_plot(event, plotted, subject_label(event))
        return files


def _trend_of(
    event: DegradationEventV2,
    metric: str,
    trends: dict[tuple[Scope, str, str], TrendRecord],
) -> TrendRecord:
    """The stored trend behind one affected metric: same scope, same subject, same metric."""
    subjects = {
        Scope.ELEMENT: event.lineage_id,
        Scope.INSTANCE: event.instance_id,
        Scope.SYSTEM: event.system_id,
    }
    key = (event.scope, subjects[event.scope] or "", metric)
    if key not in trends:
        raise ValueError(f"event {event.event_id}: no stored trend for {key}")
    return trends[key]
