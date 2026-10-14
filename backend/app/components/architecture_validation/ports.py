"""Architecture validation ports.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Every dependency this component has on the outside world, declared as a
    Protocol. Implementations live under `app/infrastructure/`; nothing in this
    package imports from there, and the wiring happens once in the API layer.

    Six protocols is the complete list of ways validation touches anything
    outside itself. A seventh is worth questioning before it is written - it
    usually means a subcomponent has started doing another component's job.

    Protocols rather than base classes, so an implementation never has to
    import this module either. Both sides stay independent and either can be
    replaced with a fake in a test.
"""

from typing import Protocol

from app.domain.recovered_architecture import RecoveredArchitecture
from app.domain.validated_architecture import ValidatedArchitectureGraph

from .models import AIResult, EvidencePackage, ReviewItem


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
    """

    def append(self, event: dict) -> None:
        """Append one event. Never edits or removes an existing event."""
        ...

    def replay(self) -> list[dict]:
        """Return every event in the order it was appended."""
        ...


class ReviewQueueRepository(Protocol):
    """Facts held back for an architect to confirm or reject."""

    def enqueue(self, item: ReviewItem) -> str:
        """Store the item and return its id."""
        ...

    def pending(self) -> list[ReviewItem]:
        """Return every unresolved item, oldest first."""
        ...

    def resolve(self, item_id: str, accepted: bool, resolved_by: str) -> None:
        """Record an architect's decision on one item."""
        ...


class ValidatedGraphPublisher(Protocol):
    """Where the validated graph goes once it is built."""

    def publish(self, document: ValidatedArchitectureGraph) -> str:
        """Publish the document and return a reference to it."""
        ...


class AIClient(Protocol):
    """Model access, by task rather than by model.

    Subcomponents name a task and hand over a schema. They never name a model,
    a provider or a vendor: the architecture document requires that no
    component depend on either, and it is also what makes the model a variable
    the research can change without touching reasoning code.
    """

    def complete(self, task: str, prompt: str, schema: dict) -> AIResult:
        """Return the model's response, validated against `schema`."""
        ...
