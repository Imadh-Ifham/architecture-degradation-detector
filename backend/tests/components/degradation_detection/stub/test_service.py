"""The synthetic `shopfront` system: what is planted really is in the generated packages.

These tests read the generated JSON the way a consumer would and recompute the simple graph
facts with networkx and numpy, independently of the detectors built in later tasks.
"""

import json
import re
import statistics
from typing import Any

import networkx as nx
import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.models import GateStatus
from app.components.degradation_detection.stub import StubService
from app.components.degradation_detection.stub.models import (
    DEFAULT_SEED,
    GROUND_TRUTH_FILE,
    GroundTruth,
)
from app.domain.degradation_event import Scope
from app.domain.release_package import DANGLING_DEPENDENCY, ReleasePackageV1

CFG = C3Config()
RELEASES = [f"v1.{i}.0" for i in range(10)]
HOTFIX_FILE = "shopfront__v1.3.1-hotfix.json"
OTHER_SEEDS = [1, 2, 3, 42]


def generate(seed: int = DEFAULT_SEED) -> dict[str, str]:
    return StubService().generate(seed).system_files


def packages(seed: int = DEFAULT_SEED) -> list[dict[str, Any]]:
    files = generate(seed)
    return [json.loads(files[f"shopfront__{release}.json"]) for release in RELEASES]


def truth(seed: int = DEFAULT_SEED) -> GroundTruth:
    return GroundTruth.model_validate(yaml.safe_load(generate(seed)[GROUND_TRUTH_FILE]))


def graph(package: dict[str, Any]) -> nx.DiGraph:
    g: nx.DiGraph = nx.DiGraph()
    g.add_nodes_from(e["id"] for e in package["elements"])
    g.add_edges_from((d["from"], d["to"]) for d in package["dependencies"])
    return g


def cycles(package: dict[str, Any]) -> list[list[str]]:
    return [sorted(c) for c in nx.strongly_connected_components(graph(package)) if len(c) > 1]


def element(package: dict[str, Any], element_id: str) -> dict[str, Any]:
    [found] = [e for e in package["elements"] if e["id"] == element_id]
    return found


def upper_fence(values: list[int]) -> float:
    q1, q3 = np.percentile(values, [25, 75])
    return float(q3 + CFG.detection.hub.iqr_k * (q3 - q1))


def robust_z(package: dict[str, Any]) -> dict[str, float]:
    sizes = {e["id"]: e["size"] for e in package["elements"]}
    median = statistics.median(sizes.values())
    mad = statistics.median(abs(s - median) for s in sizes.values())
    return {name: (size - median) / (1.4826 * mad) for name, size in sizes.items()}


def instability(g: nx.DiGraph, node: str) -> float | None:
    total = g.in_degree(node) + g.out_degree(node)
    return None if total == 0 else g.out_degree(node) / total


def unstable_dep_ratio(g: nx.DiGraph, node: str) -> float:
    own = instability(g, node)
    assert own is not None
    bad = [t for t in g.successors(node) if (instability(g, t) or 0.0) > own]
    return len(bad) / g.out_degree(node)


def kendall_s(values: list[float]) -> int:
    return sum((b > a) - (b < a) for i, a in enumerate(values) for b in values[i + 1 :])


def non_decreasing(values: list[float]) -> bool:
    return all(b >= a for a, b in zip(values, values[1:], strict=False))


# --- files -----------------------------------------------------------------------------------


def test_writes_ten_releases_one_rejected_package_and_the_manifest() -> None:
    expected = {f"shopfront__{r}.json" for r in RELEASES} | {HOTFIX_FILE, GROUND_TRUTH_FILE}

    assert set(generate()) == expected


def test_same_seed_gives_byte_identical_files() -> None:
    assert generate(7) == generate(7)


def test_another_seed_changes_the_noise_but_not_the_file_set() -> None:
    assert generate(1) != generate(2)
    assert set(generate(1)) == set(generate(2))


def test_files_end_with_one_newline_and_use_lf() -> None:
    for name, text in generate().items():
        assert text.endswith("\n") and not text.endswith("\n\n"), name
        assert "\r" not in text, name


def test_every_main_line_package_is_a_valid_release_package() -> None:
    for payload in packages():
        package = ReleasePackageV1.model_validate(payload)

        assert package.schema_version == "1.1.0"
        assert package.system_id == "shopfront"
        assert package.architecture_style.value == "microservices"
        assert package.granularity == "service"
        assert len(package.elements) == 15
        assert package.datastore_access is not None


def test_releases_are_monthly_and_on_the_main_line() -> None:
    parsed = [ReleasePackageV1.model_validate(p) for p in packages()]
    months = [p.released_at.year * 12 + p.released_at.month for p in parsed]

    assert months == list(range(months[0], months[0] + 10))
    assert all(re.match(CFG.ingest.release_line_regex, p.release_id) for p in parsed)


# --- scenarios -------------------------------------------------------------------------------


def test_s1_one_cycle_appears_then_absorbs_two_services() -> None:
    found = [cycles(p) for p in packages()]

    assert found[0] == []
    assert all(len(c) == 1 for c in found[1:])
    assert [len(c[0]) for c in found[1:]] == [3, 3, 3, 4, 4, 4, 5, 5, 5]
    assert found[1][0] == ["inventory", "order-svc", "payment"]
    assert found[4][0] == ["inventory", "order-service", "payment", "shipping"]
    assert found[7][0] == ["inventory", "notification", "order-service", "payment", "shipping"]


def test_s1_edges_inside_the_cycle_never_shrink() -> None:
    counts = []
    for package in packages()[1:]:
        g = graph(package)
        [members] = cycles(package)
        counts.append(g.subgraph(members).number_of_edges())

    assert non_decreasing(counts)
    assert counts[-1] > counts[0]


def test_s2_catalog_coupling_grows_every_release() -> None:
    graphs = [graph(p) for p in packages()]
    fan_in = [g.in_degree("catalog") for g in graphs]
    fan_out = [g.out_degree("catalog") for g in graphs]
    total = [i + o for i, o in zip(fan_in, fan_out, strict=True)]

    assert non_decreasing(fan_in) and non_decreasing(fan_out)
    assert all(b > a for a, b in zip(total, total[1:], strict=False))


def test_s2_catalog_is_the_only_hub_in_the_last_release() -> None:
    g = graph(packages()[-1])
    in_fence = upper_fence([d for _, d in g.in_degree()])
    out_fence = upper_fence([d for _, d in g.out_degree()])

    hubs = [n for n in g if g.in_degree(n) > in_fence and g.out_degree(n) > out_fence]

    assert hubs == ["catalog"]


def test_s3_legacy_auth_fan_in_is_high_and_flat() -> None:
    graphs = [graph(p) for p in packages()]

    assert {g.in_degree("legacy-auth") for g in graphs} == {11}
    assert {g.out_degree("legacy-auth") for g in graphs} == {0}
    assert {element(p, "legacy-auth")["size"] for p in packages()} == {9000}
    # A constant element count keeps fan_in_norm = fan_in / (N - 1) flat as well.
    assert {g.number_of_nodes() for g in graphs} == {15}


def test_s4_order_service_is_renamed_with_an_alias() -> None:
    for index, package in enumerate(packages()):
        ids = {e["id"] for e in package["elements"]}
        if index < 4:
            assert "order-svc" in ids and "order-service" not in ids
        else:
            assert "order-service" in ids and "order-svc" not in ids
            assert element(package, "order-service")["aliases"] == ["order-svc"]


def test_s5_reporting_outgrows_the_system() -> None:
    all_packages = packages()
    sizes = [element(p, "reporting")["size"] for p in all_packages]
    last = robust_z(all_packages[-1])

    assert all(b > a for a, b in zip(sizes, sizes[1:], strict=False))
    assert robust_z(all_packages[0])["reporting"] < CFG.detection.oversized.z_max
    assert [n for n, z in last.items() if z > CFG.detection.oversized.z_max] == ["reporting"]


@pytest.mark.parametrize("seed", [DEFAULT_SEED, *OTHER_SEEDS])
def test_s5_reporting_becomes_oversized_at_the_same_release_for_any_seed(seed: int) -> None:
    oversized = [robust_z(p)["reporting"] > CFG.detection.oversized.z_max for p in packages(seed)]

    assert oversized == [False] * 5 + [True] * 5


@pytest.mark.parametrize("seed", [DEFAULT_SEED, *OTHER_SEEDS])
def test_s6_search_is_noisy_without_a_trend_for_any_seed(seed: int) -> None:
    all_packages = packages(seed)
    sizes = [element(p, "search")["size"] for p in all_packages]
    lcom = [element(p, "search")["metrics"]["lcom"] for p in all_packages]
    graphs = [graph(p) for p in all_packages]

    assert len(set(sizes)) == 10 and len(set(lcom)) == 10
    assert abs(kendall_s(sizes)) <= 3  # of a possible 45
    assert abs(kendall_s(lcom)) <= 3
    assert len({g.in_degree("search") for g in graphs}) == 1
    assert len({g.out_degree("search") for g in graphs}) == 1
    assert sizes[-1] > 10_000  # what a fixed size threshold would flag
    assert all(robust_z(p)["search"] < CFG.detection.oversized.z_max for p in all_packages)


def test_s7_gateway_depends_more_and_more_on_less_stable_services() -> None:
    ratios = [unstable_dep_ratio(graph(p), "gateway") for p in packages()]

    assert ratios[0] == 0
    assert non_decreasing(ratios)
    assert len(set(ratios)) >= 5
    assert ratios[-1] >= CFG.detection.unstable.ratio


def test_s8_the_system_becomes_more_tangled() -> None:
    shares, modularity = [], []
    for package in packages():
        g = graph(package)
        shares.append(max((len(c) for c in cycles(package)), default=0) / g.number_of_nodes())
        undirected = g.to_undirected()
        communities = nx.community.greedy_modularity_communities(undirected)
        modularity.append(nx.community.modularity(undirected, communities))

    assert non_decreasing(shares) and shares[-1] > shares[0]
    assert shares[-1] >= CFG.detection.big_ball_of_mud.largest_scc_share_min
    assert kendall_s(modularity) <= -25  # falling: at least 35 of 45 pairs go down


def test_s9_more_and_more_services_share_one_datastore() -> None:
    sharing = []
    for package in packages():
        users: dict[str, set[str]] = {}
        for access in package["datastore_access"]:
            users.setdefault(access["datastore"], set()).add(access["element"])
        assert [store for store, who in users.items() if len(who) > 1] in ([], ["orders_db"])
        sharing.append(len(users["orders_db"]))

    assert sharing == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]


def test_s10_one_release_has_low_validation_confidence() -> None:
    confidence = {p["release_id"]: p["validation_confidence"] for p in packages()}

    assert confidence["v1.5.0"] == 0.60
    assert all(c >= CFG.gate.accept for r, c in confidence.items() if r != "v1.5.0")
    assert CFG.gate.exclude <= confidence["v1.5.0"] < CFG.gate.accept


def test_s11_hotfix_package_is_rejected_and_off_the_main_line() -> None:
    payload = json.loads(generate()[HOTFIX_FILE])

    with pytest.raises(ValidationError) as caught:
        ReleasePackageV1.model_validate(payload)

    assert [e["type"] for e in caught.value.errors()] == [DANGLING_DEPENDENCY]
    assert not re.match(CFG.ingest.release_line_regex, payload["release_id"])
    released = [p["released_at"] for p in packages()]
    assert released[3] < payload["released_at"] < released[4]


def test_intent_entries_repeat_in_later_packages() -> None:
    """The same decision arrives in every package after it was taken (M1 de-duplicates)."""
    seen = [{i["intent_id"] for i in p["intent"]} for p in packages()]

    assert all(earlier <= later for earlier, later in zip(seen, seen[1:], strict=False))
    assert len(seen[0]) >= 1 and len(seen[-1]) > len(seen[0])


# --- ground truth manifest -------------------------------------------------------------------


def test_manifest_describes_the_run() -> None:
    manifest = truth()

    assert manifest.system_id == "shopfront"
    assert manifest.seed == DEFAULT_SEED
    assert [r.release_id for r in manifest.releases] == RELEASES
    gates = {r.release_id: r.gate_status for r in manifest.releases}
    assert gates.pop("v1.5.0") is GateStatus.DOWNWEIGHTED
    assert set(gates.values()) == {GateStatus.ACCEPTED}
    [rejected] = manifest.rejected
    assert (rejected.file, rejected.reason) == (HOTFIX_FILE, DANGLING_DEPENDENCY)
    [rename] = manifest.renames
    assert (rename.from_id, rename.to_id, rename.at_release) == (
        "order-svc",
        "order-service",
        "v1.4.0",
    )


def test_manifest_lists_expected_events_and_expected_non_events() -> None:
    manifest = truth()
    events = {e.scenario: e for e in manifest.expected_events}

    assert set(events) == {"S1", "S2", "S5", "S7", "S8", "S9"}
    assert (events["S1"].scope, events["S1"].anti_pattern_types) == (
        Scope.INSTANCE,
        ("CyclicDependency",),
    )
    assert events["S1"].lifecycle == "growing"
    assert events["S2"].anti_pattern_types == ("HubLikeElement",)
    assert events["S5"].anti_pattern_types == ("OversizedElement",)
    assert events["S7"].anti_pattern_types == ("UnstableDependency",)
    assert events["S8"].scope is Scope.SYSTEM
    assert events["S9"].anti_pattern_types == ("SharedPersistence",)
    assert events["S9"].required is False  # first on the cut line
    assert {(n.scenario, n.element_id) for n in manifest.expected_non_events} == {
        ("S3", "legacy-auth"),
        ("S6", "search"),
    }


def test_manifest_subjects_exist_in_the_last_release() -> None:
    manifest = truth()
    last_ids = {e["id"] for e in packages()[-1]["elements"]}

    for event in manifest.expected_events:
        assert set(event.members) <= last_ids
        if event.scope is Scope.ELEMENT:
            assert event.element_id in last_ids
    assert {n.element_id for n in manifest.expected_non_events} <= last_ids
    assert {c.element_id for c in manifest.collateral} <= last_ids


def test_manifest_instances_match_the_packages() -> None:
    manifest = truth()
    by_scenario = {i.scenario: i for i in manifest.instances}
    cycle = by_scenario["S1"]

    assert cycle.first_release == "v1.1.0"
    for package in packages():
        expected = cycle.members_by_release.get(package["release_id"])
        assert ([list(expected)] if expected else []) == cycles(package)
    assert by_scenario["S9"].first_release == "v1.2.0"
    assert len(by_scenario["S9"].members_by_release) == 8


def test_manifest_series_lengths() -> None:
    lengths = truth().series_lengths

    assert lengths.element == 10  # the rename does not break a lineage
    assert lengths.system == 10
    assert lengths.instance == {"S1": 9, "S9": 8}


def test_manifest_planted_and_flat_trends_name_known_scenarios() -> None:
    manifest = truth()

    assert {t.scenario for t in manifest.expected_trends} == {"S1", "S2", "S5", "S7", "S8", "S9"}
    assert {t.scenario for t in manifest.expected_flat} == {"S3", "S6"}
    assert ("S8", "modularity", "DECREASE") in {
        (t.scenario, t.metric, t.worsening.value) for t in manifest.expected_trends
    }


def test_manifest_is_the_same_for_every_seed_apart_from_the_seed() -> None:
    a, b = truth(1).model_dump(), truth(2).model_dump()
    a.pop("seed")
    b.pop("seed")

    assert a == b
