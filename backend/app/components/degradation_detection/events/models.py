"""M6 models used only inside events."""

from app.components.degradation_detection.models import InternalModel
from app.domain.degradation_event import DegradationEventV2


class EventExport(InternalModel):
    """The events of one run, and the ``events.json`` text to write for C4."""

    events: tuple[DegradationEventV2, ...]
    text: str  # events.json: a JSON array of the events, schema-checked, keys sorted
