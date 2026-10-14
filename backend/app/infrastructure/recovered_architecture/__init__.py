"""Recovered architecture adapters.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Reads the architecture recovery component's output and translates it into
    the shape the validation component consumes.

    This package is the boundary that absorbs recovery's churn. Recovery is
    still being built, so its output shape moves; everything that knows about
    that shape lives here, and the validation component sees only its own
    domain model through a protocol.
"""

from .fixture_reader import FixtureArchitectureReader
from .inventory_file_reader import InventoryFileArchitectureReader
from .inventory_schema import (
    CONTRACT_VERSION,
    InventoryContractError,
    InventoryFieldError,
    InventoryVersionError,
)

__all__ = [
    "CONTRACT_VERSION",
    "FixtureArchitectureReader",
    "InventoryContractError",
    "InventoryFieldError",
    "InventoryFileArchitectureReader",
    "InventoryVersionError",
]
