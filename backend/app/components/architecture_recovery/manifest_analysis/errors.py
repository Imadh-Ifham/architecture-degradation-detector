"""Manifest analysis errors.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Defines the failure types the manifest analysis subcomponent can raise.
    Only input-level problems are fatal: a malformed or unsupported manifest is
    never raised, it is recorded as a diagnostic on the file's analysis result
    so one bad file cannot abort an analysis run.
"""


class ManifestAnalysisError(Exception):
    """Base class for manifest analysis failures."""


class AnalysisInputError(ManifestAnalysisError):
    """The repository inventory an analysis depends on could not be read."""


class AnalysisWriteError(ManifestAnalysisError):
    """The analysis report could not be written to disk."""
