"""Universal tier: detectors that apply to every architecture style (``styles = {"*"}``).

A private package of the ``detection`` subcomponent, not a subcomponent of its own.
"""

from app.components.degradation_detection.detection.models import AntiPatternDetector
from app.components.degradation_detection.detection.universal.big_ball_of_mud import BigBallOfMud
from app.components.degradation_detection.detection.universal.cyclic_dependency import (
    CyclicDependency,
)
from app.components.degradation_detection.detection.universal.hub_like_element import (
    HubLikeElement,
)
from app.components.degradation_detection.detection.universal.oversized_element import (
    OversizedElement,
)
from app.components.degradation_detection.detection.universal.unstable_dependency import (
    UnstableDependency,
)

# In output order.
UNIVERSAL_DETECTORS: tuple[AntiPatternDetector, ...] = (
    CyclicDependency(),
    HubLikeElement(),
    UnstableDependency(),
    OversizedElement(),
    BigBallOfMud(),
)

__all__ = ["UNIVERSAL_DETECTORS"]
