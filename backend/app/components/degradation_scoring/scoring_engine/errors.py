# Errors raised by the scoring_engine subcomponent.


class CalibrationError(Exception):
    # saved bounds cannot be used: unreadable, another system, or a feature without bounds
    pass


class InvalidJudgementsError(Exception):
    # the AHP weights file cannot be used: unreadable, not reciprocal, off the Saaty scale
    pass


class InconsistentJudgementsError(Exception):
    # the AHP judgements contradict each other too much: CR above the configured maximum
    pass
