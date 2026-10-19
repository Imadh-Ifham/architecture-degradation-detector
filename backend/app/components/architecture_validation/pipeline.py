"""The component's description of its own pipeline.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    What the eight stages are, in run order, and how far each one has been
    built. Declared here so there is one answer to that question: the API
    publishes this, and the structural tests verify the code against it, so a
    stage cannot claim to be implemented while its service still raises.

    `implemented` is written by hand rather than inferred from the source.
    Inferring it would make deleting a subcomponent's body look like progress;
    stating it means every change of status appears in a diff.

    This module deliberately imports no subcomponent. It describes them, which
    is why it can be read without loading any of them.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StageDescription:
    """One stage of the validation pipeline.

    `research_module` is the module number in the research briefs, or None for
    a stage with no module behind it. The folders are named for what they do
    rather than numbered, because a module number implies a run order and the
    build order is not the pipeline order.
    """

    name: str
    order: int
    role: str
    research_module: str | None
    uses_model: bool
    implemented: bool

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "order": self.order,
            "role": self.role,
            "research_module": self.research_module,
            "uses_model": self.uses_model,
            "implemented": self.implemented,
        }


PIPELINE: tuple[StageDescription, ...] = (
    StageDescription(
        name="observation_normalization",
        order=1,
        role="Turns a recovered architecture into canonical observed facts.",
        research_module="M1",
        uses_model=False,
        implemented=True,
    ),
    StageDescription(
        name="decision_knowledge",
        order=2,
        role="Holds the decision history and answers which decision governed at a release.",
        research_module="M2",
        uses_model=False,
        implemented=True,
    ),
    StageDescription(
        name="evidence_retrieval",
        order=3,
        role="Assembles exactly what the model is allowed to reason from, for one fact.",
        research_module="M3",
        uses_model=False,
        implemented=True,
    ),
    StageDescription(
        name="validation_reasoning",
        order=4,
        role="Judges one fact against the decision that governs it.",
        research_module="M4",
        uses_model=True,
        implemented=True,
    ),
    StageDescription(
        name="independent_verification",
        order=5,
        role="Re-examines a verdict as a challenge to it, using a different model.",
        research_module="M5",
        uses_model=True,
        implemented=True,
    ),
    StageDescription(
        name="classification",
        order=6,
        role="Turns a verdict and its verification into a bucket, a confidence and a route.",
        research_module="M6",
        uses_model=False,
        implemented=True,
    ),
    StageDescription(
        name="architect_review",
        order=7,
        role="Queues what the system will not decide alone, and records what a person decided.",
        research_module="M7",
        uses_model=False,
        implemented=False,
    ),
    StageDescription(
        name="graph_publishing",
        order=8,
        role="Publishes the validated architecture as a graph the next component reads.",
        research_module="M8",
        uses_model=False,
        implemented=False,
    ),
)

IMPLEMENTED_STAGES = frozenset(stage.name for stage in PIPELINE if stage.implemented)

__all__ = ["IMPLEMENTED_STAGES", "PIPELINE", "StageDescription"]
