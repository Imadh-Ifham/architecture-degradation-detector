"""Microservices tier: detectors that only make sense for ``architecture_style = microservices``.

A private package of the ``detection`` subcomponent, not a subcomponent of its own.
``CyclicServiceDependency`` is the universal ``CyclicDependency`` at service granularity, so it
has no detector of its own here.
"""

from app.components.degradation_detection.detection.microservices.shared_persistence import (
    SharedPersistence,
)
from app.components.degradation_detection.detection.models import AntiPatternDetector

# In output order.
MICROSERVICES_DETECTORS: tuple[AntiPatternDetector, ...] = (SharedPersistence(),)

__all__ = ["MICROSERVICES_DETECTORS"]
