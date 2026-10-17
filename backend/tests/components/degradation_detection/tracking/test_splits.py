"""Splits and merges are post-PP1 (plan M3, step 3). These tests state the expected behaviour;
they are strict xfails, so implementing ``detect_splits_merges`` turns them into failures that
say "remove the xfail"."""

import pytest

from app.components.degradation_detection.config import AlignConfig
from app.components.degradation_detection.models import LineageEventType
from app.components.degradation_detection.tracking.models import SplitMerge
from app.components.degradation_detection.tracking.splits import detect_splits_merges
from tests.components.degradation_detection.tracking.timelines import rel

post_pp1 = pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="post-PP1")


@post_pp1
def test_element_split_in_two_is_a_split() -> None:
    old = rel("v1.0.0", ["a", "b", "monolith"], [("a", "monolith"), ("monolith", "b")])
    new = rel("v1.1.0", ["a", "b", "orders", "billing"], [("a", "orders"), ("billing", "b")])

    found = detect_splits_merges(
        old, new, ("monolith",), ("billing", "orders"), {"a": "a", "b": "b"}, AlignConfig()
    )

    assert found == (
        SplitMerge(
            event_type=LineageEventType.SPLIT,
            from_element_ids=("monolith",),
            to_element_ids=("billing", "orders"),
        ),
    )


@post_pp1
def test_two_elements_merged_into_one_is_a_merge() -> None:
    old = rel("v1.0.0", ["a", "b", "orders", "billing"], [("a", "orders"), ("billing", "b")])
    new = rel("v1.1.0", ["a", "b", "commerce"], [("a", "commerce"), ("commerce", "b")])

    found = detect_splits_merges(
        old, new, ("billing", "orders"), ("commerce",), {"a": "a", "b": "b"}, AlignConfig()
    )

    assert found == (
        SplitMerge(
            event_type=LineageEventType.MERGE,
            from_element_ids=("billing", "orders"),
            to_element_ids=("commerce",),
        ),
    )
