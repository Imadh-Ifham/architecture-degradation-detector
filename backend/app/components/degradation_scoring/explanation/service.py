"""Explanation service.

Author: Dahami
Date: 2026-10-14
Description:
    Builds evidence bundles, retrieves evidence, generates grounded and
    ungrounded explanations, and audits them for claim-level groundedness.
    Implements CLAUDE.md §5.9.

    Scaffold only (C4-T02): the public entry method is added by C4-T23.
"""


class ExplanationService:
    """Explains top-ranked events from retrieved evidence and audits each claim."""
