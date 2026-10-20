"""Decision source registry.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Maps a decision mode to the sources that answer it.

    Three modes, because three situations are real: a team keeps decisions
    beside the code, a team keeps them in their own repository, or there are
    none to keep and the rules have to be reconstructed from configuration
    that is already enforced. The mode is chosen per run and recorded on the
    result, so a verdict can always be traced to the kind of evidence behind
    it.

    Combined is a superset rather than a fallback. Falling back from an empty
    mode to a fuller one would mean a run labelled as validated against
    written decisions had been validated against rules this component
    reconstructed itself, with nothing in the output saying so.

    Adding a source is one module and one line here, the same shape the style
    adapters use. There is deliberately no branch on the mode anywhere else.
"""

from ...ports import SourceArtifactReader
from .base import (
    DecisionSource,
    DecisionSourceError,
    SourceOutcome,
    SourceRequest,
)
from .config_scan import ConfigurationScan
from .external_adr import ExternalDecisionRecords
from .repo_adr import RepositoryDecisionRecords

MODES: dict[str, tuple[str, ...]] = {
    "repo_adr": ("repo_adr",),
    "external_adr": ("external_adr",),
    "combined": ("repo_adr", "external_adr", "config_scan"),
}
"""Which sources each mode reads, in the order their records are collected.

**`combined` reads all three**, which is what makes it the superset the
docstring above claims. It omitted `repo_adr` until 2026-10-20, and the defect
was invisible for as long as the only subject repository kept no decision
records: including or excluding a source that yields nothing changes nothing.
The first repository that keeps records beside its code showed it immediately -
forty-one documents that `combined` never opened, while the screen offered the
mode as "both, plus rules recovered from configuration".

Declared records come first so that, where a written decision and a
reconstructed rule speak about the same relationship, the written one is the
first the knowledge log holds for that key. Both declared sources therefore
precede the scan, and the in-repository one precedes the external one: a team
that keeps records in both places has the ones beside the code closer to it.
"""

DEFAULT_MODE = "combined"


def build_sources(reader: SourceArtifactReader) -> dict[str, DecisionSource]:
    """Every source, by name, reading through `reader`."""

    return {
        source.name: source
        for source in (
            RepositoryDecisionRecords(reader),
            ExternalDecisionRecords(reader),
            ConfigurationScan(reader),
        )
    }


def sources_for(mode: str, reader: SourceArtifactReader) -> tuple[DecisionSource, ...]:
    """The sources one mode reads, in collection order."""

    if mode not in MODES:
        raise ValueError(
            f"'{mode}' is not a decision mode; expected one of "
            f"{', '.join(sorted(MODES))}."
        )

    available = build_sources(reader)
    return tuple(available[name] for name in MODES[mode])


def registered_modes() -> tuple[str, ...]:
    """Every mode a run may be started in."""

    return tuple(sorted(MODES))


__all__ = [
    "DEFAULT_MODE",
    "MODES",
    "ConfigurationScan",
    "DecisionSource",
    "DecisionSourceError",
    "ExternalDecisionRecords",
    "RepositoryDecisionRecords",
    "SourceOutcome",
    "SourceRequest",
    "build_sources",
    "registered_modes",
    "sources_for",
]
