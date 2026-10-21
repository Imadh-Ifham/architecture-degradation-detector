"""Architecture validation ports.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Every dependency this component has on the outside world, declared as a
    Protocol. Implementations live under `app/infrastructure/`; nothing in this
    package imports from there, and the wiring happens once in the API layer.

    Eight protocols is the complete list of ways validation touches anything
    outside itself. A ninth is worth questioning before it is written - it
    usually means a subcomponent has started doing another component's job.

    The last two arrived together, with publishing, and they are the only two
    writes in the component that are allowed to fail. A release date is
    deliberately **not** among them: reading git history is the same category
    of thing as reading source code, which this component also does not do, so
    the date arrives as a parameter of a run rather than through a port.

    Protocols rather than base classes, so an implementation never has to
    import this module either. Both sides stay independent and either can be
    replaced with a fake in a test.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from app.domain.recovered_architecture import RecoveredArchitecture
from app.domain.validated_architecture import ValidatedArchitectureGraph

from .models import AIResult, ReviewItem

if TYPE_CHECKING:
    from .architect_review.models import ReviewDecision


class RecoveredArchitectureReader(Protocol):
    """Recovery's output for one release, already in this component's shape.

    The implementation owns the translation, which is what keeps recovery's
    field names out of this package. When recovery changes, one file under
    `app/infrastructure/` changes and nothing here does.
    """

    def read(self, repository_id: str, release_id: str) -> RecoveredArchitecture:
        """Return the recovered architecture, or raise if it cannot be read."""
        ...


class SourceArtifactReader(Protocol):
    """Files from the subject repository at a release.

    Used for deployment manifests, service contracts and release notes. Paths
    come from recovery's inventory, so nothing here guesses repository layout.

    Implementations must raise rather than return empty when the repository is
    not available: the ingestion workspace is temporary and its contents can be
    removed, and an empty read would look identical to a repository that
    genuinely declares nothing.
    """

    def read_text(self, repository_id: str, release_id: str, path: str) -> str:
        """Return the file's contents, or raise if it cannot be read."""
        ...

    def list_paths(self, repository_id: str, release_id: str, pattern: str) -> list[str]:
        """Return every path matching `pattern`, sorted, possibly empty."""
        ...


class DecisionKnowledgeStore(Protocol):
    """The append-only log of architectural decision events.

    Append-only because "which decision applied at release X" has to stay
    answerable after the answer changes. An update-in-place store can report
    the present state but cannot reproduce a past one.

    One log per repository, because the thing a log accumulates is one
    system's decisions across its releases - and comparing a release against
    what the log already holds is how a withdrawn rule is detected at all.

    Events are appended as a batch rather than one at a time. A scan produces
    a handful at once and they describe one release; half of them reaching
    the log would be a history that never happened.
    """

    def append(self, repository_id: str, events: Sequence[dict]) -> None:
        """Append these events. Never edits or removes an existing one."""
        ...

    def replay(self, repository_id: str) -> list[dict]:
        """Return every event for this repository, in the order appended."""
        ...


class ReviewQueueRepository(Protocol):
    """Facts held back for an architect to confirm or reject.

    `enqueue` is idempotent on the item's id, which is content-addressed from
    the repository, the release and the fact: a run that queued an item and
    then failed later is re-run from the start, and the same fact must not
    arrive twice. An item somebody has already decided keeps its decision -
    a settled question must not depend on how many times the pipeline ran
    afterwards.

    Nothing downstream reads this. A queue that is empty, stale or unreachable
    cannot change a verdict, a confidence or a published document.
    """

    def enqueue(self, item: ReviewItem) -> str:
        """Store the item if it is not already there, and return its id."""
        ...

    def get(self, item_id: str) -> ReviewItem | None:
        """Return one item, or `None` when no such item exists."""
        ...

    def pending(self) -> list[ReviewItem]:
        """Return every undecided item, oldest first."""
        ...

    def resolve(self, decision: "ReviewDecision") -> None:
        """Record an architect's decision on one item."""
        ...


class ValidatedGraphPublisher(Protocol):
    """Where the validated graph goes once it is built.

    The one write in this component that may not fail. Everything downstream
    reads this document, and the two stores below are both rebuilt from it, so
    a run that could not write it has produced nothing.
    """

    def publish(self, document: ValidatedArchitectureGraph) -> str:
        """Publish the document and return a reference to it."""
        ...


class ValidationRunRecorder(Protocol):
    """The relational record of one completed run.

    Separate from the projection below because the two fail differently and
    are reported separately. A row written and a graph write refused is two
    outcomes, and the stage note has to say which.

    May fail. The published document is already on disk by the time this is
    called and every row is derivable from it, so an unreachable database
    makes a record late rather than lost.
    """

    def record(
        self, run: object, document: ValidatedArchitectureGraph
    ) -> None:
        """Store the run, its stages and its facts. Idempotent per run id."""
        ...


class GraphProjection(Protocol):
    """The validated graph, projected into the graph store.

    Idempotent per run: a re-run replaces its own edges rather than adding a
    second set beside them. Two runs' edges on one release double every count
    read off the graph, with no error and a graph that still draws.

    May fail, for the same reason as the recorder.
    """

    def project(self, document: ValidatedArchitectureGraph) -> None:
        """Merge this release's subgraph and sweep the previous run's edges."""
        ...


class AIClient(Protocol):
    """Model access, by task rather than by model.

    Subcomponents name a task and hand over a schema. They never name a model,
    a provider or a vendor: the architecture document requires that no
    component depend on either, and it is also what makes the model a variable
    the research can change without touching reasoning code.

    `prompt_version` and `evidence_hash` are passed rather than hashed out of
    the prompt text, because together with the task they are the cache key: an
    edited prompt file or one changed character of evidence has to miss, and
    hashing the string would hide which of the two moved.

    **How this fails is part of the contract**, because the fallback ladder is
    built on the difference. An implementation raises `ModelUnavailable` when
    nothing answered and `ModelResponseUnusable` when something answered with
    content that could not be read. Anything else - a model that cannot do
    strict schema, a task with no model configured - propagates and fails the
    run, which is the right outcome for a misconfiguration that would
    otherwise look like a bad day on a free tier.
    """

    def complete(
        self,
        task: str,
        prompt: str,
        schema: dict,
        prompt_version: str,
        evidence_hash: str,
    ) -> AIResult:
        """Return the model's response, validated against `schema`."""
        ...
