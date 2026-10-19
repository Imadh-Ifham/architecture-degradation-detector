"""Graph construction errors.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Defines the failure types the graph construction subcomponent can raise.
    A missing upstream artifact is fatal because there is no architecture to
    persist; a release that cannot be dated, or a revision whose tag moved, is
    recorded on the snapshot rather than raised.
"""


class GraphConstructionError(Exception):
    """Base class for graph construction failures."""


class GraphConstructionInputError(GraphConstructionError):
    """A required upstream artifact is missing, unreadable or malformed."""


class GraphConstructionWriteError(GraphConstructionError):
    """The graph construction report could not be written to disk."""


class SnapshotStoreError(GraphConstructionError):
    """The graph store refused the snapshot."""
