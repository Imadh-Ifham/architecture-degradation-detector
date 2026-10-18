"""Run report (plan T-13): ``report.md`` + one PNG per event, rendered from a stored run."""

import pytest

from app.components.degradation_detection.report import ReportService
from app.domain.analysis_run import RunOutputs, StoredRun
from tests.components.degradation_detection.run_records import (
    EVENT_ID,
    RUN_ID,
    failed_run,
    outputs,
    stored_run,
)

PLOT = f"plots/{EVENT_ID}.png"


def report_text(run: StoredRun | None = None) -> str:
    return ReportService().render(run or stored_run())["report.md"].decode("utf-8")


def rows(text: str, first_cell: str) -> list[list[str]]:
    """Cells of every markdown table row whose first cell is ``first_cell``."""
    found = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] == first_cell:
            found.append(cells)
    return found


def test_renders_the_report_and_one_plot_per_event() -> None:
    assert set(ReportService().render(stored_run())) == {"report.md", PLOT}


def test_header_identifies_the_run() -> None:
    text = report_text()

    assert text.startswith(f"# C3 analysis run {RUN_ID}\n")
    for expected in ("shopfront", "COMPLETED", "sha256:" + "a" * 64, "abc1234", "numpy 2.5.4"):
        assert expected in text


def test_release_table_counts_anti_patterns_per_release_and_type() -> None:
    text = report_text()

    header = rows(text, "#")[0]
    assert header[:4] == ["#", "Release", "Released", "Gate"]
    assert header[4:] == ["CyclicDependency", "HubLikeElement", "Total"]
    assert rows(text, "0")[0][1:] == ["v1", "2026-07-21", "ACCEPTED", "0", "0", "0"]
    assert rows(text, "1")[0][1:] == ["v2", "2026-08-20", "DOWNWEIGHTED", "1", "0", "1"]
    assert rows(text, "2")[0][1:] == ["v3", "2026-09-19", "ACCEPTED", "1", "1", "2"]


def test_series_section_counts_tested_and_untested_by_scope_and_reason() -> None:
    text = report_text()

    assert rows(text, "ELEMENT")[0] == ["ELEMENT", "2", "1", "1"]
    assert rows(text, "INSTANCE")[0] == ["INSTANCE", "0", "0", "1"]
    assert rows(text, "SYSTEM")[0] == ["SYSTEM", "0", "0", "0"]
    assert rows(text, "NO_WORSENING_DIRECTION")[0][1] == "1"
    assert rows(text, "SERIES_TOO_SHORT")[0][1] == "1"


def test_every_event_is_listed_with_its_plot_and_none_is_ranked() -> None:
    text = report_text()

    (row,) = rows(text, EVENT_ID)
    assert row[1:6] == ["ELEMENT", "HubLikeElement", "auth", "v1..v3", "-"]
    assert "fan_in" in row[6] and "q=0.02" in row[6]
    assert f"]({PLOT})" in row[7]
    # Ranking is C4's job (locked decision 6): the order is fixed and says so.
    assert "C3 does not rank" in text


def test_static_baseline_section_contrasts_flags_with_events() -> None:
    """S3 in miniature: `legacy` is over a fixed threshold, but C3 has no event on it."""
    text = report_text()

    assert rows(text, "auth")[-1] == ["auth", "fan_in > 10", "12", "yes"]
    assert rows(text, "legacy")[-1] == ["legacy", "size > 10000", "12000", "no"]
    assert "2 flags on 2 elements at v3; 1 of these elements has a C3 event." in text


def test_run_section_lists_timings_and_reason_counts() -> None:
    text = report_text()

    assert rows(text, "trends")[0] == ["trends", "1.500"]
    assert rows(text, "SERIES_TOO_SHORT")[-1] == ["SERIES_TOO_SHORT", "1"]


def test_reasons_not_counted_are_reported_as_such() -> None:
    run = stored_run()
    uncounted = StoredRun(
        run=run.run.model_copy(update={"reason_counts": None}), outputs=run.outputs
    )

    assert "Reason codes were not counted" in report_text(uncounted)


def test_plots_are_png_and_byte_identical_across_renders() -> None:
    first = ReportService().render(stored_run())[PLOT]
    second = ReportService().render(stored_run())[PLOT]

    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert first == second


def test_report_is_identical_across_renders() -> None:
    assert ReportService().render(stored_run()) == ReportService().render(stored_run())


def test_an_event_without_its_trend_record_fails_loudly() -> None:
    broken = outputs().model_copy(update={"trends": ()})

    with pytest.raises(ValueError, match="fan_in"):
        ReportService().render(StoredRun(run=stored_run().run, outputs=broken))


def test_a_failed_run_reports_its_error_and_nothing_else() -> None:
    files = ReportService().render(StoredRun(run=failed_run(), outputs=RunOutputs()))

    text = files["report.md"].decode("utf-8")
    assert set(files) == {"report.md"}
    assert "FAILED" in text
    assert "RuntimeError: boom" in text
    assert "No events." in text
