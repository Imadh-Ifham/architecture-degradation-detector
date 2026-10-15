"""Golden graphs (tests/fixtures/graphs): every registered detector on every fixture.

Each fixture lists the *complete* expected output of every detector, so a positive fixture
checks that its detector finds exactly the planted instance and that no other detector fires,
and a negative fixture checks that nothing fires at all. The expected values are derived by
hand in each fixture's ``description``.
"""

from pathlib import Path
from typing import Any

import pytest

from app.components.degradation_detection.detection.registry import ALL_DETECTORS
from app.components.degradation_detection.models import AntiPatternInstance
from tests.components.degradation_detection.detection.graphs import (
    graph_fixtures,
    load_graph_fixture,
)
from tests.components.degradation_detection.detection.universal.run import run

FIXTURES = graph_fixtures()
CATALOG_OF = {d.id: d.catalog for d in ALL_DETECTORS}


def comparable(instance: AntiPatternInstance) -> tuple[str, str, tuple[str, ...]]:
    return instance.anti_pattern_type, instance.scope.value, instance.members


def expected_key(expected: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    return expected["anti_pattern_type"], expected["scope"], tuple(expected["members"])


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_detectors_find_exactly_the_expected_instances(path: Path) -> None:
    r, expected = load_graph_fixture(path)

    found = run(r, ALL_DETECTORS)

    assert sorted(map(comparable, found)) == sorted(map(expected_key, expected))
    by_key = {comparable(instance): instance for instance in found}
    for want in expected:
        got = by_key[expected_key(want)]
        assert got.measures == pytest.approx(want["measures"])
        assert got.release_id == r.release_id
        assert got.catalog == CATALOG_OF[got.anti_pattern_type]


@pytest.mark.parametrize("path", [p for p in FIXTURES if "__negative_" in p.name])
def test_negative_fixtures_expect_nothing(path: Path) -> None:
    _, expected = load_graph_fixture(path)

    assert expected == []


@pytest.mark.parametrize("detector_id", [d.id for d in ALL_DETECTORS])
def test_every_detector_has_a_positive_and_a_negative_fixture(detector_id: str) -> None:
    names = {p.name for p in FIXTURES}

    assert f"{detector_id}__positive_01.json" in names
    assert f"{detector_id}__negative_01.json" in names


def test_positive_fixture_plants_an_instance_of_its_detector() -> None:
    for path in FIXTURES:
        if "__positive_" in path.name:
            detector_id = path.name.split("__")[0]
            _, expected = load_graph_fixture(path)
            assert detector_id in {e["anti_pattern_type"] for e in expected}, path.name


def test_detection_is_deterministic() -> None:
    for path in FIXTURES:
        r, _ = load_graph_fixture(path)
        assert run(r) == run(r), path.name
