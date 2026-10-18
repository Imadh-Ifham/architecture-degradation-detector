# Errors raised by the ingestion subcomponent.


class GraphLoadError(ValueError):
    # The graph document cannot be turned into a graph; the run must stop
    pass


class AdrIndexError(ValueError):
    # The ADR index document is unusable (wrong shape, duplicate ids); the run must stop
    pass
