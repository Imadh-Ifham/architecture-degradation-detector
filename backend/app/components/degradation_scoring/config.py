"""Degradation scoring configuration.

Author: Dahami
Date: 2026-10-14
Description:
    Typed, read-only view of the `scoring_*` settings in app/core/config.py,
    without the prefix (`settings.scoring_explain_top_n` -> `config.explain_top_n`).
    Values come from the field defaults, then the [scoring] section of
    backend/config.ini, then the environment. This class has no defaults of its
    own and rejects unknown fields, so it cannot drift from Settings silently.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.core.config import Settings

SETTINGS_PREFIX = "scoring_"


class C4Config(BaseModel):
    """C4 thresholds and switches for one run (CLAUDE.md §4-§5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outputs_root: Path
    seed: int
    rank_only_confirmed: bool
    graph_reverse_edges: bool
    resolution_prefix_confidence: float
    br_weight_fan_in_ratio: float
    br_weight_pagerank: float
    br_weight_betweenness: float
    br_weight_depth: float
    pagerank_alpha: float
    betweenness_exact_max_nodes: int
    betweenness_sample_k: int
    hotspot_half_life_releases: float
    cochange_threshold: int
    max_files_per_commit: int
    eh_weight_churn_decayed: float
    eh_weight_authors: float
    eh_weight_coupling: float
    eh_weight_bugfix_ratio: float
    history_include_globs: str
    history_exclude_globs: str
    ps_weight_consecutive_releases: float
    ps_weight_growth_slope: float
    adr_semantic_fallback_enabled: bool
    adr_semantic_similarity_threshold: float
    winsor_lower_percentile: float
    winsor_upper_percentile: float
    small_n_threshold: int
    ahp_max_consistency_ratio: float
    weights_version: str
    method: Literal["topsis", "lambdamart"]
    topsis_mode: Literal["fixed_reference", "classic"]
    explain_top_n: int
    retriever_top_k: int
    explanation_max_words: int
    llm_temperature: float
    nli_entailment_threshold: float
    nli_contradiction_threshold: float
    ground_truth_horizon_releases: int
    ground_truth_min_ops: int
    bootstrap_resamples: int
    bootstrap_confidence: float
    random_baseline_permutations: int

    @classmethod
    def from_settings(cls, settings: "Settings") -> "C4Config":
        """Build the view from every `scoring_*` field of the app settings."""

        values = settings.model_dump()
        return cls(
            **{
                name.removeprefix(SETTINGS_PREFIX): value
                for name, value in values.items()
                if name.startswith(SETTINGS_PREFIX)
            }
        )
