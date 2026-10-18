"""Features subcomponent.

Author: Dahami
Date: 2026-10-14
Description:
    Computes the four severity criteria per event: blast radius (BR),
    evolutionary hotspot (EH), ADR-violation weight (AV, optional) and
    persistence (PS). Pure functions, no I/O. Implements CLAUDE.md §5.1-§5.4.
"""

from app.components.degradation_scoring.features.service import FeatureExtractionService

__all__ = ["FeatureExtractionService"]
