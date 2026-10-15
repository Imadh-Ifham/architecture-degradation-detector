"""M1 models: what goes into ingestion and the report that comes out.

The release itself (``CanonicalRelease``) is in ``app/domain/`` because it crosses the
repository port; the timeline is in the component ``models.py`` because later subcomponents
read it.
"""

from enum import StrEnum

from app.components.degradation_detection.models import InternalModel
from app.domain.canonical_release import GateStatus

# Reason codes M1 rejects a package with. DUPLICATE_ELEMENT_ID and DANGLING_DEPENDENCY come from
# the contract (app/domain/release_package.py).
PACKAGE_TOO_LARGE = "PACKAGE_TOO_LARGE"
INPUT_NOT_JSON = "INPUT_NOT_JSON"
INPUT_SCHEMA_INVALID = "INPUT_SCHEMA_INVALID"
RELEASE_CONFLICT = "RELEASE_CONFLICT"

# Reason codes M1 logs without rejecting anything.
RELEASE_STORED = "RELEASE_STORED"
RELEASE_UNCHANGED = "RELEASE_UNCHANGED"
SELF_LOOP_DROPPED = "SELF_LOOP_DROPPED"
RELEASE_OFF_MAIN_LINE = "RELEASE_OFF_MAIN_LINE"
RELEASE_EXCLUDED = "RELEASE_EXCLUDED"
ARCHITECTURE_STYLE_CHANGED = "ARCHITECTURE_STYLE_CHANGED"
GRANULARITY_CHANGED = "GRANULARITY_CHANGED"


class RawPackage(InternalModel):
    """One package as received: where it came from and its bytes, not yet parsed."""

    source: str  # file name, for the report
    data: bytes


class IngestStatus(StrEnum):
    STORED = "STORED"
    UNCHANGED = "UNCHANGED"  # same release, same content: idempotent no-op
    REJECTED = "REJECTED"  # never touched the store


class IngestOutcome(InternalModel):
    source: str
    status: IngestStatus
    system_id: str | None = None  # None when the package could not be read
    release_id: str | None = None
    gate_status: GateStatus | None = None
    reason: str | None = None  # set when REJECTED
    detail: str | None = None


class IngestReport(InternalModel):
    outcomes: tuple[IngestOutcome, ...]

    def count(self, status: IngestStatus) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is status)
