"""Report models: the files one stored run renders to, by path under ``out/<run_id>/``."""

REPORT_FILE = "report.md"
PLOT_DIR = "plots"

# Path -> bytes. The caller writes them; rendering does no I/O.
ReportFiles = dict[str, bytes]


def plot_path(event_id: str) -> str:
    """Where the plot of one event's series goes, relative to the report."""
    return f"{PLOT_DIR}/{event_id}.png"
