"""Intent extraction subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Reads architectural intent out of whatever the repository actually contains.

    Research module: new.

    Re-exports the service class only. No logic lives here.
"""

from .service import IntentExtractionService

__all__ = ["IntentExtractionService"]
