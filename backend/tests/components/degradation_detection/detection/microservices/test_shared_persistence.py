"""SharedPersistence: one instance per datastore that two or more elements access."""

from app.components.degradation_detection.detection.microservices.shared_persistence import (
    SharedPersistence,
)
from app.domain.degradation_event import Scope
from tests.components.degradation_detection.detection.graphs import release
from tests.components.degradation_detection.detection.universal.run import run

DETECTOR = SharedPersistence()


def test_declaration() -> None:
    assert DETECTOR.id == "SharedPersistence"
    assert DETECTOR.catalog == "microservices"
    assert DETECTOR.styles == frozenset({"microservices"})
    assert DETECTOR.scope is Scope.INSTANCE
    assert DETECTOR.required_fields == frozenset({"datastore_access"})
    assert DETECTOR.driving_metrics == ()
    assert DETECTOR.instance_measures == ("services_per_store",)


def test_two_services_on_one_datastore_are_one_instance() -> None:
    access = [("a", "orders_db"), ("b", "orders_db"), ("c", "c_db")]

    [found] = run(release("abc", datastore_access=access), [DETECTOR])

    assert found.members == ("a", "b")
    assert found.measures == {"services_per_store": 2.0}
    assert found.local_instance_id == "SharedPersistence:orders_db"
    assert found.scope is Scope.INSTANCE


def test_instance_id_is_keyed_on_the_datastore_not_on_the_members() -> None:
    """The datastore is the identity: its users change, it does not."""
    two = run(release("abc", datastore_access=[("b", "db"), ("c", "db")]), [DETECTOR])
    three = run(
        release("abc", datastore_access=[("a", "db"), ("b", "db"), ("c", "db")]), [DETECTOR]
    )

    assert two[0].local_instance_id == three[0].local_instance_id == "SharedPersistence:db"


def test_each_shared_datastore_is_its_own_instance_in_datastore_order() -> None:
    access = [("c", "z_db"), ("d", "z_db"), ("a", "a_db"), ("b", "a_db"), ("a", "z_db")]

    found = run(release("abcd", datastore_access=access), [DETECTOR])

    assert [(i.local_instance_id, i.members) for i in found] == [
        ("SharedPersistence:a_db", ("a", "b")),
        ("SharedPersistence:z_db", ("a", "c", "d")),
    ]


def test_an_element_listed_twice_for_one_datastore_counts_once() -> None:
    """C2 may list one access per mode (read, write); it is still one service."""
    access = [("a", "db"), ("a", "db"), ("b", "db")]

    [found] = run(release("ab", datastore_access=access), [DETECTOR])

    assert found.members == ("a", "b")
    assert found.measures == {"services_per_store": 2.0}


def test_one_service_per_datastore_is_not_shared() -> None:
    access = [("a", "a_db"), ("a", "a_cache"), ("b", "b_db")]

    assert run(release("ab", datastore_access=access), [DETECTOR]) == []


def test_empty_access_list_finds_nothing() -> None:
    assert run(release("ab", datastore_access=[]), [DETECTOR]) == []


def test_missing_access_list_finds_nothing() -> None:
    """The registry skips the detector in this case; called directly it must not invent data."""
    assert run(release("ab"), [DETECTOR]) == []
