"""Static-threshold baseline (plan T-13): what a fixed-threshold tool would flag.

It is the comparison for the core research claim, not part of the detection: C3 decides
degradation by a trend, never by a fixed threshold [locked decision 2]. The baseline reads the
same M2 observations C3 tests for trends, so the two differ only in the decision rule.
Evaluation (T-14) counts the flags C3 avoids on the stub's flat elements (S3, S6).
"""

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.models import ReleaseDetection
from app.domain.analysis_run import StaticFlag


class StaticBaselineService:
    def __init__(self, cfg: C3Config) -> None:
        self._rules = {rule.metric: rule.above for rule in cfg.baseline.static.rules}

    def flag(self, detection: ReleaseDetection) -> tuple[StaticFlag, ...]:
        """Every element metric of one release above its rule's threshold, sorted by element
        then metric. A null value is never above anything."""
        flags = [
            StaticFlag(
                release_id=detection.release_id,
                element_id=obs.element_id,
                metric=obs.metric,
                value=obs.value,
                threshold=self._rules[obs.metric],
            )
            for obs in detection.observations
            if obs.element_id is not None
            and obs.metric in self._rules
            and obs.value is not None
            and obs.value > self._rules[obs.metric]
        ]
        return tuple(sorted(flags, key=lambda f: (f.element_id, f.metric)))
