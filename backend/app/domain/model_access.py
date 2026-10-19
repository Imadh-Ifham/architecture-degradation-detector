"""What can go wrong when something asks a model.

Author: Aman Mohamed M.A
Date: 2026-10-16
Description:
    Two errors, and they are here rather than beside the provider because both
    sides of the port need them: the adapter raises them and the component
    catches them. A component may not import an adapter's exception type, and
    an adapter may not import a component - so the shared vocabulary lives in
    the domain, next to the other shapes that cross a boundary.

    They are two rather than one because the thing above them does different
    work for each. A model that could not be reached is a reason to try a
    different model. A model that answered with something unreadable is not -
    the next model would be answering a question the first one already
    botched, and no comparison between the two would mean anything. So one
    moves down the ladder and the other retries identically and then gives up.

    Neither is raised for a misconfiguration. A model that cannot do strict
    schema, or one the registry does not know, raises from the interface and
    fails the run - because a configuration error that degraded quietly into a
    no-model result would look exactly like a free tier having a bad day.
"""


class ModelAccessError(RuntimeError):
    """A model could not answer. Shared root so a caller may catch either."""


class ModelUnavailable(ModelAccessError):
    """Nothing answered: a transport failure, a timeout or a rate limit.

    A rate limit is grouped with the transport failures on purpose. On a free
    tier the limit is tokens per minute, so the useful response is to try the
    other model rather than to retry the same one immediately.
    """


class ModelResponseUnusable(ModelAccessError):
    """Something answered, and what came back could not be read as the answer.

    In strict mode this means the provider ignored the constraint it was
    given, which is worth knowing as itself rather than as a transport
    failure: the network was fine and the model was reached.
    """


__all__ = ["ModelAccessError", "ModelResponseUnusable", "ModelUnavailable"]
