"""Component discovery errors.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Defines the failure types the component discovery subcomponent can raise.
    Only input-level problems are fatal: a resource that cannot be associated
    with any component is recorded as an unresolved artifact rather than
    raised, so one unrecognised manifest cannot invalidate the components that
    were discovered successfully.
"""


class ComponentDiscoveryError(Exception):
    """Base class for component discovery failures."""


class DiscoveryInputError(ComponentDiscoveryError):
    """A required upstream artifact is missing, unreadable or malformed."""


class DiscoveryWriteError(ComponentDiscoveryError):
    """The component discovery report could not be written to disk."""
