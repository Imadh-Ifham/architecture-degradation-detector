# Errors raised by the features subcomponent.


class HistoryError(Exception):
    # git history cannot answer what hotspot needs (missing tag, too few releases); run stops
    pass
