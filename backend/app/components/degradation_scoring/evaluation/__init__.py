"""Evaluation subcomponent.

Author: Dahami
Date: 2026-10-14
Description:
    Builds ground-truth labels and reports ranking metrics, bootstrap
    confidence intervals, baselines and ablations. Implements CLAUDE.md §5.10.
"""

from app.components.degradation_scoring.evaluation.service import EvaluationService

__all__ = ["EvaluationService"]
