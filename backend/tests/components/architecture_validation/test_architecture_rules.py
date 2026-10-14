"""Structural rules for the architecture validation component.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Checks the architectural constraints this component is built on, by reading
    its own source. They are easy to break by accident - one convenient import
    during a late debugging session - and awkward to unwind once other code has
    been written on top.

    These tests never need maintenance as the component grows, which is the
    point: the rules keep holding without anyone remembering them.
"""

import ast
from pathlib import Path

import pytest

COMPONENT = Path(__file__).resolve().parents[3] / "app" / "components" / "architecture_validation"

SUBCOMPONENTS = (
    "observation_normalization",
    "intent_extraction",
    "decision_knowledge",
    "evidence_retrieval",
    "validation_reasoning",
    "independent_verification",
    "classification",
    "architect_review",
    "graph_publishing",
)

FORBIDDEN_IMPORTS = ("app.infrastructure", "sqlalchemy", "neo4j", "fastapi", "anthropic", "openai")

IMPLEMENTED = frozenset({"observation_normalization"})
"""Subcomponents whose service is written.

Kept here rather than inferred from the source, so adding one is a deliberate
edit that shows up in a diff. Both halves of the stub/implemented pair below
read from it.
"""


def modules() -> list[Path]:
    return sorted(COMPONENT.rglob("*.py"))


def imported_names(path: Path) -> set[str]:
    """Every module name this file imports, absolute form only.

    Relative imports are resolved to None by `ast` and are deliberately
    ignored: the rules here are about what the component reaches outside
    itself.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


class TestLayerBoundaries:
    """What this component may depend on."""

    @pytest.mark.parametrize("path", modules(), ids=lambda p: p.name)
    def test_no_module_imports_infrastructure_or_a_driver(self, path):
        """Dependencies on the outside world go through ports.py.

        Covers the AI SDKs too: the architecture document requires that no
        component depend on a specific provider or model, and an import is the
        most direct way to do so by accident.
        """

        for name in imported_names(path):
            for forbidden in FORBIDDEN_IMPORTS:
                assert not name.startswith(forbidden), (
                    f"{path.relative_to(COMPONENT)} imports {name}; "
                    "declare a Protocol in ports.py instead"
                )

    def test_no_subcomponent_names_a_model(self):
        """A subcomponent asks for a task, never for a model."""

        suspicious = ("gpt-", "llama-", "qwen", "claude-", "gemini", "mixtral")
        for path in modules():
            if path.parent.name not in SUBCOMPONENTS:
                continue
            source = path.read_text(encoding="utf-8").lower()
            for token in suspicious:
                assert token not in source, f"{path.name} names a model: {token}"


class TestSubcomponentPattern:
    """The shape the instructions mandate for every subcomponent."""

    @pytest.mark.parametrize("name", SUBCOMPONENTS)
    def test_every_subcomponent_has_the_three_mandatory_files(self, name):
        folder = COMPONENT / name
        for filename in ("__init__.py", "service.py", "models.py"):
            assert (folder / filename).exists(), f"{name}/{filename} is missing"

    @pytest.mark.parametrize("name", SUBCOMPONENTS)
    def test_no_subcomponent_imports_another_subcomponent(self, name):
        """If A needs B's output, the component passes it in.

        This is what lets a subcomponent be built and tested before the one
        feeding it exists, which the whole build order depends on.
        """

        others = set(SUBCOMPONENTS) - {name}
        for path in (COMPONENT / name).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                # A sibling import is `from ..<other> import X` - level 2 with
                # the sibling's name as the module.
                if node.level == 2 and node.module in others:
                    pytest.fail(f"{name} imports sibling {node.module}")

    @pytest.mark.parametrize("name", SUBCOMPONENTS)
    def test_no_subcomponent_contains_a_nested_subcomponent(self, name):
        """Maximum depth is component/subcomponent.

        Private module folders are allowed and are distinguished by having no
        service.py - a folder with one is a subcomponent, and a subcomponent
        inside a subcomponent is what the rule forbids.
        """

        for child in (COMPONENT / name).iterdir():
            if child.is_dir() and child.name != "__pycache__":
                assert not (child / "service.py").exists(), (
                    f"{name}/{child.name} has a service.py, making it a nested subcomponent"
                )

    @pytest.mark.parametrize("name", SUBCOMPONENTS)
    def test_the_subcomponent_init_only_re_exports(self, name):
        """__init__.py re-exports the public class and holds no logic."""

        tree = ast.parse((COMPONENT / name / "__init__.py").read_text(encoding="utf-8"))
        for node in tree.body:
            assert isinstance(node, (ast.Expr, ast.ImportFrom, ast.Import, ast.Assign)), (
                f"{name}/__init__.py contains logic: {type(node).__name__}"
            )


class TestOrchestration:
    """Only the component's service knows the order."""

    def test_the_component_service_is_the_only_module_importing_subcomponents(self):
        importers = []
        for path in modules():
            if path.parent != COMPONENT:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    if node.module in SUBCOMPONENTS:
                        importers.append(path.name)
                        break

        assert set(importers) == {"service.py"}, (
            f"subcomponents are imported by {sorted(set(importers))}; only service.py may"
        )

    def test_the_stage_order_matches_the_subcomponents_that_exist(self):
        from app.components.architecture_validation.service import STAGE_ORDER

        assert STAGE_ORDER == SUBCOMPONENTS

    @pytest.mark.parametrize("name", sorted(set(SUBCOMPONENTS) - IMPLEMENTED))
    def test_an_unimplemented_subcomponent_raises_rather_than_returning_nothing(self, name):
        """Asserted rather than assumed.

        A half-written subcomponent that silently returns None looks identical
        to one not yet started, and the difference matters while most of them
        are stubs.

        As each subcomponent is built, its name moves into IMPLEMENTED - so
        this test and the next one together record how far the component has
        got, and neither can be satisfied by accident.
        """

        service_class = _service_class(name)
        entry = _entry_method(service_class)
        with pytest.raises(NotImplementedError):
            getattr(service_class(), entry)(*[None] * _arity(service_class, entry))

    @pytest.mark.parametrize("name", sorted(IMPLEMENTED))
    def test_an_implemented_subcomponent_no_longer_raises(self, name):
        """The other half of the pair above.

        Without it, deleting a subcomponent's body would make the suite greener
        rather than redder.
        """

        service_class = _service_class(name)
        entry = _entry_method(service_class)
        source = (COMPONENT / name / "service.py").read_text(encoding="utf-8")

        assert "raise NotImplementedError" not in source
        assert callable(getattr(service_class, entry))


def _service_class(name: str):
    """The single *Service class a subcomponent's service module exposes."""

    import importlib

    module = importlib.import_module(f"app.components.architecture_validation.{name}.service")
    return next(
        getattr(module, attribute)
        for attribute in dir(module)
        if attribute.endswith("Service") and attribute != "SourceArtifactReader"
    )


def _entry_method(service_class) -> str:
    """The subcomponent's one public entry method."""

    return next(method for method in vars(service_class) if not method.startswith("_"))


def _arity(service_class, method_name: str) -> int:
    """Positional argument count for a bound method, excluding self."""

    import inspect

    signature = inspect.signature(getattr(service_class, method_name))
    return len(signature.parameters) - 1
