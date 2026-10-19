"""Graph publishing service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Publishes the validated architecture as a graph the next component reads.

    Research module: M8.
"""

from app.domain.recovered_architecture import RecoveredArchitecture
from app.domain.validated_architecture import ValidatedArchitectureGraph

from ..models import ValidationRunResult
from ..ports import GraphProjection, ValidatedGraphPublisher, ValidationRunRecorder
from . import _document, _summary
from .models import PublishedGraph

FILE_STORE = "file"
RECORD_STORE = "record"
PROJECTION_STORE = "projection"


class GraphPublishingService:
    """Publishes the validated architecture as a graph the next component reads."""

    def __init__(
        self,
        publisher: ValidatedGraphPublisher | None = None,
        recorder: ValidationRunRecorder | None = None,
        projection: GraphProjection | None = None,
    ) -> None:
        """Bind the three stores, two of which may be absent.

        `None` means *not configured*, which is a different thing from a
        configured store that failed: a run on a laptop with no databases
        should say it wrote one store, not warn twice about two it was never
        asked to write. Only a store that exists and refused produces a
        warning.
        """

        self._publisher = publisher
        self._recorder = recorder
        self._projection = projection

    def publish(self, run: ValidationRunResult,
                architecture: RecoveredArchitecture) -> PublishedGraph:
        """Builds and publishes the validated architecture graph.

        Each verdict is attached to the relationship it describes, so the
        consumer never has to join a findings list back onto a topology - a
        join being a place where two sides can disagree about what the
        topology was.

        Every fact appears, including uncovered ones. An omitted fact would
        make the published graph quietly incomplete, and the consumer would
        compute over a subset without knowing it.

        The file is written first and a failure to write it raises: it is the
        contract, and a run that could not write it has produced nothing. The
        record and the projection follow, and either may fail - the document
        is already on disk by then, and both stores are rebuildable from it,
        so an unreachable database makes them late rather than lost.

        A release whose elements disagree on their size unit cannot be built
        at all - the document refuses in its own constructor. A release whose
        unit disagrees with the *previous* release is caught by the file
        store, which is the only thing here that can see what came before.
        """

        document = _document.build(run, architecture, _summary.build(run))

        if self._publisher is None:
            raise ValueError(
                "No publisher is configured, so this run has nowhere to write "
                "the one artifact the next component reads. The two stores are "
                "optional; this is not."
            )

        reference = self._publisher.publish(document)
        written = [FILE_STORE]
        warnings = []

        for name, store, write in (
            (RECORD_STORE, self._recorder, self._record),
            (PROJECTION_STORE, self._projection, self._project),
        ):
            if store is None:
                continue
            try:
                write(run, document)
            except Exception as error:  # noqa: BLE001
                # Deliberately broad, and the only place in the component that
                # is. The failures are a database being down, a driver timing
                # out, a constraint from somebody else's migration - an open
                # set, from two libraries, none of which may lose a run whose
                # deliverable is already on disk. What keeps it honest rather
                # than lazy is the next line: the store is named in a warning
                # and the run is never reported as a clean pass.
                warnings.append(f"{name} store failed: {error}")
            else:
                written.append(name)

        return PublishedGraph(
            reference=reference,
            stores=tuple(written),
            warnings=tuple(warnings),
        )

    def _record(
        self, run: ValidationRunResult, document: ValidatedArchitectureGraph
    ) -> None:
        self._recorder.record(run, document)

    def _project(
        self, run: ValidationRunResult, document: ValidatedArchitectureGraph
    ) -> None:
        self._projection.project(document)
