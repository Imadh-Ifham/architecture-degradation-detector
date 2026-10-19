"""Dependency resolution errors.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Defines the failure types the dependency resolution subcomponent can raise.
    A malformed or missing upstream artifact is fatal because the resolver has
    nothing defensible to resolve against; ambiguity inside the evidence is not
    an error and is recorded in the report instead.
"""


class DependencyResolutionError(Exception):
    """Base class for dependency resolution failures."""


class DependencyResolutionInputError(DependencyResolutionError):
    """An upstream component-discovery or manifest-analysis artifact is unusable."""


class DependencyResolutionWriteError(DependencyResolutionError):
    """The dependency resolution report could not be written to disk."""
