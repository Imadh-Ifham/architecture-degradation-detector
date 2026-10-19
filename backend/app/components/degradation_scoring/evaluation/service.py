"""Evaluation service.

Author: Dahami
Date: 2026-10-14
Description:
    Builds ground-truth labels and reports ranking metrics, bootstrap
    confidence intervals, baselines and ablations. Implements CLAUDE.md §5.10.

    Scaffold only (C4-T02): the public entry method is added by C4-T27.
"""


class EvaluationService:
    """Evaluates a severity ranking against ground-truth labels."""
