# Checks the hand-made Online Boutique fixtures used by the T21 real-repo run agree with each
# other: the complete call graph, every service mapped, events on graph services and real tags.

import json
import re
from pathlib import Path
from typing import Any

from app.domain.degradation_event import DegradationEventV2
from app.domain.release_package import ReleasePackageV1

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "degradation_scoring"
TAGS = [f"v0.10.{i}" for i in range(8)]


def load(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


GRAPH = load("graphs/online_boutique_graph.v0.10.7.json")
PACKAGE = ReleasePackageV1.model_validate(GRAPH)
EVENTS = [
    DegradationEventV2.model_validate(e) for e in load("events/online_boutique_events.v1.json")
]
MAPPING = load("mappings/online_boutique.source_paths.v1.json")
LINKS = load("adr/online_boutique/adr_links.v1.json")
NODES = {element.id for element in PACKAGE.elements}
FRONTEND = {"checkout", "cart", "productcatalog", "currency", "recommendation", "shipping", "ad"}
CHECKOUT = {"payment", "email", "shipping", "currency", "cart", "productcatalog"}


def test_graph_is_labelled_and_is_the_complete_call_graph() -> None:
    # every *_SERVICE_ADDR in kubernetes-manifests/ at v0.10.7, without loadgenerator
    edges = {(dep.from_, dep.to) for dep in PACKAGE.dependencies}

    assert GRAPH["data_provenance"] == "fixture"
    assert (PACKAGE.system_id, PACKAGE.release_id) == ("online-boutique", "v0.10.7")
    assert edges == {("frontend", f"{s}service") for s in FRONTEND} | {
        ("checkoutservice", f"{s}service") for s in CHECKOUT
    } | {("recommendationservice", "productcatalogservice")}
    assert len(NODES) == 10


def test_every_graph_service_has_a_folder_mapping() -> None:
    for node in NODES:
        assert MAPPING["elements"][node] == [f"src/{node}/**"]


def test_events_use_graph_services_and_real_tags() -> None:
    assert len(EVENTS) == 6
    assert len({event.event_id for event in EVENTS}) == 6
    for event in EVENTS:
        names = [event.element_id] if event.element_id else event.members
        releases = [v.release_id for m in event.affected_metrics for v in m.series]

        assert re.fullmatch(r"DEG-C4OB-T21-\d{4}", event.event_id)
        assert event.system_id == "online-boutique"
        assert set(names) <= NODES
        assert event.window.end_release == "v0.10.7"
        assert releases == TAGS[TAGS.index(event.window.start_release) :]
        assert event.window.n_releases == len(releases)


def test_adr_links_are_labelled_and_name_graph_services_and_adr_files() -> None:
    files = {f"ADR-{p.name[:4]}" for p in (FIXTURES / "adr" / "online_boutique").glob("*.md")}

    assert LINKS["data_provenance"] == "fixture"
    assert set(LINKS["links"]) <= NODES
    linked = {adr for adrs in LINKS["links"].values() for adr in adrs}

    assert linked == files == {"ADR-0001", "ADR-0002"}
