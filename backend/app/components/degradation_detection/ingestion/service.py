"""M1 Ingestion & Combination: the only door into C3 (plan Section 4, M1).

Each package goes Receive -> Validate -> Normalise -> Idempotency -> Gate -> Persist. A package
that fails any step before Persist is rejected with a reason code and never touches the store,
so one bad file cannot leave half a release behind. The timeline is a separate, pure query over
what was stored.

``timeline`` is a second public method on purpose (owner decision, T-04): M1 owns the release
store, and later modules must read releases through it rather than from the repository.
"""

import json
from collections.abc import Iterable
from typing import Any

import structlog
from pydantic import ValidationError

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.ingestion.gate import gate
from app.components.degradation_detection.ingestion.models import (
    INPUT_NOT_JSON,
    INPUT_SCHEMA_INVALID,
    PACKAGE_TOO_LARGE,
    RELEASE_CONFLICT,
    RELEASE_REPLACED,
    RELEASE_STORED,
    RELEASE_UNCHANGED,
    IngestOutcome,
    IngestReport,
    IngestStatus,
    RawPackage,
)
from app.components.degradation_detection.ingestion.normalise import normalise, package_hash
from app.components.degradation_detection.ingestion.ordering import timeline
from app.components.degradation_detection.models import Timeline
from app.components.degradation_detection.ports import Clock, ReleaseRepository
from app.domain.release_package import (
    DANGLING_DEPENDENCY,
    DUPLICATE_ELEMENT_ID,
    ReleasePackageV1,
)

log = structlog.get_logger(__name__)

# Semantic rule violations keep their own code; every other validation error is a shape error.
_SEMANTIC_CODES = frozenset({DUPLICATE_ELEMENT_ID, DANGLING_DEPENDENCY})


class _Rejected(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _parse(raw: RawPackage, max_bytes: int) -> dict[str, Any]:
    # The size is checked on the bytes before parsing, so an oversized file is never loaded.
    if len(raw.data) > max_bytes:
        raise _Rejected(PACKAGE_TOO_LARGE, f"{len(raw.data)} bytes, limit {max_bytes}")
    try:
        parsed = json.loads(raw.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Rejected(INPUT_NOT_JSON, str(exc)) from exc
    if not isinstance(parsed, dict):
        raise _Rejected(
            INPUT_SCHEMA_INVALID, f"expected a JSON object, got {type(parsed).__name__}"
        )
    return parsed


def _validate(payload: dict[str, Any]) -> ReleasePackageV1:
    try:
        return ReleasePackageV1.model_validate(payload)
    except ValidationError as exc:
        codes = {error["type"] for error in exc.errors()} & _SEMANTIC_CODES
        reason = min(codes) if codes else INPUT_SCHEMA_INVALID
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '<package>'}: {error['msg']}"
            for error in exc.errors()
        )
        raise _Rejected(reason, detail) from exc


def _identity(payload: dict[str, Any]) -> dict[str, str | None]:
    """Best-effort ids for the report and logs of a package that failed validation."""
    return {
        key: value if isinstance(value := payload.get(key), str) else None
        for key in ("system_id", "release_id")
    }


class IngestService:
    def __init__(self, repo: ReleaseRepository, clock: Clock, cfg: C3Config) -> None:
        self._repo = repo
        self._clock = clock
        self._cfg = cfg

    def ingest(
        self, packages: Iterable[RawPackage], *, replace_changed: bool = False
    ) -> IngestReport:
        """Ingest each package independently; one rejection never stops the others.

        A release already stored with different content is rejected (``RELEASE_CONFLICT``)
        unless ``replace_changed`` is set. The API sets it: there the packages are built from
        C2's latest published graphs, and a release validated again is meant to replace the
        old one. The CLI keeps the strict default, so a file edited by hand cannot overwrite a
        release silently.
        """
        return IngestReport(
            outcomes=tuple(self._ingest_one(raw, replace_changed) for raw in packages)
        )

    def timeline(self, system_id: str) -> Timeline:
        """The ordered, gated main-line releases of one system, as of now."""
        return timeline(system_id, self._repo.list_releases(system_id), self._cfg.ingest)

    def _ingest_one(self, raw: RawPackage, replace_changed: bool) -> IngestOutcome:
        payload: dict[str, Any] = {}
        try:
            payload = _parse(raw, self._cfg.ingest.max_package_bytes)
            package = _validate(payload)
        except _Rejected as rejected:
            return self._reject(raw.source, rejected, **_identity(payload))

        ids = {"system_id": package.system_id, "release_id": package.release_id}
        digest = package_hash(package)
        status = gate(package.validation_confidence, self._cfg.gate)

        stored_hash = self._repo.find_package_hash(package.system_id, package.release_id)
        if stored_hash == digest:
            log.info(RELEASE_UNCHANGED, reason=RELEASE_UNCHANGED, source=raw.source, **ids)
            return IngestOutcome(
                source=raw.source, status=IngestStatus.UNCHANGED, gate_status=status, **ids
            )
        if stored_hash is not None and replace_changed:
            release = normalise(package, gate_status=status, package_hash=digest)
            self._repo.replace(release, payload, self._clock.now())
            log.info(
                RELEASE_REPLACED,
                reason=RELEASE_REPLACED,
                source=raw.source,
                gate_status=status.value,
                previous_hash=stored_hash,
                **ids,
            )
            return IngestOutcome(
                source=raw.source, status=IngestStatus.REPLACED, gate_status=status, **ids
            )
        if stored_hash is not None:
            detail = f"stored {stored_hash}, received {digest}; re-ingest is not supported yet"
            return self._reject(raw.source, _Rejected(RELEASE_CONFLICT, detail), **ids)

        release = normalise(package, gate_status=status, package_hash=digest)
        self._repo.add(release, payload, self._clock.now())
        log.info(
            RELEASE_STORED,
            reason=RELEASE_STORED,
            source=raw.source,
            gate_status=status.value,
            **ids,
        )
        return IngestOutcome(
            source=raw.source, status=IngestStatus.STORED, gate_status=status, **ids
        )

    @staticmethod
    def _reject(
        source: str, rejected: _Rejected, system_id: str | None, release_id: str | None
    ) -> IngestOutcome:
        log.warning(
            rejected.reason,
            reason=rejected.reason,
            source=source,
            system_id=system_id,
            release_id=release_id,
            detail=rejected.detail,
        )
        return IngestOutcome(
            source=source,
            status=IngestStatus.REJECTED,
            system_id=system_id,
            release_id=release_id,
            reason=rejected.reason,
            detail=rejected.detail,
        )
