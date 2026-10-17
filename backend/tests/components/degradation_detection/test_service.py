import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import sys
from app.components.degradation_detection import DegradationDetectionService

outer = ("app.core", "app.infrastructure", "app.api", "fastapi", "sqlalchemy", "neo4j")
loaded = sorted(m for m in sys.modules if m.startswith(outer))
assert not loaded, loaded
"""


def test_component_imports_without_settings_or_databases(tmp_path: Path) -> None:
    """C3 must load with no .env and no containers, so its tests never hang on Docker.

    Runs in a fresh interpreter from an empty directory: other tests in this session import
    app.main, which would hide a leak through sys.modules.
    """
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("POSTGRES_", "NEO4J_"))}
    env["PYTHONPATH"] = str(BACKEND_ROOT)

    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
