# Errors the C4 read-side query methods raise (DegradationScoringService.runs / report).


class SavedReportError(Exception):
    # saved reports cannot be read: no source configured, or a report breaks the contract
    pass


class AmbiguousRunError(SavedReportError):
    # two systems hold a run with the same id
    pass


class HandoverNotFoundError(Exception):
    # degradation detection left no events.json + release package for that run
    pass
