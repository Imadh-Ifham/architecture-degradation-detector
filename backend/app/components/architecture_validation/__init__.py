"""Architecture validation component.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Validates the architecture recovered from a release against the
    architectural intent recorded for that release, and publishes the result
    as a graph with each verdict carried on the relationship it describes.

    The subcomponents are named for what they do. The research briefs number
    their modules M1-M8, and the mapping is kept here rather than in folder
    names: module numbers imply a run order, and the build order is not the
    pipeline order.

      M1  Architecture Observation Normalization  -> observation_normalization
      M2  Architectural Knowledge and Evolution   -> decision_knowledge
      M3  Architecture-Aware Evidence Retrieval   -> evidence_retrieval
      M4  Architectural Validation Reasoner       -> validation_reasoning
      M5  Independent Verification                -> independent_verification
      M6  Validation Classification and Confidence-> classification
      M7  Architect Review                        -> architect_review
      M8  Validated Architecture Graph Publisher  -> graph_publishing

    There were nine for a while. The briefs assume architectural intent is
    read from decision records and most repositories hold none, so a ninth
    subcomponent was added to read intent from what they do hold. Reading it
    produces decision records, and the thing that holds decision records is
    M2 - so it is one of that module's sources rather than a module of its
    own, and the count matches the research again.

    Only this package's service is public. Subcomponents never import each
    other, and nothing outside the component imports a subcomponent.
"""

from .pipeline import PIPELINE, StageDescription
from .service import ArchitectureValidationService

__all__ = ["PIPELINE", "ArchitectureValidationService", "StageDescription"]
