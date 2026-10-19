"""The committed corpus, assembled once for every test that reasons over it.

Author: Aman Mohamed M.A
Date: 2026-10-18
Description:
    One definition of `package()`, shared by the reasoning tests and the
    verification tests.

    Two copies would be the one duplication this component cannot have. The
    verifier's whole claim is that it read the *identical* evidence the
    reasoner read, asserted on a hash, and two helper functions drifting
    apart would make that assertion pass over two different questions while
    every test stayed green.

    Nothing here is a stand-in. The architecture comes off the recorded
    snapshots, the decisions off the committed fixture store, and the package
    out of M3 as the pipeline assembles it - so a prompt test is a test of
    the real prompt against the real corpus.
"""

from pathlib import Path

from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
)
from app.components.architecture_validation.evidence_retrieval import (
    EvidenceRetrievalService,
)
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.recovery_gateway import SnapshotFileReader

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"
SUBJECT = FIXTURES / "subject"
SNAPSHOTS = Path(__file__).resolve().parents[3] / "data" / "snapshots"

REPOSITORY = "online-boutique"


class WorkspaceReader:
    """Reads the generated subject tree in place of an ingested checkout."""

    def read_text(self, repository_id, release_id, path):
        return (SUBJECT / release_id / path).read_text(encoding="utf-8")

    def list_paths(self, repository_id, release_id, pattern):
        root = SUBJECT / release_id
        return sorted(
            str(match.relative_to(root)).replace("\\", "/")
            for match in root.glob(pattern)
            if match.is_file()
        )


def architecture(release: str = "v0.10.0"):
    return SnapshotFileReader(SNAPSHOTS).read(REPOSITORY, release)


def facts(release: str = "v0.10.0"):
    return ObservationNormalizationService().normalise(architecture(release)).facts


def knowledge() -> DecisionKnowledgeService:
    return DecisionKnowledgeService(
        WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
    )


def service() -> EvidenceRetrievalService:
    return EvidenceRetrievalService(WorkspaceReader())


def recorded_fact(subject="frontend", object_="cartservice", release="v0.10.0"):
    """One of the real facts, picked by the names a person would use."""

    return next(
        observed
        for observed in facts(release)
        if observed.subject.name == subject and observed.object.name == object_
    )


def resolution_for(observed):
    return knowledge().resolve(observed, REPOSITORY)


def package(subject="frontend", object_="cartservice", release="v0.10.0"):
    """A real sealed package, out of M3 and over the committed corpus."""

    observed = recorded_fact(subject, object_, release)
    return service().assemble(observed, resolution_for(observed), architecture(release))
