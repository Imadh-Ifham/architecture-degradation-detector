"""Observation normalization subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Turns a recovered architecture into one uniform fact shape, whatever style it came from.

    Research module: M1.

    Re-exports the service class only. No logic lives here.
"""

from .service import ObservationNormalizationService

__all__ = ["ObservationNormalizationService"]
