"""Graph publishing subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Publishes the validated architecture as a graph the next component reads.

    Research module: M8.

    Re-exports the service class only. No logic lives here.
"""

from .service import GraphPublishingService

__all__ = ["GraphPublishingService"]
