import pytest

from app.components.degradation_detection.config import AlignWeights
from app.components.degradation_detection.tracking.similarity import (
    name_similarity,
    name_tokens,
    neighbour_jaccard,
    similarity,
    size_ratio,
)
from app.domain.canonical_release import ElementSnapshot
from tests.components.degradation_detection.tracking.timelines import el


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("OrderService", "order service"),
        ("order-svc", "order svc"),
        ("com.shop.order_service", "com shop order service"),
        ("HTTPClient", "http client"),
        ("orderService2", "order service2"),
    ],
)
def test_name_tokens_split_on_case_and_separators(name: str, tokens: str) -> None:
    assert name_tokens(name) == tokens


def test_name_similarity_ignores_spelling_of_separators() -> None:
    assert name_similarity("OrderService", "order-service") == 1.0


def test_name_similarity_is_low_for_unrelated_names() -> None:
    assert name_similarity("order", "payment") < 0.5


def test_name_similarity_of_a_rename_is_high_but_not_one() -> None:
    assert 0.75 < name_similarity("order-svc", "order-service") < 1.0


def test_neighbour_jaccard_translates_old_neighbours_through_links() -> None:
    links = {"a": "a", "b": "b2"}

    assert neighbour_jaccard({"a", "b"}, {"a", "b2"}, links) == 1.0


def test_unlinked_old_neighbour_counts_in_the_union_only() -> None:
    assert neighbour_jaccard({"a", "x"}, {"a"}, {"a": "a"}) == 0.5


def test_unlinked_old_neighbour_never_overlaps_a_new_one_with_the_same_id() -> None:
    # x was not linked (e.g. its kind changed), so the x in the new release is another element.
    assert neighbour_jaccard({"x"}, {"x"}, {}) == 0.0


def test_neighbour_jaccard_without_neighbours_is_zero() -> None:
    assert neighbour_jaccard(set(), set(), {}) == 0.0


def test_size_ratio_is_min_over_max() -> None:
    assert size_ratio(el("a", size=1000), el("b", size=4000)) == 0.25


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (el("a", size=None), el("b", size=1000)),
        (el("a", size=1000, size_unit="loc"), el("b", size=1000, size_unit="files")),
        (el("a", size=0), el("b", size=0)),
    ],
    ids=["null size", "different units", "both zero"],
)
def test_size_ratio_is_zero_when_sizes_cannot_be_compared(
    old: ElementSnapshot, new: ElementSnapshot
) -> None:
    assert size_ratio(old, new) == 0.0


def test_similarity_weights_the_three_features() -> None:
    old, new = el("a", name="order", size=1000), el("b", name="order", size=2000)

    score = similarity(old, new, {"x", "y"}, {"x"}, {"x": "x"}, AlignWeights())

    assert (score.name, score.neighbours, score.size) == (1.0, 0.5, 0.5)
    assert score.total == pytest.approx(0.4 * 1.0 + 0.4 * 0.5 + 0.2 * 0.5)
