"""Degradation scoring service.

Author: Dahami
Date: 2026-10-14
Description:
    Orchestrates the C4 subcomponents in pipeline order:
    ingestion -> features -> scoring_engine -> explanation -> reporting
    (evaluation runs separately on a finished report). It is the only way into
    the component; subcomponents never import each other (INSTRUCTIONS §7.3).

    Scaffold only (C4-T02): the public entry method is added by C4-T20.
"""


class DegradationScoringService:
    """Runs the C4 pipeline for one (system, release) and returns its report."""
