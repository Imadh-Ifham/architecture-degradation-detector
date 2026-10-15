"""Architecture guards for C3 (INSTRUCTIONS §7.1, plan Section 1.1 and R3).

The source is scanned with ``ast`` instead of being imported, so the guards hold for every
module added by later tasks without listing them here.
"""

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
COMPONENT_ROOT = BACKEND_ROOT / "app" / "components" / "degradation_detection"

# Runtime code C3 owns or writes into: the component, plus the shared layers it adds files to.
RUNTIME_ROOTS = (
    COMPONENT_ROOT,
    BACKEND_ROOT / "app" / "domain",
    BACKEND_ROOT / "app" / "shared",
)

# Components reach the outside world only through ports.py Protocols.
FORBIDDEN_IN_COMPONENT = (
    "fastapi",
    "sqlalchemy",
    "neo4j",
    "anthropic",
    "openai",
    "app.infrastructure",
    "app.api",
)

# Mann-Kendall, Sen's slope and Benjamini-Hochberg are self-implemented; these are test oracles.
ORACLE_ONLY = ("pymannkendall", "statsmodels", "scipy.stats")


def imported_names(source: str) -> Iterator[str]:
    """Yield every absolute dotted name a module imports.

    ``from scipy import stats`` yields both ``scipy`` and ``scipy.stats`` so a banned submodule
    cannot be reached through the ``from`` form.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module
            for alias in node.names:
                yield f"{node.module}.{alias.name}"


def violations(root: Path, banned: tuple[str, ...]) -> list[str]:
    found = []
    for path in sorted(root.rglob("*.py")):
        for name in imported_names(path.read_text(encoding="utf-8")):
            if any(name == b or name.startswith(f"{b}.") for b in banned):
                found.append(f"{path.relative_to(BACKEND_ROOT).as_posix()} imports {name}")
    return found


def test_component_has_source_to_guard() -> None:
    assert list(COMPONENT_ROOT.rglob("*.py")), "guards below would pass on an empty tree"


def test_component_does_not_import_frameworks_or_outer_layers() -> None:
    assert violations(COMPONENT_ROOT, FORBIDDEN_IN_COMPONENT) == []


def test_domain_imports_no_other_app_layer_except_shared() -> None:
    outer = ("app.api", "app.components", "app.core", "app.infrastructure")

    assert violations(BACKEND_ROOT / "app" / "domain", outer) == []


def test_shared_imports_only_the_standard_library() -> None:
    shared = BACKEND_ROOT / "app" / "shared"
    modules = sorted(shared.rglob("*.py"))
    assert modules, "guard below would pass on an empty tree"

    for path in modules:
        for name in imported_names(path.read_text(encoding="utf-8")):
            assert name.split(".")[0] in sys.stdlib_module_names, f"{path.name} imports {name}"


def test_runtime_code_does_not_import_statistical_oracles() -> None:
    for root in RUNTIME_ROOTS:
        assert violations(root, ORACLE_ONLY) == []


def test_guard_catches_planted_violations(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "import sqlalchemy.orm\n"
        "from scipy import stats\n"
        "from app.infrastructure.postgres import database\n"
        "from scipy.optimize import linear_sum_assignment\n"
        "from . import fastapi\n",
        encoding="utf-8",
    )

    names = set(imported_names((tmp_path / "bad.py").read_text(encoding="utf-8")))

    assert "sqlalchemy.orm" in names
    assert "scipy.stats" in names
    assert "app.infrastructure.postgres" in names
    assert "fastapi" not in names  # relative import: a local module, not the framework
    banned = FORBIDDEN_IN_COMPONENT + ORACLE_ONLY
    flagged = {n for n in names if any(n == b or n.startswith(f"{b}.") for b in banned)}
    assert "scipy.optimize.linear_sum_assignment" not in flagged
    assert {"sqlalchemy.orm", "scipy.stats", "app.infrastructure.postgres"} <= flagged
