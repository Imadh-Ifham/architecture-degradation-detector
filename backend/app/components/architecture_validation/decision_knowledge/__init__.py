"""Decision knowledge subcomponent.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Holds the decision history and answers which decision governed at a release.

    Research module: M2.

    Re-exports the service class and the shapes its callers have to build. No
    logic lives here.
"""

from .models import (
    AppendOutcome,
    DecisionStageOutcome,
    DecisionVersion,
    ModeAvailability,
)
from .service import (
    DecisionKnowledgeService,
    DecisionStoreMissing,
    NoDecisionsAvailable,
)
from .sources import DEFAULT_MODE, MODES, DecisionSourceError, SourceRequest

__all__ = [
    "DEFAULT_MODE",
    "MODES",
    "AppendOutcome",
    "DecisionKnowledgeService",
    "DecisionStageOutcome",
    "DecisionStoreMissing",
    "DecisionVersion",
    "NoDecisionsAvailable",
    "DecisionSourceError",
    "ModeAvailability",
    "SourceRequest",
]
