"""Architecture-agnostic guard (plan Section 1.1 #5, Section 4 M2 step 4).

C3 has one generic core; style-specific knowledge lives only in the detector catalog, and the
detector registry is the only module that acts on ``architecture_style``. The guard bans
*reading* the style anywhere else, not only ``if`` statements: a lookup such as
``STRATEGY[release.architecture_style]`` branches on style without any ``if``.

Two kinds of read are flagged: the attribute ``.architecture_style`` and a member of the
``ArchitectureStyle`` enum (``ArchitectureStyle.LAYERED``). Declaring which styles a detector
applies to (``styles = frozenset({"microservices"})``) is data, not a branch, and stays allowed.
"""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
COMPONENT_ROOT = BACKEND_ROOT / "app" / "components" / "degradation_detection"

ALLOWED = {
    # The one place that chooses detectors by style.
    "detection/registry.py",
    # Ingestion pass-through: copies the style into the canonical release...
    "ingestion/normalise.py",
    # ...and warns when it changes between releases, without acting on its value.
    "ingestion/ordering.py",
    # Event export pass-through: copies the style into DegradationEventV2 for C4.
    "events/emitter.py",
}


def style_reads(source: str) -> list[int]:
    """Line numbers where a module reads the architecture style."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load):
            continue
        reads_field = node.attr == "architecture_style"
        reads_member = isinstance(node.value, ast.Name) and node.value.id == "ArchitectureStyle"
        if reads_field or reads_member:
            lines.append(node.lineno)
    return lines


def test_only_the_registry_reads_the_architecture_style() -> None:
    found = []
    for path in sorted(COMPONENT_ROOT.rglob("*.py")):
        relative = path.relative_to(COMPONENT_ROOT).as_posix()
        if relative in ALLOWED:
            continue
        found += [f"{relative}:{n}" for n in style_reads(path.read_text(encoding="utf-8"))]

    assert found == []


def test_allowed_modules_exist() -> None:
    """A stale entry would quietly exempt whatever file later takes that name."""
    for relative in ALLOWED:
        assert (COMPONENT_ROOT / relative).is_file(), relative


def test_registry_does_read_the_style() -> None:
    """Otherwise the guard would pass because nobody chooses by style at all."""
    source = (COMPONENT_ROOT / "detection" / "registry.py").read_text(encoding="utf-8")

    assert style_reads(source)


def test_guard_catches_planted_branches() -> None:
    source = (
        "if release.architecture_style == 'layered':\n"  # 1: if on the field
        "    pass\n"
        "run = STRATEGY[r.architecture_style]\n"  # 3: lookup, no if
        "match style:\n"
        "    case ArchitectureStyle.LAYERED:\n"  # 5: enum member
        "        pass\n"
        "x = getattr(r, 'granularity')\n"
    )

    assert style_reads(source) == [1, 3, 5]


def test_guard_allows_declarations() -> None:
    source = (
        "class D:\n"
        "    styles: frozenset[str] = frozenset({'microservices'})\n"
        "    architecture_style: str\n"
        "def f(architecture_style: ArchitectureStyle) -> None:\n"
        "    make(architecture_style=architecture_style)\n"
        "payload = {'architecture_style': 'microservices'}\n"
        "names = {s.value for s in ArchitectureStyle}\n"
    )

    assert style_reads(source) == []
