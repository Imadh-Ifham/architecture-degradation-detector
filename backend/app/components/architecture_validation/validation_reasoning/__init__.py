"""Validation reasoning subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Judges one fact against the decision that governs it.

    Research module: M4.

    Re-exports the service class only. No logic lives here.
"""

from .service import ArbiterOnlyRefused, ValidationReasoningService

__all__ = ["ArbiterOnlyRefused", "ValidationReasoningService"]
