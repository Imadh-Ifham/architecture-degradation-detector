"""Small ReleasePackageV1.1 payloads for the M1 tests. Override any top-level field."""

import json
from typing import Any

from app.components.degradation_detection.ingestion.models import RawPackage
from app.components.degradation_detection.ingestion.normalise import normalise, package_hash
from app.domain.canonical_release import CanonicalRelease, GateStatus
from app.domain.release_package import ReleasePackageV1


def payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": "1.1.0",
        "system_id": "tiny",
        "release_id": "v1.0.0",
        "released_at": "2025-01-01T00:00:00Z",
        "architecture_style": "microservices",
        "granularity": "service",
        "elements": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "dependencies": [{"from": "a", "to": "b", "types": ["call"], "count": 1}],
        "validation_confidence": 0.9,
    }
    return base | overrides


def raw(body: dict[str, Any], source: str | None = None) -> RawPackage:
    name = source or f"{body.get('system_id')}__{body.get('release_id')}.json"
    return RawPackage(source=name, data=json.dumps(body).encode("utf-8"))


def canonical_from(package: ReleasePackageV1, gate_status: GateStatus) -> CanonicalRelease:
    return normalise(package, gate_status=gate_status, package_hash=package_hash(package))
