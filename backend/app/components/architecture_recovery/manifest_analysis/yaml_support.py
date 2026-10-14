"""YAML loading with source positions.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Loads YAML through an explicitly safe loader and records the source line of
    every mapping and sequence, so extracted findings can cite where they came
    from.

    Positions are kept in a side table keyed by object identity rather than
    injected into the data, which keeps the parsed structure exactly what the
    manifest declared.
"""

from dataclasses import dataclass, field
from typing import Any

import yaml


class _PositionTrackingLoader(yaml.SafeLoader):
    """A safe loader that records the start line of every container node.

    The map and sequence constructors are overridden as well as
    `construct_mapping`, because PyYAML builds the container *after* calling
    `construct_mapping`: recording only there would attach positions to a
    throwaway object.

    A nested container is recorded against the line of the *key* that
    introduced it, so asking for a service's line returns the `web:` line rather
    than the line of the first entry beneath it.
    """

    def __init__(self, stream: Any) -> None:
        """Initialise the loader and the position table for this document."""

        super().__init__(stream)
        self.positions: dict[int, int] = {}

    def construct_yaml_map(self, node: Any):
        """Build a mapping, recording the line it starts on."""

        data: dict = {}
        # A parent mapping overwrites this with the introducing key's line.
        self.positions.setdefault(id(data), node.start_mark.line + 1)
        yield data
        data.update(self.construct_mapping(node))

    def construct_yaml_seq(self, node: Any):
        """Build a sequence, recording the line it starts on."""

        data: list = []
        self.positions.setdefault(id(data), node.start_mark.line + 1)
        yield data
        data.extend(self.construct_sequence(node))

    def construct_mapping(self, node: Any, deep: bool = False) -> dict:
        """Construct a mapping and record where each entry was declared."""

        mapping = super().construct_mapping(node, deep=deep)

        if isinstance(node, yaml.MappingNode):
            for key_node, _ in node.value:
                try:
                    key = self.construct_object(key_node, deep=True)
                except yaml.YAMLError:
                    # A malformed key is reported by the caller; it must not
                    # stop the surrounding mapping from being built.
                    continue

                if key in mapping:
                    self.positions[id(mapping[key])] = key_node.start_mark.line + 1

        return mapping


# Register on the subclass so the parent's constructors stay untouched.
_PositionTrackingLoader.add_constructor(
    "tag:yaml.org,2002:map", _PositionTrackingLoader.construct_yaml_map
)
_PositionTrackingLoader.add_constructor(
    "tag:yaml.org,2002:seq", _PositionTrackingLoader.construct_yaml_seq
)


@dataclass
class YamlDocument:
    """One parsed YAML document plus the line it starts on."""

    data: Any
    line: int | None = None


@dataclass
class YamlLoadResult:
    """The documents of a YAML stream, or the error that stopped parsing."""

    documents: list[YamlDocument] = field(default_factory=list)
    positions: dict[int, int] = field(default_factory=dict)
    error: str | None = None
    error_line: int | None = None


def load_yaml_documents(text: str) -> YamlLoadResult:
    """Parse every YAML document in `text` without ever raising.

    A malformed stream yields the documents that parsed before the failure,
    together with the error and the line it occurred on.
    """

    loader = _PositionTrackingLoader(text)
    result = YamlLoadResult(positions=loader.positions)

    try:
        while loader.check_node():
            node = loader.get_node()

            if node is None:
                # An empty document (for example a trailing `---`).
                continue

            data = loader.construct_document(node)
            result.documents.append(
                YamlDocument(data=data, line=node.start_mark.line + 1)
            )
    except yaml.YAMLError as error:
        result.error = _describe(error)
        result.error_line = _error_line(error)
    finally:
        loader.dispose()

    return result


def line_of(value: Any, positions: dict[int, int]) -> int | None:
    """Return the recorded source line for a parsed container, if known."""

    return positions.get(id(value))


def _describe(error: yaml.YAMLError) -> str:
    """Reduce a YAML error to a single readable line."""

    problem = getattr(error, "problem", None)

    if problem:
        return str(problem)

    # Multi-line messages (the error plus the offending excerpt) collapse to the
    # first line so a diagnostic stays a one-liner.
    return str(error).splitlines()[0]


def _error_line(error: yaml.YAMLError) -> int | None:
    """Extract the 1-based source line a YAML error occurred on."""

    mark = getattr(error, "problem_mark", None)

    return mark.line + 1 if mark is not None else None
