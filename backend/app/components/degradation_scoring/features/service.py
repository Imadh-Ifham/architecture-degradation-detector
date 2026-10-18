"""Features service.

Author: Dahami
Date: 2026-10-14
Description:
    Computes the four severity criteria per event: blast radius (BR),
    evolutionary hotspot (EH), ADR-violation weight (AV, optional) and
    persistence (PS). Pure functions, no I/O. Implements CLAUDE.md §5.1-§5.4.

    Scaffold only (C4-T02): the public entry method is added by C4-T11.
"""


class FeatureExtractionService:
    """Computes the BR, EH, AV and PS criteria for each resolved event."""
