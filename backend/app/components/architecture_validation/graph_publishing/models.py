"""Graph publishing data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.

    The published document itself is not here: it crosses a component
    boundary, so it lives in `app/domain/validated_architecture.py` with a
    committed fixture beside it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicationTarget:
    """Where a published graph is written.

    The file is the contract. A graph-store projection is an additional view
    generated from the published file, and a projection that fails logs a
    warning rather than failing the run - the deliverable is already on disk
    by then.
    """

    directory: str
    project_to_graph_store: bool = False

    def filename(self, release_id: str) -> str:
        return f"{release_id}.graph.json"


@dataclass(frozen=True)
class PublishedGraph:
    """What one publish attempt produced.

    Returned rather than left on the service, because the stage that reports
    it is in another module: an orchestrator reading mutable attributes off a
    subcomponent would be two places holding one answer, and the second run
    would overwrite what the first one reported.

    `stores` names what took the document and `warnings` names what refused.
    Both travel, because *written to file* and *written to file, record and
    projection* are different claims about where a run can be found - and a
    store that was never configured is not a store that failed.
    """

    reference: str
    stores: tuple[str, ...]
    warnings: tuple[str, ...] = ()
