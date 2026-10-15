"""Graph publishing data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
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
