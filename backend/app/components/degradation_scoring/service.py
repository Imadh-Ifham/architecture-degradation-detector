# Degradation scoring service: the only way into C4; orchestrates the subcomponents in order
# (ingestion -> features -> scoring -> explanation -> reporting). Layers 1-3 so far (T16b,
# T19); T20 adds the report, explanation comes in Phase 4.

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
from app.components.degradation_scoring.scoring_engine import ScoringService
from app.components.degradation_scoring.scoring_engine.models import RawEvent, ScoringResult
from app.domain.severity_report import Dimension


class ScoringRun(BaseModel):
    # the result of layers 1-3 for one (system, release)

    model_config = ConfigDict(frozen=True)

    run_id: str
    system_id: str
    release_id: str
    ingestion: IngestionResult
    features: FeatureSet
    scoring: ScoringResult


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
        self._scoring = ScoringService(config)
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
    ) -> ScoringRun:
        # layers 1-3: ingest + resolve, features, then normalise + weights + TOPSIS;
        # stored for inspection (C4-T16b, C4-T19)
        graph = build_graph(graph_document, reverse=self._config.graph_reverse_edges)
        ingestion = self._ingestion.ingest(list(payloads), graph, adr_document)
        features = self._features.extract(ingestion.resolved, graph, repo_path, ingestion.adr_index)
        first = ingestion.resolved[0].event if ingestion.resolved else None
        system_id = str(graph.graph.get("system_id") or (first.system_id if first else ""))
        release_id = str(
            graph.graph.get("release_id") or (first.window.end_release if first else "")
        )
        active, raw_events = scoring_inputs(features)
        run = ScoringRun(
            run_id=run_id,
            system_id=system_id,
            release_id=release_id,
            ingestion=ingestion,
            features=features,
            scoring=self._scoring.rank(
                raw_events, active, system_id=system_id, release_id=release_id
            ),
        )
        if self._runs is not None:
            self._runs.save(
                run_row(run, data_provenance, code_commit, repo_path),
                ingestion_rows(run),
                feature_rows(run),
                score_rows(run),
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
    run: ScoringRun, data_provenance: str, code_commit: str | None, repo_path: Path | None
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
            "scoring": _scoring_details(run.scoring),
        },
    }


def _scoring_details(scoring: ScoringResult) -> dict[str, Any]:
    weights, normalised = scoring.weights, scoring.normalised
    return {
        "topsis_mode": scoring.topsis_mode,
        "weights_version": weights.version,
        "weights_provenance": weights.provenance.value,
        "ahp_cr": weights.consistency_ratio,
        "ahp_lambda_max": weights.lambda_max,
        "elicited_weights": {d.value: w for d, w in weights.elicited.items()},
        "normalization": normalised.mode.value,
        "calibration_frozen": normalised.frozen,
        "normalization_bounds": {
            key: bounds.model_dump() for key, bounds in normalised.calibration.bounds.items()
        },
    }


def ingestion_rows(run: ScoringRun) -> list[dict[str, Any]]:
    return [{"run_id": run.run_id, **record.model_dump()} for record in run.ingestion.payloads]


def feature_rows(run: ScoringRun) -> list[dict[str, Any]]:
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


# column prefix of each criterion in c4_event_features / c4_event_scores
PREFIXES = {
    Dimension.BLAST_RADIUS: "br",
    Dimension.HOTSPOT: "eh",
    Dimension.ADR_VIOLATION: "av",
    Dimension.PERSISTENCE: "ps",
}


def score_rows(run: ScoringRun) -> list[dict[str, Any]]:
    # one row per ranked event; normalised value NULL, weight and contribution 0 when a
    # criterion is off (as in the report)
    scoring = run.scoring
    criteria = {event.event_id: event.criteria for event in scoring.normalised.events}
    rows = []
    for ranked in scoring.ranking:
        row: dict[str, Any] = {
            "run_id": run.run_id,
            "event_id": ranked.event_id,
            "rank": ranked.rank,
            "severity": ranked.severity,
            "distance_ideal": ranked.distance_ideal,
            "distance_anti_ideal": ranked.distance_anti_ideal,
        }
        for dimension, prefix in PREFIXES.items():
            row[f"{prefix}_normalized"] = criteria[ranked.event_id].get(dimension)
            row[f"{prefix}_weight"] = scoring.weights.weights[dimension]
            row[f"{prefix}_contribution"] = ranked.contributions[dimension]
        rows.append(row)
    return rows
