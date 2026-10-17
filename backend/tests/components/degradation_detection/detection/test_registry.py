"""The detector registry: the only place in C3 that branches on ``architecture_style``.

Plan Section 4, M2 step 4: the catalog says which detectors are enabled for a style; a detector
whose required package fields are missing is skipped with a log line, and the rest still run.
"""

from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.components.degradation_detection.config import C3Config, CatalogConfig
from app.components.degradation_detection.detection import DetectionService
from app.components.degradation_detection.detection.models import (
    ArchGraph,
    ReleaseContext,
)
from app.components.degradation_detection.detection.registry import (
    ALL_DETECTORS,
    CATALOG_INPUT_MISSING,
    DetectorRegistry,
    available_fields,
)
from app.components.degradation_detection.models import AntiPatternInstance
from app.domain.canonical_release import ElementSnapshot
from app.domain.degradation_event import Scope
from app.domain.release_package import ArchitectureStyle
from tests.components.degradation_detection.detection.graphs import (
    graph_fixtures,
    load_graph_fixture,
    release,
)

UNIVERSAL = [
    "CyclicDependency",
    "HubLikeElement",
    "UnstableDependency",
    "OversizedElement",
    "BigBallOfMud",
]
DEFAULT = DetectorRegistry.from_catalog(CatalogConfig())
FIELDS = frozenset({"datastore_access", "delegation", "layer"})


def ids(detectors: object) -> list[str]:
    return [d.id for d in detectors]  # type: ignore[attr-defined]


# --- what runs for which style -------------------------------------------------------------


def test_all_detectors_in_output_order() -> None:
    assert ids(ALL_DETECTORS) == [*UNIVERSAL, "SharedPersistence"]


@pytest.mark.parametrize("style", [s for s in ArchitectureStyle if s.value != "microservices"])
def test_other_styles_run_the_universal_tier_only(style: ArchitectureStyle) -> None:
    assert ids(DEFAULT.detectors_for(style, FIELDS)) == UNIVERSAL


def test_microservices_also_run_shared_persistence() -> None:
    assert ids(DEFAULT.detectors_for("microservices", FIELDS)) == [*UNIVERSAL, "SharedPersistence"]


def test_detector_ids_are_every_detector_the_catalog_enables() -> None:
    """The ap_count.<Type> metrics are declared for exactly these."""
    assert DEFAULT.detector_ids == (*UNIVERSAL, "SharedPersistence")


def test_for_release_reads_style_and_fields_from_the_release() -> None:
    r = release("ab", datastore_access=[("a", "db")])

    assert ids(DEFAULT.for_release(r)) == [*UNIVERSAL, "SharedPersistence"]


# --- skip with a log when a required field is missing --------------------------------------


def test_missing_field_skips_the_detector_and_the_universal_tier_still_runs() -> None:
    r = release("ab", release_id="v1.3.0")  # no datastore_access

    with capture_logs() as logs:
        chosen = DEFAULT.for_release(r)

    assert ids(chosen) == UNIVERSAL
    assert logs == [
        {
            "event": "detector_skipped",
            "log_level": "info",
            "reason": CATALOG_INPUT_MISSING,
            "detector": "SharedPersistence",
            "missing": ["datastore_access"],
            "style": "microservices",
            "release_id": "v1.3.0",
        }
    ]


def test_a_detector_not_enabled_for_the_style_is_not_logged_as_skipped() -> None:
    r = release("ab", style=ArchitectureStyle.MONOLITH)

    with capture_logs() as logs:
        chosen = DEFAULT.for_release(r)

    assert ids(chosen) == UNIVERSAL
    assert logs == []


def test_empty_datastore_access_is_supplied_not_missing() -> None:
    """C2 sent ``[]``: it looked and found no datastores, so the detector runs and finds none."""
    assert "SharedPersistence" in ids(DEFAULT.for_release(release("ab", datastore_access=[])))


# --- available fields ----------------------------------------------------------------------


def with_layers(*layers: str | None) -> frozenset[str]:
    r = release("ab"[: len(layers)])
    elements = tuple(
        ElementSnapshot(element_id=e.element_id, name=e.name, kind=e.kind, layer=layer)
        for e, layer in zip(r.elements, layers, strict=True)
    )
    return available_fields(r.model_copy(update={"elements": elements}))


def test_no_optional_fields() -> None:
    assert available_fields(release("ab")) == frozenset()


def test_datastore_access_and_delegation_count_when_supplied_even_if_empty() -> None:
    r = release("ab", datastore_access=[]).model_copy(update={"delegation": ()})

    assert available_fields(r) == frozenset({"datastore_access", "delegation"})


def test_layer_counts_only_when_every_element_has_one() -> None:
    """A layered detector on a half-layered graph would miss or invent back-calls."""
    assert with_layers("web", "data") == frozenset({"layer"})
    assert with_layers("web", None) == frozenset()


# --- the catalog is checked against the detectors at start-up ------------------------------


@pytest.mark.parametrize(
    ("enabled", "message"),
    [
        ({"*": ("NoSuchDetector",)}, "unknown detector"),
        ({"*": ("SharedPersistence",)}, "does not apply"),
        ({"layered": ("SharedPersistence",)}, "does not apply"),
    ],
    ids=["unknown-id", "style-specific-under-wildcard", "wrong-style"],
)
def test_invalid_catalog_fails(enabled: dict[str, tuple[str, ...]], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        DetectorRegistry(ALL_DETECTORS, enabled)


def test_two_detectors_with_one_id_fail() -> None:
    with pytest.raises(ValueError, match="twice"):
        DetectorRegistry((*ALL_DETECTORS, ALL_DETECTORS[0]), {"*": ("CyclicDependency",)})


def test_a_universal_detector_may_be_enabled_for_one_style_only() -> None:
    registry = DetectorRegistry(ALL_DETECTORS, {"layered": ("CyclicDependency",)})

    assert ids(registry.detectors_for("layered", FIELDS)) == ["CyclicDependency"]
    assert ids(registry.detectors_for("monolith", FIELDS)) == []


# --- extension: a new style and detector change nothing for the existing ones -------------


class Dummy:
    id: str = "Dummy"
    catalog: str = "dummy"
    styles: frozenset[str] = frozenset({"dummy-style"})
    scope: Scope = Scope.SYSTEM
    required_fields: frozenset[str] = frozenset()
    driving_metrics: tuple[str, ...] = ()
    instance_measures: tuple[str, ...] = ()

    def detect(self, g: ArchGraph, ctx: ReleaseContext) -> list[AntiPatternInstance]:
        return [
            AntiPatternInstance(
                release_id=g.release_id,
                local_instance_id="Dummy:system",
                anti_pattern_type=self.id,
                catalog=self.catalog,
                scope=self.scope,
                members=g.nodes,
            )
        ]


EXTENDED = DetectorRegistry(
    (*ALL_DETECTORS, Dummy()), {**CatalogConfig().enabled, "dummy-style": ("Dummy",)}
)
FIXTURES = graph_fixtures()


@pytest.mark.parametrize("style", list(ArchitectureStyle))
def test_extension_leaves_existing_styles_unchanged(style: ArchitectureStyle) -> None:
    assert ids(EXTENDED.detectors_for(style, FIELDS)) == ids(DEFAULT.detectors_for(style, FIELDS))


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_extension_leaves_existing_results_unchanged(path: Path) -> None:
    r, _ = load_graph_fixture(path)
    cfg = C3Config()

    before = DetectionService(cfg).detect(r)
    after = DetectionService(cfg, EXTENDED).detect(r)

    assert after.instances == before.instances
    assert after.detectors_run == before.detectors_run
    extra = {o.metric for o in after.observations} - {o.metric for o in before.observations}
    assert extra == {"ap_count.Dummy"}
    assert [o for o in after.observations if o.metric != "ap_count.Dummy"] == list(
        before.observations
    )


def test_new_style_runs_universal_tier_plus_its_own_detector() -> None:
    # The contract enum has no "dummy-style"; model_copy skips validation, as a future style would.
    r = release("ab", [("a", "b")]).model_copy(update={"architecture_style": "dummy-style"})

    result = DetectionService(C3Config(), EXTENDED).detect(r)

    assert result.detectors_run == (*UNIVERSAL, "Dummy")
    assert [i.anti_pattern_type for i in result.instances] == ["Dummy"]
