"""The synthetic system `shopfront`: ten monthly releases of fifteen services.

It stands in for C2 output until real packages exist. Each scenario S1-S11 (plan Section 6.3,
T-03) is planted by the tables below; everything not named in a scenario stays constant, so a
trend C3 reports can be traced to one line here.

Design rules, each one protecting a scenario:

* The element count is 15 in every release. ``fan_in_norm`` divides by N - 1, so a changing N
  would give `legacy-auth` (S3, flat) a trend it does not have.
* No size other than `reporting` and `search` changes, and both stay above the median with a
  deviation above the MAD. The median (5000) and MAD (2000) are therefore constant, and
  ``size_rz`` of every other element is flat.
* `catalog` is called only by services that nothing in the cycle calls, and it calls only the
  cycle and `legacy-auth`. Its growth can therefore never create a second cycle.
* Fan-in stays at 3 or less for everything except `catalog` and `legacy-auth`, so the hub
  fence (Q3 + 1.5 IQR) stays below `catalog`.

"order" is a logical name: its element id is `order-svc` up to v1.3.0 and `order-service`
from v1.4.0 (S4).
"""

import random
from typing import Any

from app.components.degradation_detection.models import GateStatus
from app.components.degradation_detection.stub.models import (
    Collateral,
    ExpectedEvent,
    ExpectedNonEvent,
    FlatTruth,
    GroundTruth,
    InstanceTruth,
    RejectedPackage,
    ReleaseTruth,
    RenameTruth,
    SeriesLengths,
    TrendTruth,
)
from app.components.degradation_detection.stub.noise import trendless_order
from app.domain.degradation_event import Lifecycle, Scope, Worsening
from app.domain.release_package import DANGLING_DEPENDENCY, SCHEMA_VERSION

SYSTEM_ID = "shopfront"
ARCHITECTURE_STYLE = "microservices"
GRANULARITY = "service"
N_RELEASES = 10
RELEASE_IDS = tuple(f"v1.{i}.0" for i in range(N_RELEASES))

RENAME_AT = 4  # S4
OLD_ORDER_ID, NEW_ORDER_ID = "order-svc", "order-service"

# S10: v1.5.0 falls between the gate's exclude and accept thresholds.
CONFIDENCE = (0.91, 0.88, 0.90, 0.86, 0.89, 0.60, 0.87, 0.92, 0.85, 0.90)
LOW_CONFIDENCE_AT = 5

# S11: a back-port that is off the main release line and has a dangling dependency.
HOTFIX_ID = "v1.3.1-hotfix"
HOTFIX_BASE = 3
HOTFIX_RELEASED_AT = "2025-03-18T00:00:00Z"
HOTFIX_MISSING_ELEMENT = "fraud-check"

# Logical name -> (size in lines of code, C1 metric lcom). Order is the order in the files.
ELEMENTS: dict[str, tuple[int, float]] = {
    "order": (7600, 0.52),
    "payment": (5600, 0.41),
    "inventory": (5000, 0.38),
    "shipping": (3600, 0.33),
    "notification": (2200, 0.29),
    "catalog": (7000, 0.47),
    "legacy-auth": (9000, 0.71),
    "reporting": (8200, 0.58),
    "search": (9800, 0.45),
    "gateway": (4600, 0.36),
    "web-bff": (3000, 0.31),
    "mobile-bff": (2600, 0.30),
    "admin-console": (1500, 0.27),
    "cart": (4200, 0.35),
    "recommendation": (6400, 0.44),
}

# S5: `reporting` grows by about 1500 lines a release while nothing else grows.
REPORTING_STEP = 1500
REPORTING_JITTER = 150

# S6: `search` moves around its base value in a trendless order. The last size is above
# 10 000 lines, which a fixed size threshold flags and a trend test does not.
SEARCH_SIZE_OFFSETS = (-520, -400, -290, -170, -60, 50, 160, 270, 390, 510)
SEARCH_LCOM_OFFSETS = (-0.09, -0.07, -0.05, -0.03, -0.01, 0.01, 0.03, 0.05, 0.07, 0.09)
STATIC_SIZE_THRESHOLD = 10_000

Edge = tuple[str, str]

# v1.0.0. Eleven services call `legacy-auth` and that never changes (S3).
BASE_EDGES: tuple[Edge, ...] = (
    ("order", "legacy-auth"),
    ("order", "payment"),
    ("payment", "legacy-auth"),
    ("payment", "inventory"),
    ("inventory", "legacy-auth"),
    ("shipping", "legacy-auth"),
    ("notification", "legacy-auth"),
    ("catalog", "legacy-auth"),
    ("catalog", "inventory"),
    ("reporting", "legacy-auth"),
    ("reporting", "notification"),
    ("search", "legacy-auth"),
    ("search", "catalog"),
    ("gateway", "legacy-auth"),
    ("gateway", "inventory"),
    ("web-bff", "gateway"),
    ("web-bff", "search"),
    ("mobile-bff", "gateway"),
    ("mobile-bff", "search"),
    ("admin-console", "gateway"),
    ("cart", "legacy-auth"),
    ("cart", "catalog"),
    ("recommendation", "legacy-auth"),
)

# Release index -> edges added in that release, tagged with the scenario they belong to.
ADDED: dict[int, tuple[tuple[str, Edge], ...]] = {
    1: (
        ("S1", ("inventory", "order")),  # closes the cycle order -> payment -> inventory
        ("S2", ("recommendation", "catalog")),
        ("S7", ("gateway", "recommendation")),
    ),
    2: (("S2", ("catalog", "order")),),
    3: (
        ("S2", ("admin-console", "catalog")),
        ("S7", ("gateway", "cart")),
    ),
    4: (
        ("S1", ("order", "shipping")),  # shipping joins the cycle
        ("S1", ("shipping", "inventory")),
        ("S2", ("catalog", "payment")),
    ),
    5: (
        ("S2", ("reporting", "catalog")),
        ("S7", ("gateway", "reporting")),
    ),
    6: (
        ("S1", ("shipping", "payment")),
        ("S2", ("catalog", "shipping")),
    ),
    7: (
        ("S1", ("payment", "notification")),  # notification joins the cycle
        ("S1", ("notification", "order")),
        ("S2", ("web-bff", "catalog")),
    ),
    8: (("S2", ("catalog", "notification")),),
    9: (
        ("S1", ("notification", "shipping")),
        ("S2", ("mobile-bff", "catalog")),
    ),
}

# S7: from v1.7.0 the gateway stops calling the stable `inventory` directly.
REMOVED: dict[int, tuple[Edge, ...]] = {7: (("gateway", "inventory"),)}

# S1: members of the cycle from the release index where the membership changes.
CYCLE_MEMBERS: dict[int, tuple[str, ...]] = {
    1: ("order", "payment", "inventory"),
    4: ("order", "payment", "inventory", "shipping"),
    7: ("order", "payment", "inventory", "shipping", "notification"),
}

# Each service's own datastore, and (S9) the release index from which a service also uses
# `orders_db`, which belongs to `order`.
OWN_DATASTORE: dict[str, str] = {
    "order": "orders_db",
    "payment": "payments_db",
    "inventory": "inventory_db",
    "shipping": "shipping_db",
    "catalog": "catalog_db",
    "legacy-auth": "users_db",
    "reporting": "reporting_dw",
    "search": "search_index",
    "cart": "cart_cache",
    "recommendation": "recommendation_store",
}
SHARED_DATASTORE = "orders_db"
SHARES_ORDERS_DB_FROM: dict[str, tuple[int, str]] = {
    "payment": (2, "readwrite"),
    "shipping": (4, "read"),
    "reporting": (6, "read"),
    "notification": (8, "read"),
}

# Design decisions C2 would attach. Each arrives in every package from `from` on; M5 uses
# them after PP1. Element names are logical names.
INTENT: tuple[dict[str, Any], ...] = (
    {
        "from": 0,
        "intent_id": "DOC-001",
        "element": None,
        "source_type": "design_doc",
        "ref": "docs/architecture/data-ownership.md",
        "decision": "Every service owns its datastore; no service uses another service's.",
        "decision_kind": "principle",
        "date": "2024-11-15",
    },
    {
        "from": RENAME_AT,
        "intent_id": "ADR-007",
        "element": "order",
        "source_type": "adr",
        "ref": "ADR-007",
        "decision": "Rename order-svc to order-service to follow the service naming standard.",
        "decision_kind": "rename",
        "date": "2025-03-20",
    },
    {
        "from": 6,
        "intent_id": "ADR-009",
        "element": "reporting",
        "source_type": "adr",
        "ref": "ADR-009",
        "decision": "Move all report queries out of the other services into reporting.",
        "decision_kind": "consolidate",
        "date": "2025-05-12",
    },
)


def element_id(name: str, index: int) -> str:
    """The id a logical service name has in release ``index``."""
    if name != "order":
        return name
    return OLD_ORDER_ID if index < RENAME_AT else NEW_ORDER_ID


def released_at(index: int) -> str:
    """First day of the month, one release a month, starting December 2024."""
    months = 2024 * 12 + 11 + index
    return f"{months // 12:04d}-{months % 12 + 1:02d}-01T00:00:00Z"


def file_name(release_id: str) -> str:
    return f"{SYSTEM_ID}__{release_id}.json"


def edges_at(index: int) -> list[Edge]:
    edges = set(BASE_EDGES)
    for step in range(1, index + 1):
        edges.update(edge for _, edge in ADDED.get(step, ()))
        edges.difference_update(REMOVED.get(step, ()))
    return sorted(edges)


def cycle_members_at(index: int) -> tuple[str, ...]:
    """Ids of the planted cycle's members in release ``index``; empty before it exists."""
    starts = [start for start in CYCLE_MEMBERS if start <= index]
    if not starts:
        return ()
    return tuple(sorted(element_id(name, index) for name in CYCLE_MEMBERS[max(starts)]))


def orders_db_users_at(index: int) -> tuple[str, ...]:
    names = ["order", *(n for n, (start, _) in SHARES_ORDERS_DB_FROM.items() if start <= index)]
    return tuple(sorted(element_id(name, index) for name in names))


def _all_edges() -> list[Edge]:
    return sorted(set(BASE_EDGES) | {edge for added in ADDED.values() for _, edge in added})


class _Noise:
    """Everything the seed decides. Each part has its own stream, so they do not interact."""

    def __init__(self, seed: int) -> None:
        counts = random.Random(f"{seed}:edge-counts")
        self.edge_count = {edge: counts.randint(1, 6) for edge in _all_edges()}

        growth = random.Random(f"{seed}:reporting-size")
        base = ELEMENTS["reporting"][0]
        self.reporting_size = [
            base + REPORTING_STEP * i + growth.randint(-REPORTING_JITTER, REPORTING_JITTER)
            for i in range(N_RELEASES)
        ]

        base = ELEMENTS["search"][0]
        self.search_size = trendless_order(
            [base + offset for offset in SEARCH_SIZE_OFFSETS],
            random.Random(f"{seed}:search-size"),
            accept=lambda order: order[-1] > STATIC_SIZE_THRESHOLD,
        )
        lcom = ELEMENTS["search"][1]
        self.search_lcom = trendless_order(
            [round(lcom + offset, 2) for offset in SEARCH_LCOM_OFFSETS],
            random.Random(f"{seed}:search-lcom"),
        )


def _elements(index: int, noise: _Noise) -> list[dict[str, Any]]:
    elements = []
    for name, (size, lcom) in ELEMENTS.items():
        if name == "reporting":
            size = noise.reporting_size[index]
        elif name == "search":
            size, lcom = noise.search_size[index], noise.search_lcom[index]
        renamed = name == "order" and index >= RENAME_AT
        elements.append(
            {
                "id": element_id(name, index),
                "name": element_id(name, index),
                "kind": GRANULARITY,
                "size": size,
                "size_unit": "loc",
                "aliases": [OLD_ORDER_ID] if renamed else [],
                "layer": None,
                "metrics": {"lcom": lcom},
                "extra": {},
            }
        )
    return elements


def _dependencies(index: int, noise: _Noise) -> list[dict[str, Any]]:
    return [
        {
            "from": element_id(source, index),
            "to": element_id(target, index),
            "types": ["call"],
            "count": noise.edge_count[(source, target)],
        }
        for source, target in edges_at(index)
    ]


def _datastore_access(index: int) -> list[dict[str, Any]]:
    access = [
        {"element": element_id(name, index), "datastore": store, "mode": "readwrite"}
        for name, store in OWN_DATASTORE.items()
    ]
    access += [
        {"element": element_id(name, index), "datastore": SHARED_DATASTORE, "mode": mode}
        for name, (start, mode) in SHARES_ORDERS_DB_FROM.items()
        if start <= index
    ]
    return access


def _intent(index: int) -> list[dict[str, Any]]:
    entries = []
    for entry in INTENT:
        if entry["from"] > index:
            continue
        item = {key: value for key, value in entry.items() if key != "from"}
        if item["element"] is not None:
            item["element"] = element_id(item["element"], index)
        entries.append(item)
    return entries


def _package(index: int, noise: _Noise) -> dict[str, Any]:
    release_id = RELEASE_IDS[index]
    return {
        "schema_version": SCHEMA_VERSION,
        "system_id": SYSTEM_ID,
        "release_id": release_id,
        "released_at": released_at(index),
        "architecture_style": ARCHITECTURE_STYLE,
        "granularity": GRANULARITY,
        "elements": _elements(index, noise),
        "dependencies": _dependencies(index, noise),
        "datastore_access": _datastore_access(index),
        "delegation": None,
        "intent": _intent(index),
        "validation_confidence": CONFIDENCE[index],
        "provenance": {
            "c1_model_ref": f"c1://{SYSTEM_ID}/{release_id}",
            "c2_validation_ref": f"c2://{SYSTEM_ID}/{release_id}",
        },
    }


def _hotfix_package(noise: _Noise) -> dict[str, Any]:
    package = _package(HOTFIX_BASE, noise)
    package["release_id"] = HOTFIX_ID
    package["released_at"] = HOTFIX_RELEASED_AT
    package["dependencies"].append(
        {"from": "payment", "to": HOTFIX_MISSING_ELEMENT, "types": ["call"], "count": 1}
    )
    package["provenance"] = {
        "c1_model_ref": f"c1://{SYSTEM_ID}/{HOTFIX_ID}",
        "c2_validation_ref": f"c2://{SYSTEM_ID}/{HOTFIX_ID}",
    }
    return package


def build_packages(seed: int) -> dict[str, dict[str, Any]]:
    """File name -> package payload: the ten main-line releases, then the rejected hotfix."""
    noise = _Noise(seed)
    packages = {file_name(RELEASE_IDS[i]): _package(i, noise) for i in range(N_RELEASES)}
    packages[file_name(HOTFIX_ID)] = _hotfix_package(noise)
    return packages


def build_ground_truth(seed: int) -> GroundTruth:
    last = N_RELEASES - 1
    cycle_start = min(CYCLE_MEMBERS)
    sharing_start = min(start for start, _ in SHARES_ORDERS_DB_FROM.values())
    cycle = {RELEASE_IDS[i]: cycle_members_at(i) for i in range(cycle_start, N_RELEASES)}
    sharing = {RELEASE_IDS[i]: orders_db_users_at(i) for i in range(sharing_start, N_RELEASES)}

    return GroundTruth(
        system_id=SYSTEM_ID,
        seed=seed,
        architecture_style=ARCHITECTURE_STYLE,
        granularity=GRANULARITY,
        releases=tuple(
            ReleaseTruth.model_validate(
                {
                    "release_id": RELEASE_IDS[i],
                    "file": file_name(RELEASE_IDS[i]),
                    "released_at": released_at(i),
                    "validation_confidence": CONFIDENCE[i],
                    "gate_status": (
                        GateStatus.DOWNWEIGHTED if i == LOW_CONFIDENCE_AT else GateStatus.ACCEPTED
                    ),
                }
            )
            for i in range(N_RELEASES)
        ),
        rejected=(
            RejectedPackage(
                release_id=HOTFIX_ID, file=file_name(HOTFIX_ID), reason=DANGLING_DEPENDENCY
            ),
        ),
        renames=(
            RenameTruth(
                from_id=OLD_ORDER_ID, to_id=NEW_ORDER_ID, at_release=RELEASE_IDS[RENAME_AT]
            ),
        ),
        instances=(
            InstanceTruth(
                scenario="S1",
                anti_pattern_type="CyclicDependency",
                first_release=RELEASE_IDS[cycle_start],
                members_by_release=cycle,
            ),
            InstanceTruth(
                scenario="S9",
                anti_pattern_type="SharedPersistence",
                first_release=RELEASE_IDS[sharing_start],
                members_by_release=sharing,
            ),
        ),
        expected_events=(
            ExpectedEvent(
                scenario="S1",
                scope=Scope.INSTANCE,
                anti_pattern_types=("CyclicDependency",),
                members=cycle_members_at(last),
                lifecycle=Lifecycle.GROWING,
                description="One cycle that appears at v1.1.0 and absorbs two more services.",
            ),
            ExpectedEvent(
                scenario="S2",
                scope=Scope.ELEMENT,
                anti_pattern_types=("HubLikeElement",),
                element_id="catalog",
                description="catalog gains a caller or a callee in every release.",
            ),
            ExpectedEvent(
                scenario="S5",
                scope=Scope.ELEMENT,
                anti_pattern_types=("OversizedElement",),
                element_id="reporting",
                description="reporting grows every release while the rest of the system does not.",
            ),
            ExpectedEvent(
                scenario="S7",
                scope=Scope.ELEMENT,
                anti_pattern_types=("UnstableDependency",),
                element_id="gateway",
                description="gateway adds dependencies on services less stable than itself.",
            ),
            ExpectedEvent(
                scenario="S8",
                scope=Scope.SYSTEM,
                anti_pattern_types=("BigBallOfMud", "MetricDrift"),
                members=cycle_members_at(last),
                description=(
                    "The largest cycle covers a growing share of the system and modularity "
                    "falls. BigBallOfMud if its presence thresholds are met at v1.9.0, "
                    "otherwise MetricDrift."
                ),
            ),
            ExpectedEvent(
                scenario="S9",
                scope=Scope.INSTANCE,
                anti_pattern_types=("SharedPersistence",),
                members=orders_db_users_at(last),
                required=False,
                description=(
                    "orders_db is used by one more service every second release. Not required: "
                    "the SharedPersistence detector is first on the cut line."
                ),
            ),
        ),
        expected_non_events=(
            ExpectedNonEvent(
                scenario="S3",
                element_id="legacy-auth",
                static_flag="fan_in > 10",
                description="Eleven callers in every release: heavily used, but not getting worse.",
            ),
            ExpectedNonEvent(
                scenario="S6",
                element_id="search",
                static_flag=f"size > {STATIC_SIZE_THRESHOLD}",
                description="Size and lcom move up and down with no trend.",
            ),
        ),
        expected_trends=(
            _trend("S1", Scope.INSTANCE, "S1", "member_count"),
            _trend("S1", Scope.SYSTEM, SYSTEM_ID, "cyclic_edge_count"),
            _trend("S2", Scope.ELEMENT, "catalog", "fan_in_norm"),
            _trend("S2", Scope.ELEMENT, "catalog", "fan_out_norm"),
            _trend("S5", Scope.ELEMENT, "reporting", "size_rz"),
            _trend("S7", Scope.ELEMENT, "gateway", "unstable_dep_ratio"),
            _trend("S8", Scope.SYSTEM, SYSTEM_ID, "largest_scc_share"),
            _trend("S8", Scope.SYSTEM, SYSTEM_ID, "modularity", Worsening.DECREASE),
            _trend("S9", Scope.INSTANCE, "S9", "services_per_store"),
        ),
        expected_flat=(
            FlatTruth(scenario="S3", scope=Scope.ELEMENT, subject="legacy-auth", metric="fan_in"),
            FlatTruth(
                scenario="S3", scope=Scope.ELEMENT, subject="legacy-auth", metric="fan_in_norm"
            ),
            FlatTruth(scenario="S3", scope=Scope.ELEMENT, subject="legacy-auth", metric="size_rz"),
            FlatTruth(scenario="S6", scope=Scope.ELEMENT, subject="search", metric="size"),
            FlatTruth(scenario="S6", scope=Scope.ELEMENT, subject="search", metric="size_rz"),
            FlatTruth(scenario="S6", scope=Scope.ELEMENT, subject="search", metric="c1.lcom"),
            FlatTruth(scenario="S6", scope=Scope.ELEMENT, subject="search", metric="fan_out"),
        ),
        collateral=_collateral(last),
        series_lengths=SeriesLengths(
            element=N_RELEASES,
            system=N_RELEASES,
            instance={"S1": len(cycle), "S9": len(sharing)},
        ),
    )


def _trend(
    scenario: str,
    scope: Scope,
    subject: str,
    metric: str,
    worsening: Worsening = Worsening.INCREASE,
) -> TrendTruth:
    return TrendTruth(
        scenario=scenario, scope=scope, subject=subject, metric=metric, worsening=worsening
    )


def _collateral(last: int) -> tuple[Collateral, ...]:
    """Elements that an edge of a scenario touches, other than the scenario's own subject."""
    subjects = {"S2": "catalog", "S7": "gateway"}
    touched: dict[str, str] = {name: "S1" for members in CYCLE_MEMBERS.values() for name in members}
    for added in ADDED.values():
        for scenario, edge in added:
            for name in edge:
                if name != subjects.get(scenario) and name not in subjects.values():
                    touched.setdefault(name, scenario)
    reasons = {
        "S1": "Member of the growing cycle: its scc_size and its coupling rise with it.",
        "S2": "Gains one dependency to or from catalog as the hub grows.",
        "S7": "Gains gateway as a caller.",
    }
    return tuple(
        Collateral(
            element_id=element_id(name, last), scenario=scenario, description=reasons[scenario]
        )
        for name, scenario in sorted(touched.items())
        if name != "reporting"  # subject of S5; a second event on a subject is already tolerated
    )
