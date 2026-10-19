"""Source code analysis errors.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Defines the failure types the source code analysis subcomponent can raise.
    An unreadable source file is a diagnostic, not a fatal error; a missing or
    malformed upstream artifact is fatal because there is nothing defensible to
    analyse against.
"""


class SourceCodeAnalysisError(Exception):
    """Base class for source code analysis failures."""


class SourceCodeAnalysisInputError(SourceCodeAnalysisError):
    """An upstream inventory, discovery or dependency artifact is unusable."""


class SourceCodeAnalysisWriteError(SourceCodeAnalysisError):
    """The source code analysis report could not be written to disk."""
