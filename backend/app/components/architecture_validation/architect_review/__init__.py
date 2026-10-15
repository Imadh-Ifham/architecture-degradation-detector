"""Architect review subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Queues what the system will not decide alone, and records what a person decided.

    Research module: M7.

    Re-exports the service class only. No logic lives here.
"""

from .service import ArchitectReviewService

__all__ = ["ArchitectReviewService"]
