"""Evidence for one recovered snapshot, joined from the artifacts on disk.

Author: Imadh Ifham
Date: 2026-10-20
Description:
    A projection, not a stage. Recovery already extracted this evidence and
    wrote it beside the clone; the snapshot keeps the conclusion and this
    module reunites it with the proof.

    It changes no algorithm and re-analyses nothing, which is why it lives
    inside the recovery component rather than beside it: the artifacts it
    reads are that component's own output, and their layout is its knowledge.
"""

from .service import ARTIFACTS, SnapshotDetails

__all__ = ["ARTIFACTS", "SnapshotDetails"]
