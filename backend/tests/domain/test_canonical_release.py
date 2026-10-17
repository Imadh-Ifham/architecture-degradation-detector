"""CanonicalRelease, the normalised release M1 stores: strict, immutable, null-preserving."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain import canonical_release
from app.domain.canonical_release import (
    CanonicalRelease,
    DependencyEdge,
    ElementSnapshot,
    GateStatus,
    ReleaseModel,
)
from app.domain.release_package import ArchitectureStyle

HASH = "sha256:" + "a" * 64


def element(element_id: str = "a") -> ElementSnapshot:
    return ElementSnapshot(element_id=element_id, name=element_id, kind="service")


def release() -> CanonicalRelease:
    return CanonicalRelease(
        system_id="shopfront",
        release_id="v1.0.0",
        released_at=datetime(2025, 1, 1, tzinfo=UTC),
        architecture_style=ArchitectureStyle.MICROSERVICES,
        granularity="service",
        validation_confidence=0.83,
        gate_status=GateStatus.ACCEPTED,
        package_hash=HASH,
        elements=(element("a"), element("b")),
        dependencies=(DependencyEdge(from_id="a", to_id="b", types=("call",), count=2),),
    )


def test_canonical_release_holds_the_normalised_package() -> None:
    canonical = release()

    assert canonical.elements[0].size is None
    assert canonical.datastore_access is None
    assert canonical.delegation is None
    assert canonical.intent == ()


def test_release_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ElementSnapshot.model_validate({"element_id": "a", "name": "a", "kind": "x", "colour": 1})


def test_release_models_are_immutable() -> None:
    snapshot = element()

    with pytest.raises(ValidationError, match="frozen"):
        snapshot.name = "renamed"  # type: ignore[misc]


def test_every_release_model_is_strict_and_frozen() -> None:
    found = [
        cls
        for cls in vars(canonical_release).values()
        if isinstance(cls, type)
        and issubclass(cls, ReleaseModel)
        and cls.__module__ == canonical_release.__name__
    ]

    assert len(found) == 6
    for cls in found:
        assert cls.model_config.get("extra") == "forbid", cls.__name__
        assert cls.model_config.get("frozen") is True, cls.__name__


def test_release_round_trips_through_json() -> None:
    """The store keeps the release as JSON-ready data and must get the same model back."""
    canonical = release()

    assert CanonicalRelease.model_validate(canonical.model_dump(mode="json")) == canonical
