# Degradation scoring service: the only way into C4; orchestrates the subcomponents in order
# (ingestion -> features -> scoring -> explanation -> reporting). Layers 1-2 so far (T16b);
# T20 extends the same class with scoring, explanation and the report.

import datetime as dt
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.features import FeatureExtractionService
from app.components.degradation_scoring.features.models import EventFeatures, FeatureSet
from app.components.degradation_scoring.ingestion import IngestionService
from app.components.degradation_scoring.ingestion.graph import build_graph
from app.components.degradation_scoring.ingestion.models import IngestionResult
from app.components.degradation_scoring.ports import (
    CommitHistorySource,
    MiningCache,
    ScoringRunRepository,
)
from app.components.degradation_scoring.scoring_engine.models import RawEvent
from app.domain.severity_report import Dimension


class FeaturesRun(BaseModel):
    # the result of layers 1-2 for one (system, release)

    model_config = ConfigDict(frozen=True)

    run_id: str
    system_id: str
    release_id: str
    ingestion: IngestionResult
    features: FeatureSet


class DegradationScoringService:
    # Runs the C4 pipeline for one (system, release); saves each run when given a repository.

    def __init__(
        self,
        config: C4Config,
        *,
        history_source: CommitHistorySource | None = None,
        mining_cache: MiningCache | None = None,
        run_repository: ScoringRunRepository | None = None,
    ) -> None:
        self._config = config
        self._ingestion = IngestionService(config)
        self._features = FeatureExtractionService(config, history_source, mining_cache)
        self._runs = run_repository

    def run_features(
        self,
        payloads: Iterable[object],
        graph_document: object,
        *,
        run_id: str,
        data_provenance: str,
        adr_document: object | None = None,
        repo_path: Path | None = None,
        code_commit: str | None = None,
    ) -> FeaturesRun:
        # layers 1-2: ingest + resolve, then features; stored for inspection (C4-T16b)
        graph = build_graph(graph_document, reverse=self._config.graph_reverse_edges)
        ingestion = self._ingestion.ingest(list(payloads), graph, adr_document)
        features = self._features.extract(ingestion.resolved, graph, repo_path, ingestion.adr_index)
        first = ingestion.resolved[0].event if ingestion.resolved else None
        run = FeaturesRun(
            run_id=run_id,
            system_id=str(graph.graph.get("system_id") or (first.system_id if first else "")),
            release_id=str(
                graph.graph.get("release_id") or (first.window.end_release if first else "")
            ),
            ingestion=ingestion,
            features=features,
        )
        if self._runs is not None:
            self._runs.save(
                run_row(run, data_provenance, code_commit, repo_path),
                ingestion_rows(run),
                feature_rows(run),
            )
        return run


# Scoring input: features -> the scoring engine's plain rows (subcomponents never import
# each other). Hotspot and AV are active only when the features subcomponent says so.


def scoring_inputs(features: FeatureSet) -> tuple[list[Dimension], list[RawEvent]]:
    active = [Dimension.BLAST_RADIUS]
    if features.hotspot.active:
        active.append(Dimension.HOTSPOT)
    if features.adr.active:
        active.append(Dimension.ADR_VIOLATION)
    active.append(Dimension.PERSISTENCE)
    return active, [_raw_event(row) for row in features.events]


def _raw_event(row: EventFeatures) -> RawEvent:
    br, ps, eh, av = row.blast_radius, row.persistence, row.hotspot, row.adr_violation
    values = {
        "br_fan_in_ratio": br.fan_in_ratio,
        "br_pagerank": br.pagerank,
        "br_betweenness": br.betweenness,
        "br_depth": float(br.depth),
        "ps_consecutive_releases": float(ps.consecutive_releases),
        "ps_growth_slope": ps.growth_slope,
    }
    if eh is not None:
        values |= {
            "eh_churn_decayed": eh.churn_decayed,
            "eh_authors": float(eh.authors),
            "eh_coupling": float(eh.coupling),
            "eh_bugfix_ratio": eh.bugfix_ratio,
        }
    if av is not None:
        values["av_weight"] = av.av
    return RawEvent(event_id=row.event_id, values=values)


# Plain rows for the ScoringRunRepository port; keys = c4_* table columns.


def run_row(
    run: FeaturesRun, data_provenance: str, code_commit: str | None, repo_path: Path | None
) -> dict[str, Any]:
    hotspot, adr, ingestion = run.features.hotspot, run.features.adr, run.ingestion
    outcomes = [record.outcome for record in ingestion.payloads]
    return {
        "run_id": run.run_id,
        "system_id": run.system_id,
        "release_id": run.release_id,
        "created_at": dt.datetime.now(dt.UTC),
        "data_provenance": data_provenance,
        "code_commit": code_commit,
        "payloads": len(outcomes),
        "ranked": outcomes.count("ranked"),
        "skipped": outcomes.count("skipped"),
        "quarantined": outcomes.count("quarantined"),
        "resolution_rate": ingestion.resolution_rate,
        "hotspot_active": hotspot.active,
        "hotspot_inactive_reason": hotspot.inactive_reason,
        "half_life_days": hotspot.half_life_days,
        "decay_rate_per_day": hotspot.decay_rate,
        "cochange_threshold": hotspot.cochange_threshold,
        "max_files_per_commit": hotspot.max_files_per_commit,
        "unmapped_line_share": hotspot.unmapped_line_share,
        "adr_active": adr.active,
        "adr_inactive_reason": adr.inactive_reason,
        "details": {
            "repo_path": repo_path.resolve().as_posix() if repo_path else None,
            "adr_status_weights": adr.status_weights,
            "adr_scope_weights": adr.scope_weights,
            "adr_explicitness": adr.explicitness,
        },
    }


def ingestion_rows(run: FeaturesRun) -> list[dict[str, Any]]:
    return [{"run_id": run.run_id, **record.model_dump()} for record in run.ingestion.payloads]


def feature_rows(run: FeaturesRun) -> list[dict[str, Any]]:
    return [_feature_row(run.run_id, row) for row in run.features.events]


def _feature_row(run_id: str, row: EventFeatures) -> dict[str, Any]:
    br, ps, eh, av = row.blast_radius, row.persistence, row.hotspot, row.adr_violation
    return {
        "run_id": run_id,
        "event_id": row.event_id,
        "br_fan_in_ratio": br.fan_in_ratio,
        "br_pagerank": br.pagerank,
        "br_betweenness": br.betweenness,
        "br_depth": br.depth,
        "br_betweenness_sampled": br.betweenness_sampled,
        "eh_churn_decayed": eh.churn_decayed if eh else None,
        "eh_authors": eh.authors if eh else None,
        "eh_coupling": eh.coupling if eh else None,
        "eh_bugfix_ratio": eh.bugfix_ratio if eh else None,
        "eh_commits": eh.commits if eh else None,
        "eh_from_release": eh.from_release if eh else None,
        "eh_to_release": eh.to_release if eh else None,
        "eh_first_seen_fallback": eh.first_seen_fallback if eh else None,
        "eh_paths_available": eh.paths_available if eh else None,
        "ps_consecutive_releases": ps.consecutive_releases,
        "ps_growth_slope": ps.growth_slope,
        "ps_growth_slope_available": ps.growth_slope_available,
        "ps_growth_metric": ps.growth_metric,
        "ps_presence_fallback": ps.presence_fallback,
        "av_weight": av.av if av else None,
        "av_adr_id": av.adr_id if av else None,
        "av_linked_adrs": av.linked_adrs if av else None,
    }
