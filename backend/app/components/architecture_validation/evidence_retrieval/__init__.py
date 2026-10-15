"""Evidence retrieval subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Assembles exactly what the model is allowed to reason from, for one fact.

    Research module: M3.

    Re-exports the service class only. No logic lives here.
"""

from .service import EvidenceRetrievalService

__all__ = ["EvidenceRetrievalService"]
