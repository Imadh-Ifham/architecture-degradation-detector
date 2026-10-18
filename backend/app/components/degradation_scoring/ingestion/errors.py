# Errors raised by the ingestion subcomponent.


class GraphLoadError(ValueError):
    # The graph document cannot be turned into a graph; the run must stop
    pass
