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
import inspect
from pathlib import Path

import pytest

from app.components.architecture_validation.pipeline import (
    IMPLEMENTED_STAGES,
    PIPELINE,
)

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

IMPLEMENTED = IMPLEMENTED_STAGES
"""Subcomponents whose service is written.

Read from the component's own pipeline description rather than restated here,
so the status the API publishes is the status these tests enforce. It is still
written by hand there, which is the point: promoting a subcomponent stays a
deliberate edit that shows up in a diff.
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


class TestObservationNormalizationHasNoIO:
    """M1's one port, asserted structurally rather than hoped for.

    The architecture document gives recovery the job of supplying the elements,
    their dependencies and the detected style, and it says that validation does
    not read source code. A manifest reader inside this component contradicts
    both - so the rule worth enforcing is not "do not read manifests" but the
    stronger one below: M1 cannot name a reader, so it cannot read anything.
    """

    M1 = "observation_normalization"

    def m1_modules(self) -> list[Path]:
        return sorted((COMPONENT / self.M1).rglob("*.py"))

    @pytest.mark.parametrize(
        "path", sorted((COMPONENT / "observation_normalization").rglob("*.py")),
        ids=lambda p: p.name,
    )
    def test_no_module_names_a_file_reader_or_a_filesystem_call(self, path):
        source = path.read_text(encoding="utf-8")
        body = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )

        for forbidden in ("SourceArtifactReader", "open(", "Path(", "yaml."):
            assert forbidden not in body, (
                f"{path.name} names '{forbidden}'; M1 has one port and no I/O"
            )

    def test_the_subcomponent_has_no_derivation_module_left(self):
        """The derivation moved to infrastructure as a named stand-in for
        recovery. A file reappearing here is the regression to catch."""

        names = {path.name for path in self.m1_modules()}

        assert "_derivation.py" not in names

    def test_the_service_takes_no_dependency_at_all(self):
        from app.components.architecture_validation.observation_normalization import (
            ObservationNormalizationService,
        )

        # Constructible with nothing: that is what "no I/O" means in practice.
        assert ObservationNormalizationService().normalise

    def test_the_stand_in_lives_outside_the_component_and_states_its_expiry(self):
        """A thing that has to disappear should be named and dated so that it
        cannot be forgotten."""

        stand_in = (
            COMPONENT.parents[1]
            / "infrastructure"
            / "recovery_gateway"
            / "c1_dependency_stand_in.py"
        )

        assert stand_in.is_file()
        docstring = ast.get_docstring(ast.parse(stand_in.read_text(encoding="utf-8"))) or ""
        assert "deleted when recovery ships" in docstring


class TestTheStyleIsInferredInExactlyOnePlace:
    """One inference, three readers.

    The architectural style decides which adapter runs, and the adapter
    decides what every fact in a run looks like. There are three readers
    behind M1's one port - a recorded snapshot, recovery's inventory, and
    eventually recovery's graph - and an inference in that layer would be
    written once per reader or imported across them, which is three chances
    for two releases to be classified by different rules.
    """

    GATEWAY = Path(__file__).resolve().parents[3] / "app" / "infrastructure" / "recovery_gateway"

    def test_only_the_normaliser_defines_the_inference(self):
        defining = []
        for path in (COMPONENT.parents[1]).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.FunctionDef) and node.name == "infer_style":
                    defining.append(path)

        assert [path.name for path in defining] == ["_style.py"], (
            f"infer_style is defined in {[p.name for p in defining]}; "
            "M1 is the one place that decides a style nobody supplied"
        )

    def test_the_gateway_reports_the_absence_rather_than_filling_it(self):
        """The reader's job is to say whether recovery answered, not to answer
        for it. A gateway that imports the inference has taken on the decision
        the normaliser owns."""

        for path in self.GATEWAY.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            assert "infer_style" not in path.read_text(encoding="utf-8"), (
                f"{path.name} names infer_style; the gateway reports the style's "
                "absence and the normaliser decides what to do about it"
            )


class TestPipelineDescription:
    """What the component publishes about itself has to be true."""

    def test_the_description_lists_every_stage_in_run_order(self):
        from app.components.architecture_validation.service import STAGE_ORDER

        assert tuple(stage.name for stage in PIPELINE) == STAGE_ORDER
        assert [stage.order for stage in PIPELINE] == list(range(1, len(STAGE_ORDER) + 1))

    @pytest.mark.parametrize("stage", PIPELINE, ids=lambda s: s.name)
    def test_every_described_role_is_the_subcomponent_own_summary(self, stage):
        """The description is published; the docstring is read in the code.

        Two wordings of the same sentence drift apart, and the published one
        drifts silently. So the description quotes the subcomponent rather than
        paraphrasing it, and this test is what keeps that true.
        """

        summary = inspect.getdoc(_service_class(stage.name)).splitlines()[0]

        assert stage.role == summary

    def test_the_implemented_set_is_derived_from_the_description(self):
        assert IMPLEMENTED_STAGES == frozenset(
            stage.name for stage in PIPELINE if stage.implemented
        )

    @pytest.mark.parametrize("stage", PIPELINE, ids=lambda s: s.name)
    def test_a_described_stage_serialises_every_field_the_api_publishes(self, stage):
        assert set(stage.to_dict()) == {
            "name",
            "order",
            "role",
            "research_module",
            "uses_model",
            "implemented",
        }


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
