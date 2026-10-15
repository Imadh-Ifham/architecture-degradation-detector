"""Locked decision 6: nothing C3 emits may carry severity. C4 owns ranking.

The guard reads the generated JSON Schema, because the schema is what C4 receives, and walks it
recursively so a field added later inside a nested object is caught too.
"""

import re
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel

from app.domain.audit_entry import AuditEntryV1
from app.domain.degradation_event import DegradationEventV2

BANNED = re.compile(r"(severity|priority|rank|impact|blast|hotspot|risk)", re.IGNORECASE)


def declared_names(node: Any) -> Iterator[str]:
    """Yield every property name and every definition name in a JSON Schema."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("properties", "$defs") and isinstance(value, dict):
                yield from value
            yield from declared_names(value)
    elif isinstance(node, list):
        for item in node:
            yield from declared_names(item)


@pytest.mark.parametrize("contract", [DegradationEventV2, AuditEntryV1])
def test_output_schema_has_no_severity_like_field(contract: type[BaseModel]) -> None:
    names = set(declared_names(contract.model_json_schema()))

    assert "event_key" in names, "the walk found nothing; the guard would pass vacuously"
    assert sorted(name for name in names if BANNED.search(name)) == []


def test_guard_catches_planted_fields_at_any_depth() -> None:
    schema = {
        "properties": {
            "window": {"$ref": "#/$defs/Window"},
            "Severity": {"type": "string"},
            "items": {"type": "array", "items": {"properties": {"blast_radius": {}}}},
        },
        "$defs": {
            "Window": {"properties": {"risk_score": {"type": "number"}}},
            "HotspotRank": {"type": "object"},
        },
    }

    flagged = {name for name in declared_names(schema) if BANNED.search(name)}

    assert flagged == {"Severity", "blast_radius", "risk_score", "HotspotRank"}
