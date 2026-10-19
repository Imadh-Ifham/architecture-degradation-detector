# Errors raised by the reporting subcomponent.


class ReportSchemaError(ValueError):
    # the report written does not read back as SeverityReportV1 of the current schema version
    pass


class OutputExistsError(FileExistsError):
    # the run's output folder already holds files; a run never overwrites another
    pass
