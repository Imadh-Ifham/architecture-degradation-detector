"""Canonical JSON and content hashing.

Two values with the same content must give the same bytes, otherwise their hashes differ for
reasons that have nothing to do with the content (key order, whitespace, float noise such as
``0.1 + 0.2``). Every hash in the system goes through here.

Types are part of the content: ``2`` and ``2.0`` are different values. Hash validated models,
not raw text, so each field always has one type.
"""

import hashlib
import json
import math
from typing import Any

# Significant digits kept for floats. Enough to keep any real difference, few enough to drop
# the last-bit noise of floating point arithmetic.
FLOAT_DIGITS = 12


def _normalise(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{value!r} has no canonical JSON form")
        return float(format(value, f".{FLOAT_DIGITS}g")) + 0.0  # + 0.0 turns -0.0 into 0.0
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise TypeError(f"object key {key!r} is not a string")
        return {key: _normalise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    raise TypeError(f"{type(value).__name__} has no canonical JSON form")


def canonical_json(value: Any) -> str:
    """Serialise to JSON with sorted keys, no whitespace and floats at a fixed precision."""
    return json.dumps(
        _normalise(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    """Return ``sha256:<hex>`` of the canonical JSON of ``value``."""
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
