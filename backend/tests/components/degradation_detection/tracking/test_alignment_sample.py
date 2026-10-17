import csv
import io

import pytest

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.tracking import TrackingService
from app.components.degradation_detection.tracking.alignment_sample import (
    COLUMNS,
    alignment_sample_csv,
)
from app.components.degradation_detection.tracking.models import TrackingResult
from tests.components.degradation_detection.tracking.timelines import el, rel, timeline


@pytest.fixture
def result() -> TrackingResult:
    """One similarity rename (order) and one alias rename (pay) in the same release."""
    return TrackingService(C3Config()).track(
        timeline(
            rel(
                "v1.0.0",
                ["a", "b", "order-svc", "pay-svc"],
                [("a", "order-svc"), ("order-svc", "b")],
            ),
            rel(
                "v1.1.0",
                ["a", "b", "order-service", el("payments", aliases=["pay-svc"])],
                [("a", "order-service"), ("order-service", "b")],
            ),
        )
    )


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_one_row_per_decision_with_the_checker_column_empty(result: TrackingResult) -> None:
    text = alignment_sample_csv(result)

    assert text.splitlines()[0] == ",".join(COLUMNS)
    assert COLUMNS[-1] == "correct"
    assert len(rows(text)) == len(result.decisions) == 2
    assert {row["correct"] for row in rows(text)} == {""}


def test_similarity_row_has_its_features_and_alias_row_leaves_them_empty(
    result: TrackingResult,
) -> None:
    by_method = {row["method"]: row for row in rows(alignment_sample_csv(result))}

    alias, sim = by_method["ALIAS"], by_method["SIMILARITY"]
    assert (alias["from_element_ids"], alias["to_element_ids"]) == ("pay-svc", "payments")
    assert (alias["similarity"], alias["name"], alias["runner_up"]) == ("", "", "")
    assert (sim["from_release_id"], sim["to_release_id"]) == ("v1.0.0", "v1.1.0")
    assert sim["outcome"] == "LINKED"
    assert sim["neighbours"] == "1.0000"  # fixed digits, so the file is byte-stable


def test_csv_uses_lf_line_endings(result: TrackingResult) -> None:
    assert "\r\n" not in alignment_sample_csv(result)
