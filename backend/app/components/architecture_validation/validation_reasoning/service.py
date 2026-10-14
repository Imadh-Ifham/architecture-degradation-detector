"""Validation reasoning service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Judges one fact against the decision that governs it.

    Research module: M4.
"""

from ..models import EvidencePackage, PrimaryVerdict


class ValidationReasoningService:
    """Judges one fact against the decision that governs it."""

    def judge(self, package: EvidencePackage) -> PrimaryVerdict:
        """Produces the primary verdict for one evidence package.

        Asks the AI interface for a task and a schema, never for a model. The
        schema is requested in strict mode, so an out-of-vocabulary verdict is
        structurally impossible rather than something this code has to catch.

        Two guards then run in ordinary Python. The first checks the response
        parses. The second checks every cited reference exists in the package
        it came from - which no schema can express, and which is this
        component's only real guarantee that a conclusion is grounded.
        """

        raise NotImplementedError
