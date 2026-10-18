"""Tests for the degradation scoring layer boundaries.

Author: Dahami
Date: 2026-10-14
Description:
    Enforces INSTRUCTIONS §7.1 and §7.3 on every module of the component by
    parsing its imports: no framework, database, LLM/model SDK, api or
    infrastructure imports, and no subcomponent importing another one.
"""

import ast
from pathlib import Path

import pytest

import app.components.degradation_scoring as component

COMPONENT_ROOT = Path(component.__file__).parent
COMPONENT_PACKAGE = "app.components.degradation_scoring"
SUBCOMPONENTS = (
    "ingestion",
    "features",
    "scoring_engine",
    "explanation",
    "evaluation",
    "reporting",
)
FORBIDDEN_ROOTS = (
    "fastapi",
    "sqlalchemy",
    "neo4j",
    "anthropic",
    "openai",
    "sentence_transformers",
    "transformers",
    "torch",
    "app.api",
    "app.infrastructure",
)

MODULES = sorted(COMPONENT_ROOT.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
    return imported


def _is_within(module: str, root: str) -> bool:
    return module == root or module.startswith(f"{root}.")


def _module_id(path: Path) -> str:
    return path.relative_to(COMPONENT_ROOT).as_posix()


def test_component_modules_are_found() -> None:
    assert {path.parent.name for path in MODULES} >= set(SUBCOMPONENTS)


@pytest.mark.parametrize("path", MODULES, ids=_module_id)
def test_no_forbidden_imports(path: Path) -> None:
    offending = {
        module
        for module in _imported_modules(path)
        for root in FORBIDDEN_ROOTS
        if _is_within(module, root)
    }

    assert not offending, f"{_module_id(path)} imports {sorted(offending)}"


@pytest.mark.parametrize(
    "path",
    [path for path in MODULES if path.parent.name in SUBCOMPONENTS],
    ids=_module_id,
)
def test_subcomponents_do_not_import_each_other(path: Path) -> None:
    own = path.parent.name
    others = [f"{COMPONENT_PACKAGE}.{name}" for name in SUBCOMPONENTS if name != own]

    offending = {
        module
        for module in _imported_modules(path)
        for other in others
        if _is_within(module, other)
    }

    assert not offending, f"{_module_id(path)} imports {sorted(offending)}"
