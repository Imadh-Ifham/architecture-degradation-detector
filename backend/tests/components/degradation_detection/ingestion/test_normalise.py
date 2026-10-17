"""M1 step 3: a validated package becomes a CanonicalRelease (pure)."""

from typing import Any

from structlog.testing import capture_logs

from app.components.degradation_detection.ingestion.normalise import normalise, package_hash
from app.domain.canonical_release import CanonicalRelease, GateStatus
from app.domain.release_package import ReleasePackageV1
from tests.components.degradation_detection.ingestion.packages import payload

HASH = "sha256:" + "0" * 64


def canonical(**overrides: Any) -> CanonicalRelease:
    package = ReleasePackageV1.model_validate(payload(**overrides))
    return normalise(package, gate_status=GateStatus.ACCEPTED, package_hash=HASH)


def edges(release: CanonicalRelease) -> dict[tuple[str, str], tuple[tuple[str, ...], int]]:
    return {(e.from_id, e.to_id): (e.types, e.count) for e in release.dependencies}


def test_duplicate_edges_collapse_with_counts_summed_and_types_merged() -> None:
    release = canonical(
        dependencies=[
            {"from": "a", "to": "b", "types": ["call"], "count": 1},
            {"from": "a", "to": "b", "types": ["event", "call"], "count": 1},
        ]
    )

    assert edges(release) == {("a", "b"): (("call", "event"), 2)}


def test_self_loop_is_dropped_and_logged() -> None:
    with capture_logs() as logs:
        release = canonical(
            dependencies=[
                {"from": "a", "to": "a", "count": 4},
                {"from": "a", "to": "b"},
            ]
        )

    assert edges(release) == {("a", "b"): ((), 1)}
    [log] = [entry for entry in logs if entry.get("reason") == "SELF_LOOP_DROPPED"]
    assert log["element_id"] == "a"
    assert log["release_id"] == "v1.0.0"


def test_missing_name_defaults_to_id_and_missing_kind_to_granularity() -> None:
    release = canonical(elements=[{"id": "a"}, {"id": "b", "name": "Bee", "kind": "library"}])

    by_id = {e.element_id: e for e in release.elements}
    assert (by_id["a"].name, by_id["a"].kind) == ("a", "service")
    assert (by_id["b"].name, by_id["b"].kind) == ("Bee", "library")


def test_c1_metrics_are_prefixed_and_null_stays_null() -> None:
    release = canonical(
        elements=[{"id": "a", "metrics": {"lcom": 0.4, "wmc": None}}], dependencies=[]
    )

    assert release.elements[0].metrics == {"c1.lcom": 0.4, "c1.wmc": None}


def test_output_order_does_not_depend_on_input_order() -> None:
    forward = canonical(
        elements=[{"id": "a"}, {"id": "b"}, {"id": "c"}],
        dependencies=[{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    )
    backward = canonical(
        elements=[{"id": "c"}, {"id": "b"}, {"id": "a"}],
        dependencies=[{"from": "b", "to": "c"}, {"from": "a", "to": "b"}],
    )

    assert forward == backward
    assert [e.element_id for e in forward.elements] == ["a", "b", "c"]


def test_release_fields_and_optional_inputs_are_carried_over() -> None:
    release = canonical(
        datastore_access=[{"element": "a", "datastore": "orders_db", "mode": "readwrite"}],
        intent=[
            {
                "intent_id": "ADR-1",
                "element": "a",
                "source_type": "adr",
                "adr_ref": "ADR-1",
                "decision": "split a",
            }
        ],
        provenance={"c1_model_ref": "c1://tiny/v1.0.0"},
    )

    assert release.gate_status is GateStatus.ACCEPTED
    assert release.package_hash == HASH
    assert release.validation_confidence == 0.9
    assert release.datastore_access is not None
    assert release.datastore_access[0].element_id == "a"
    assert release.intent[0].element_id == "a"
    assert release.intent[0].ref == "ADR-1"
    assert release.c1_model_ref == "c1://tiny/v1.0.0"
    assert release.c2_validation_ref is None


def test_optional_inputs_not_supplied_stay_none() -> None:
    release = canonical()

    assert release.datastore_access is None
    assert release.delegation is None


def test_hash_ignores_key_order_unknown_fields_and_the_deprecated_alias() -> None:
    intent = {"intent_id": "ADR-1", "source_type": "adr", "decision": "split a"}
    reference = ReleasePackageV1.model_validate(payload(intent=[intent | {"ref": "ADR-1"}]))
    reordered = dict(reversed(list(payload(intent=[intent | {"adr_ref": "ADR-1"}]).items())))
    reordered["colour"] = "blue"

    assert package_hash(ReleasePackageV1.model_validate(reordered)) == package_hash(reference)


def test_hash_changes_when_the_content_changes() -> None:
    first = ReleasePackageV1.model_validate(payload())
    second = ReleasePackageV1.model_validate(payload(validation_confidence=0.8))

    assert package_hash(first) != package_hash(second)
    assert package_hash(first).startswith("sha256:")
