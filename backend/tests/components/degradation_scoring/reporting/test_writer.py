# Tests for the report writer (C4-T20): JSON checked against SeverityReportV1, the static HTML
# report (summary header, one card per event, badges, fixture banner) and the quarantine file.

import json

import pytest

from app.components.degradation_scoring.reporting.errors import ReportSchemaError
from app.components.degradation_scoring.reporting.models import EventNotes
from app.components.degradation_scoring.reporting.writer import (
    quarantine_json,
    render_html,
    report_json,
)
from app.domain.severity_report import DataProvenance, SeverityReportV1
from tests.components.degradation_scoring.support import sample_report, sample_view


def test_report_json_reads_back_as_the_same_report() -> None:
    report = sample_report()
    text = report_json(report)

    assert SeverityReportV1.model_validate_json(text) == report
    assert json.loads(text)["schema_version"] == "1.1.0"
    assert json.loads(text)["weights_provenance"] == "provisional-author-elicited"
    assert text.endswith("}\n")


def test_report_json_is_stable_text() -> None:
    assert report_json(sample_report()) == report_json(sample_report())


def test_report_json_refuses_another_schema_version() -> None:
    with pytest.raises(ReportSchemaError, match=r"1\.0\.0"):
        report_json(sample_report(schema_version="1.0.0"))


def test_quarantine_file_lists_every_event_left_out() -> None:
    data = json.loads(quarantine_json(sample_report()))

    assert data["run_id"] == "unit-run"
    assert data["quarantined"] == [
        {"event_id": "E-3", "reason": "unresolved_element", "detail": "missing: x"}
    ]
    assert data["skipped"] == [{"event_id": "E-4", "reason": "intentional"}]


def test_html_summary_header() -> None:
    html = render_html(sample_report(), sample_view())

    assert "Severity report: unit-system @ v1.0.0" in html
    assert "<td>fixture</td>" in html
    assert "blast_radius, persistence" in html
    assert "ahp_v1 · provisional-author-elicited (elicited by Tester)" in html
    assert "CR 0.011 (λmax 4.031)" in html
    assert "4 payloads: 2 ranked, 1 skipped, 1 quarantined" in html
    assert "<td>50.0%</td>" in html
    assert "off (no_repository)" in html
    assert "off (no_adr_index)" in html


def test_html_has_one_card_per_event_in_rank_order() -> None:
    html = render_html(sample_report(), sample_view())

    assert html.count('<section class="card">') == 2
    assert html.index("#1</span> CyclicDependency · E-1") < html.index("#2</span>")
    assert '<span style="width: 70.0%">' in html
    assert '<span style="width: 40.0%">' in html
    # BR row: value, weight, contribution
    assert '<td class="n">0.900</td><td class="n">0.750</td><td class="n">80.0%</td>' in html
    assert "metric fan_in" in html


def test_html_badges() -> None:
    html = render_html(sample_report(), sample_view())

    assert '<span class="badge warn">fallback: presence</span>' in html
    assert '<span class="badge off">hotspot off</span>' in html
    assert '<span class="badge off">ADR off</span>' in html


@pytest.mark.parametrize(
    ("provenance", "banner"),
    [
        (DataProvenance.FIXTURE, "FIXTURE DATA"),
        (DataProvenance.FIXTURE_EVENTS_LIVE_HISTORY, "FIXTURE EVENTS"),
    ],
)
def test_html_fixture_banner(provenance: DataProvenance, banner: str) -> None:
    html = render_html(sample_report(data_provenance=provenance), sample_view())

    assert 'class="banner"' in html
    assert banner in html


def test_html_live_run_has_no_banner() -> None:
    html = render_html(sample_report(data_provenance=DataProvenance.LIVE), sample_view())

    assert 'class="banner"' not in html


def test_html_escapes_input_text() -> None:
    notes = {
        "E-1": EventNotes(nodes=["<script>alert(1)</script>"], flags=[]),
        "E-2": EventNotes(nodes=["c"], flags=[]),
    }
    html = render_html(sample_report(), sample_view(notes=notes))

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_html_without_ranked_events() -> None:
    report = sample_report(records=[], quarantined=[], skipped=[])
    html = render_html(report, sample_view(notes={}))

    assert "No event was ranked." in html
    assert html.count("<p>None.</p>") == 2
