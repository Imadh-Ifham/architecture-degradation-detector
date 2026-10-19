"""Classification subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Turns a verdict and its verification into a bucket, a confidence and a route.

    Research module: M6.

    Re-exports the service class, the route vocabulary and the one helper the
    orchestrator needs to say what happened to a single fact. No logic lives
    here.
"""

from .models import Route
from .service import ClassificationService, per_fact_mode

__all__ = ["ClassificationService", "Route", "per_fact_mode"]
