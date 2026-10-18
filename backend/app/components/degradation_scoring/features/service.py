# Features: computes the severity criteria of each resolved event.
# Blast radius (T11), hotspot (T13) and persistence (T15); ADR weight joins in T16.

from collections.abc import Sequence
from pathlib import Path

import networkx as nx

from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.features.blast_radius import CentralityCache, blast_radius
from app.components.degradation_scoring.features.history import FileFilter, MemoryMiningCache
from app.components.degradation_scoring.features.hotspot import compute_hotspots
from app.components.degradation_scoring.features.models import (
    EventFeatures,
    FeatureSet,
    HotspotContext,
)
from app.components.degradation_scoring.features.persistence import persistence
from app.components.degradation_scoring.models import ResolvedEvent
from app.components.degradation_scoring.ports import CommitHistorySource, MiningCache


class FeatureExtractionService:
    # Turns resolved events plus their release graph (and optionally the repository's git
    # history) into raw features, in input order.

    def __init__(
        self,
        config: C4Config,
        history_source: CommitHistorySource | None = None,
        mining_cache: MiningCache | None = None,
    ) -> None:
        self._config = config
        self._history = history_source
        self._cache: MiningCache = mining_cache or MemoryMiningCache()
        self._filter = FileFilter.from_settings(
            config.history_include_globs, config.history_exclude_globs
        )
        self._centralities = CentralityCache(
            alpha=config.pagerank_alpha,
            exact_max_nodes=config.betweenness_exact_max_nodes,
            sample_k=config.betweenness_sample_k,
            seed=config.seed,
        )

    def extract(
        self,
        events: Sequence[ResolvedEvent],
        graph: "nx.DiGraph[str]",
        repo_path: Path | None = None,
    ) -> FeatureSet:
        # one call = one (system, release) and the graph of that release; without repo_path
        # the hotspot criterion is inactive
        if not events:
            return FeatureSet(events=[], hotspot=self._inactive("no_events"))
        keys = {(item.event.system_id, item.event.window.end_release) for item in events}
        if len(keys) > 1:
            raise ValueError(f"events span several (system, release) pairs: {sorted(keys)}")
        centralities = self._centralities.get(keys.pop(), graph)
        hotspots, context = compute_hotspots(
            events,
            graph,
            source=self._history,
            cache=self._cache,
            repo_path=repo_path,
            file_filter=self._filter,
            releases_per_half_life=self._config.hotspot_half_life_releases,
            cochange_threshold=self._config.cochange_threshold,
            max_files_per_commit=self._config.max_files_per_commit,
        )
        return FeatureSet(
            events=[
                EventFeatures(
                    event_id=item.event.event_id,
                    blast_radius=blast_radius(graph, item.nodes, centralities),
                    persistence=persistence(item.event),
                    hotspot=hotspots.get(item.event.event_id),
                )
                for item in events
            ],
            hotspot=context,
        )

    def _inactive(self, reason: str) -> HotspotContext:
        return HotspotContext(
            active=False,
            inactive_reason=reason,
            cochange_threshold=self._config.cochange_threshold,
            max_files_per_commit=self._config.max_files_per_commit,
        )
