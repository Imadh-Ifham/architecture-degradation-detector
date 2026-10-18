"""Reporting subcomponent.

Author: Dahami
Date: 2026-10-14
Description:
    Writes the severity report (JSON + HTML) and the run manifest.
    Implements CLAUDE.md §4.2 and §6.
"""

from app.components.degradation_scoring.reporting.service import ReportingService

__all__ = ["ReportingService"]
