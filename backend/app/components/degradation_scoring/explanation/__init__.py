"""Explanation subcomponent.

Author: Dahami
Date: 2026-10-14
Description:
    Builds evidence bundles, retrieves evidence, generates grounded and
    ungrounded explanations, and audits them for claim-level groundedness.
    Implements CLAUDE.md §5.9.
"""

from app.components.degradation_scoring.explanation.service import ExplanationService

__all__ = ["ExplanationService"]
