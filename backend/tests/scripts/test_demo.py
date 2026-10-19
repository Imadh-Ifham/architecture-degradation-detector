"""`scripts/demo.ps1` and the C3 README name real commands and run on a fresh clone (plan T-15).

The demo itself needs Docker, so it is not run here. These checks catch the ways it rots
without Docker: a renamed command or option, a new required setting, or a demo that would
point at the development database.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import typer
import yaml

from app.core.config import Settings
from scripts import c3, mvp_eval

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEMO = BACKEND_ROOT / "scripts" / "demo.ps1"
README = BACKEND_ROOT / "app" / "components" / "degradation_detection" / "README.md"
COMPOSE = BACKEND_ROOT / "docker-compose.yml"

# Typer bundles its own click, so commands are recognised by shape, not by click's classes.
CLIS: dict[str, Any] = {
    "scripts.c3": typer.main.get_command(c3.app),
    "scripts.mvp_eval": typer.main.get_command(mvp_eval.app),
}
INVOCATION = re.compile(r"-m (scripts\.(?:c3|mvp_eval))\b([^\n`|]*)")


def invocations(text: str) -> list[tuple[str, list[str]]]:
    """Every ``python -m scripts.<cli> ...`` in the text, as (module, words)."""
    return [(m[1], m[2].split()) for m in INVOCATION.finditer(text)]


def resolve(module: str, words: list[str]) -> tuple[list[str], Any, list[str]]:
    """The command path the words name (group options and subcommands followed), the command,
    and every option given along the way."""
    command = CLIS[module]
    path: list[str] = []
    options: list[str] = []
    rest = list(words)
    while rest:
        word = rest.pop(0)
        if word.startswith("--"):
            options.append(word.split("=")[0])
            param = next((p for p in command.params if word.split("=")[0] in p.opts), None)
            if param is not None and not getattr(param, "is_flag", True) and "=" not in word:
                rest = rest[1:]  # the option's value
        elif word in getattr(command, "commands", {}):
            command = command.commands[word]
            path.append(word)
    return path, command, options


def known_options(command: Any, module: str) -> set[str]:
    group = CLIS[module]
    params = [*command.params, *(group.params if group is not command else [])]
    return {opt for p in params for opt in (*p.opts, *p.secondary_opts)}


@pytest.mark.parametrize("path", [DEMO, README], ids=["demo.ps1", "README.md"])
def test_every_command_and_option_named_exists(path: Path) -> None:
    calls = invocations(path.read_text(encoding="utf-8"))

    assert calls, f"{path.name} names no command"
    for module, words in calls:
        _, command, options = resolve(module, words)
        if module == "scripts.c3":
            assert not hasattr(command, "commands"), f"{path.name}: no command in {words}"
        unknown = set(options) - known_options(command, module)
        assert not unknown, f"{path.name}: {module} {' '.join(words)}: unknown {unknown}"


def test_demo_runs_every_step_of_the_plan() -> None:
    """Plan T-15: clean DB -> stub -> ingest -> run -> report -> eval."""
    text = DEMO.read_text(encoding="utf-8")
    steps = [resolve(m, w)[0][0] if m == "scripts.c3" else "eval" for m, w in invocations(text)]

    assert steps == ["stub", "ingest", "run", "report", "eval"]
    assert "alembic upgrade head" in DEMO.read_text(encoding="utf-8")


def test_demo_sets_every_required_setting() -> None:
    """A fresh clone has no .env; the demo supplies whatever Settings cannot default."""
    required = {name.upper() for name, f in Settings.model_fields.items() if f.is_required()}
    assigned = set(re.findall(r"^\s*([A-Z0-9_]+)\s*=", DEMO.read_text(encoding="utf-8"), re.M))

    assert required <= assigned, required - assigned


def test_demo_never_uses_the_development_database() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    dev_db = compose["services"]["postgres"]["environment"]["POSTGRES_DB"]
    [demo_db] = re.findall(r'^\s*POSTGRES_DB\s*=\s*"([^"]+)"', DEMO.read_text("utf-8"), re.M)

    assert demo_db != dev_db
    assert f"DROP DATABASE IF EXISTS {demo_db}" in DEMO.read_text(encoding="utf-8")


def test_demo_restores_the_callers_environment() -> None:
    """The demo database must not leak into the next `c3` command typed in the same shell."""
    text = DEMO.read_text(encoding="utf-8")

    assert "finally" in text
    assert re.search(r"Restore|restore", text)


def test_backend_readme_points_to_the_c3_readme() -> None:
    text = (BACKEND_ROOT / "README.md").read_text(encoding="utf-8")

    assert "app/components/degradation_detection/README.md" in text
