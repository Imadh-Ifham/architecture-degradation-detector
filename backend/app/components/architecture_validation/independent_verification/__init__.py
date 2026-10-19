"""Independent verification subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Re-examines a verdict as a challenge to it, using a different model.

    Research module: M5.

    Re-exports the service class only. No logic lives here.
"""

from .models import MECHANISM_CRITICAL_REFRAMING
from .service import IndependentVerificationService

__all__ = ["MECHANISM_CRITICAL_REFRAMING", "IndependentVerificationService"]
