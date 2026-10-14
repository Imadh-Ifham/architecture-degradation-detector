"""Classification subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Turns a verdict and its verification into a bucket, a confidence and a route.

    Research module: M6.

    Re-exports the service class only. No logic lives here.
"""

from .service import ClassificationService

__all__ = ["ClassificationService"]
