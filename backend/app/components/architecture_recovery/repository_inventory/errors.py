"""Repository inventory errors.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Defines the failure types the inventory module can raise. Per-file problems
    (unreadable paths, malformed manifests) are never fatal: they are collected
    as warnings so a single bad file cannot abort an inventory run.
"""


class RepositoryInventoryError(Exception):
    """Base class for repository inventory failures."""


class InventoryScanError(RepositoryInventoryError):
    """The inventory root is missing or is not a directory."""


class InventoryWriteError(RepositoryInventoryError):
    """The inventory could not be written to disk."""
