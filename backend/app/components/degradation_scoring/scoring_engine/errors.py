# Errors raised by the scoring_engine subcomponent.


class CalibrationError(Exception):
    # saved bounds cannot be used: unreadable, another system, or a feature without bounds
    pass
