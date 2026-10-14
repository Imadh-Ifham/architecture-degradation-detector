"""Decision knowledge subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Holds the decision history and answers which decision governed at a release.

    Research module: M2.

    Re-exports the service class only. No logic lives here.
"""

from .service import DecisionKnowledgeService

__all__ = ["DecisionKnowledgeService"]
