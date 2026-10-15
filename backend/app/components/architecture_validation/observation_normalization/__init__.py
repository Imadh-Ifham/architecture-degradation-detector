"""Observation normalization subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Turns a recovered architecture into one uniform fact shape, whatever style it came from.

    Research module: M1.

    Re-exports the service class, plus the release check and the error it
    raises. No logic lives here.

    Two names beyond the service are public for one reason: the transport
    layer has to refuse an unorderable release identifier against the field
    that carried it, before anything is read from disk, and it has to do that
    with this function rather than with a second implementation of it. A
    release identifier that cannot be ordered is the caller's input, not a
    server fault. Everything else about release parsing stays private to
    `_release.py`.
"""

from .._release import UnorderableRelease, release_sort_key
from .service import ObservationNormalizationService

__all__ = [
    "ObservationNormalizationService",
    "UnorderableRelease",
    "release_sort_key",
]
