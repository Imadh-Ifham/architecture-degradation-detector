# Degradation scoring service: the only way into C4; orchestrates the subcomponents in order
# (ingestion -> features -> scoring -> explanation -> reporting). rank() runs layers 1-3 and
# writes the report and manifest (T20); explanation comes in Phase 4. runs() and report() are
# read-side query methods over saved reports, for the read API.

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, ValidationError

from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.errors import (
    AmbiguousRunError,
    HandoverNotFoundError,
    SavedReportError,
)
from app.components.degradation_scoring.features import FeatureExtractionService
from app.components.degradation_scoring.features.models import EventFeatures, FeatureSet
from app.components.degradation_scoring.ingestion import IngestionService
from app.components.degradation_scoring.ingestion.graph import build_graph
from app.components.degradation_scoring.ingestion.models import IngestionResult
from app.components.degradation_scoring.models import ResolvedEvent, SavedRun
from app.components.degradation_scoring.ports import (
    CommitHistorySource,
    DetectionHandoverSource,
    MiningCache,
    SavedReportSource,
    ScoringRunRepository,
)
from app.components.degradation_scoring.reporting import ReportingService
from app.components.degradation_scoring.reporting.models import EventNotes, ReportView, RunOutputs
from app.components.degradation_scoring.scoring_engine import ScoringService
from app.components.degradation_scoring.scoring_engine.models import RawEvent, ScoringResult
from app.core.config import Settings
from app.domain.degradation_event import ContextTag
from app.domain.severity_report import (
    SCHEMA_VERSION,
    DataProvenance,
    Dimension,
    DimensionScore,
    NormalizationBounds,
    ResolutionStatus,
    SeverityRecord,
    SeverityReportV1,
)
from app.shared.canonical_json import content_hash

log = structlog.get_logger(__name__)

# the files of a saved run that may be read back (CLAUDE.md §6)
RUN_FILES = frozenset(
    {"c4_report.json", "c4_report.html", "c4_run_manifest.json", "c4_quarantine.json"}
)

__all__ = [
    "AmbiguousRunError",
    "DegradationScoringService",
    "HandoverNotFoundError",
    "RankRun",
    "SavedReportError",
    "SavedRun",
    "ScoringRun",
    "service_from_settings",
]


class ScoringRun(BaseModel):
    # the result of layers 1-3 for one (system, release)

    model_config = ConfigDict(frozen=True)

    run_id: str
    system_id: str
    release_id: str
    ingestion: IngestionResult
    features: FeatureSet
    scoring: ScoringResult
    # graph node id -> its readable name (C2 ids can be hashes: component:31a85d9abab5)
    node_names: dict[str, str] = {}


class RankRun(BaseModel):
    # a full rank run: layers 1-3, the report built from them and the files written (T20)

    model_config = ConfigDict(frozen=True)

    run: ScoringRun
    report: SeverityReportV1
    outputs: RunOutputs


class DegradationScoringService:
    # Runs the C4 pipeline for one (system, release); saves each run when given a repository.

    def __init__(
        self,
        config: C4Config,
        *,
        history_source: CommitHistorySource | None = None,
        mining_cache: MiningCache | None = None,
        run_repository: ScoringRunRepository | None = None,
        saved_reports: SavedReportSource | None = None,
        detection_handover: DetectionHandoverSource | None = None,
    ) -> None:
        self._config = config
        self._ingestion = IngestionService(config)
        self._features = FeatureExtractionService(config, history_source, mining_cache)
        self._scoring = ScoringService(config)
        self._reporting = ReportingService()
        self._runs = run_repository
        self._saved = saved_reports
        self._handover = detection_handover

    def rank(
        self,
        payloads: Iterable[object],
        graph_document: object,
        *,
        run_id: str,
        data_provenance: DataProvenance,
        adr_document: object | None = None,
        repo_path: Path | None = None,
        code_commit: str | None = None,
        source_paths: Mapping[str, Sequence[str]] | None = None,
        path_mapping: str | None = None,
    ) -> RankRun:
        # layers 1-3, then report, HTML and manifest in <outputs_root>/<system>/<run_id>/
        # (CLAUDE.md §6); source_paths = a manual element -> paths mapping labelled by
        # path_mapping, replacing the graph's own paths for those elements
        payloads = list(payloads)
        run = self.run_features(
            payloads,
            graph_document,
            run_id=run_id,
            data_provenance=data_provenance.value,
            adr_document=adr_document,
            repo_path=repo_path,
            code_commit=code_commit,
            source_paths=source_paths,
        )
        report = build_report(run, data_provenance)
        facts = manifest_facts(
            run,
            self._config,
            data_provenance=data_provenance,
            code_commit=code_commit,
            inputs={
                "events_hash": content_hash(payloads),
                "graph_hash": content_hash(graph_document),
                "adr_index_hash": None if adr_document is None else content_hash(adr_document),
                "source_paths_hash": None if source_paths is None else content_hash(source_paths),
                "path_mapping": path_mapping,
                "repo_path": repo_path.resolve().as_posix() if repo_path else None,
            },
        )
        outputs = self._reporting.write(
            report,
            report_view(run, path_mapping),
            facts,
            self._config.outputs_root / run.system_id / run_id,
        )
        return RankRun(run=run, report=report, outputs=outputs)

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
        source_paths: Mapping[str, Sequence[str]] | None = None,
    ) -> ScoringRun:
        # layers 1-3: ingest + resolve, features, then normalise + weights + TOPSIS;
        # stored for inspection (C4-T16b, C4-T19)
        graph = build_graph(graph_document, reverse=self._config.graph_reverse_edges)
        for name, paths in sorted((source_paths or {}).items()):
            for node in mapped_nodes(name, graph):
                graph.nodes[node]["source_paths"] = list(paths)
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
            node_names={str(node): str(name) for node, name in graph.nodes(data="name") if name},
        )
        if self._runs is not None:
            self._runs.save(
                run_row(run, data_provenance, code_commit, repo_path),
                ingestion_rows(run),
                feature_rows(run),
                score_rows(run),
            )
        return run

    def score_detection(
        self,
        system_id: str,
        detection_run_id: str,
        *,
        repo_path: Path | None = None,
        code_commit: str | None = None,
        source_paths: Mapping[str, Sequence[str]] | None = None,
        path_mapping: str | None = None,
    ) -> SavedRun:
        # rank one detection run's hand-over as run "score-<detection run>", once: the same
        # detection run is never scored twice, so a repeat returns the saved run
        run_id = f"score-{detection_run_id}"
        saved = self._saved_run(system_id, run_id)
        if saved is not None:
            return saved
        handover = self._handover.read(system_id, detection_run_id) if self._handover else None
        if handover is None:
            raise HandoverNotFoundError(
                f"detection run {detection_run_id!r} of {system_id!r} left no events.json "
                "and release package"
            )
        self.rank(
            handover["events"],
            handover["package"],
            run_id=run_id,
            data_provenance=DataProvenance.LIVE,
            repo_path=repo_path,
            code_commit=code_commit,
            source_paths=source_paths,
            path_mapping=path_mapping,
        )
        saved = self._saved_run(system_id, run_id)
        if saved is None:
            raise SavedReportError(f"run {run_id!r} was written but cannot be read back")
        return saved

    def _saved_run(self, system_id: str, run_id: str) -> SavedRun | None:
        return next(
            (run for run in self.runs() if run.run_id == run_id and run.system_id == system_id),
            None,
        )

    def runs(self) -> list[SavedRun]:
        # read-side query: every saved run, newest first; a manifest that does not fit is
        # logged and left out
        runs = []
        for document in self._saved_source().runs():
            try:
                runs.append(SavedRun.model_validate(document))
            except ValidationError as error:
                log.warning("saved_run_skipped", run_id=document.get("run_id"), error=str(error))
        return sorted(runs, key=lambda run: (run.created_at, run.run_id), reverse=True)

    def report(self, run_id: str) -> SeverityReportV1 | None:
        # read-side query: the saved report of one run, checked against the contract;
        # None when no run has that id
        documents = self._saved_source().reports(run_id)
        if len(documents) > 1:
            systems = sorted(str(document.get("system_id")) for document in documents)
            raise AmbiguousRunError(f"run {run_id!r} exists for several systems: {systems}")
        if not documents:
            return None
        try:
            return SeverityReportV1.model_validate(documents[0])
        except ValidationError as error:
            raise SavedReportError(f"saved report {run_id!r} breaks SeverityReportV1") from error

    def run_file(self, run_id: str, name: str) -> bytes | None:
        # read-side query: one of a saved run's files (RUN_FILES), for download and the run
        # details; None when no run has that id or the file is not one of them
        if name not in RUN_FILES:
            return None
        found = self._saved_source().files(run_id, name)
        if len(found) > 1:
            raise AmbiguousRunError(f"run {run_id!r} exists for several systems")
        return found[0] if found else None

    def _saved_source(self) -> SavedReportSource:
        if self._saved is None:
            raise SavedReportError("no saved report source configured")
        return self._saved


def service_from_settings(settings: Settings, **ports: Any) -> DegradationScoringService:
    # the service with C4Config from the app settings, for entry points (API); ports by name
    return DegradationScoringService(C4Config.from_settings(settings), **ports)


def mapped_nodes(name: str, graph: Any) -> list[str]:
    # a mapping key names a node by its id, by the id without a kind prefix
    # ("checkoutservice" for "svc:checkoutservice") or by the node's name (C2 ids can be
    # hashes: "component:31a85d9abab5" named "currencyservice")
    if name in graph:
        return [name]
    return [
        node
        for node, label in graph.nodes(data="name")
        if str(node).partition(":")[2] == name or label == name
    ]


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


# The report (CLAUDE.md §4.2): one SeverityRecord per ranked event, all four dimensions listed.
# A criterion's value is its criterion score (weighted mean of its normalised features, §5.1;
# AV is already on 0-1), which is also what TOPSIS consumed; features holds the raw values.


def build_report(run: ScoringRun, data_provenance: DataProvenance) -> SeverityReportV1:
    scoring, ingestion = run.scoring, run.ingestion
    return SeverityReportV1(
        schema_version=SCHEMA_VERSION,
        run_id=run.run_id,
        system_id=run.system_id,
        release_id=run.release_id,
        data_provenance=data_provenance,
        active_dimensions=list(scoring.weights.active_criteria),
        weights_version=scoring.weights.version,
        weights_provenance=scoring.weights.provenance,
        ahp_cr=scoring.weights.consistency_ratio,
        normalization=scoring.normalised.mode,
        normalization_bounds={
            key: NormalizationBounds(lower=bounds.lower, upper=bounds.upper)
            for key, bounds in scoring.normalised.calibration.bounds.items()
        },
        resolution_rate=ingestion.resolution_rate,
        records=_records(run),
        quarantined=list(ingestion.quarantined),
        skipped=list(ingestion.skipped),
    )


def _records(run: ScoringRun) -> list[SeverityRecord]:
    scoring = run.scoring
    resolved = {item.event.event_id: item for item in run.ingestion.resolved}
    features = {row.event_id: row for row in run.features.events}
    criteria = {event.event_id: event.criteria for event in scoring.normalised.events}
    records = []
    for ranked in scoring.ranking:
        item = resolved[ranked.event_id]
        raw = _raw_features(features[ranked.event_id])
        dimensions = {}
        for dimension in Dimension:
            value = criteria[ranked.event_id].get(dimension)
            dimensions[dimension] = (
                DimensionScore(
                    raw=value,
                    normalized=value,
                    weight=scoring.weights.weights[dimension],
                    features=raw[dimension],
                )
                if value is not None
                else DimensionScore(raw=0.0, normalized=0.0, weight=0.0, active=False)
            )
        records.append(
            SeverityRecord(
                event_id=ranked.event_id,
                anti_pattern_type=item.event.anti_pattern_type,
                scope=item.event.scope,
                review_status=item.event.review_status,
                context_tag=item.event.context.tag,
                rank=ranked.rank,
                severity=ranked.severity,
                dimensions=dimensions,
                contributions={d: ranked.contributions[d] for d in Dimension},
                resolution=item.resolution,
                elements=[run.node_names.get(node, node) for node in item.nodes],
            )
        )
    return records


def _raw_features(row: EventFeatures) -> dict[Dimension, dict[str, bool | float | None]]:
    br, ps, eh, av = row.blast_radius, row.persistence, row.hotspot, row.adr_violation
    return {
        Dimension.BLAST_RADIUS: {
            "fan_in_ratio": br.fan_in_ratio,
            "pagerank": br.pagerank,
            "betweenness": br.betweenness,
            "depth": float(br.depth),
        },
        Dimension.HOTSPOT: {
            "churn_decayed": eh.churn_decayed,
            "authors": float(eh.authors),
            "coupling": float(eh.coupling),
            "bugfix_ratio": eh.bugfix_ratio,
            "commits": float(eh.commits),
        }
        if eh
        else {},
        Dimension.ADR_VIOLATION: {"av": av.av} if av else {},
        Dimension.PERSISTENCE: {
            "consecutive_releases": float(ps.consecutive_releases),
            "growth_slope": ps.growth_slope,
        },
    }


# The HTML view: run facts the JSON contract does not carry, and one set of badges per event.


def report_view(run: ScoringRun, path_mapping: str | None) -> ReportView:
    scoring, hotspot, adr = run.scoring, run.features.hotspot, run.features.adr
    resolved = {item.event.event_id: item for item in run.ingestion.resolved}
    features = {row.event_id: row for row in run.features.events}
    notes = {}
    for ranked in scoring.ranking:
        item, row = resolved[ranked.event_id], features[ranked.event_id]
        notes[ranked.event_id] = EventNotes(
            nodes=list(item.nodes),
            flags=_flags(item, row, path_mapping),
            growth_metric=row.persistence.growth_metric,
            adr_id=row.adr_violation.adr_id if row.adr_violation else None,
        )
    return ReportView(
        payloads=len(run.ingestion.payloads),
        topsis_mode=scoring.topsis_mode,
        weights_elicited_by=scoring.weights.elicited_by,
        ahp_lambda_max=scoring.weights.lambda_max,
        elicited_weights=dict(scoring.weights.elicited),
        weights=dict(scoring.weights.weights),
        hotspot_inactive_reason=None if hotspot.active else hotspot.inactive_reason,
        adr_inactive_reason=None if adr.active else adr.inactive_reason,
        unmapped_line_share=hotspot.unmapped_line_share,
        path_mapping=path_mapping,
        notes=notes,
    )


def _flags(item: ResolvedEvent, row: EventFeatures, path_mapping: str | None) -> list[str]:
    # badge texts; a text ending in " off" is drawn as a switched-off criterion
    flags = []
    if item.event.context.tag == ContextTag.UNCERTAIN:
        flags.append("context uncertain")
    if item.resolution.status == ResolutionStatus.PREFIX_FALLBACK:
        flags.append("fallback: path prefix")
    if row.hotspot and row.hotspot.first_seen_fallback:
        flags.append("fallback: first seen")
    if row.persistence.presence_fallback:
        flags.append("fallback: presence")
    if not row.persistence.growth_slope_available:
        flags.append("no growth slope")
    if row.blast_radius.betweenness_sampled:
        flags.append("betweenness sampled")
    if row.hotspot is None:
        flags.append("hotspot off")
    elif not row.hotspot.paths_available:
        flags.append("no source paths")
    elif path_mapping:
        flags.append(path_mapping.replace("-", " "))
    if row.adr_violation is None:
        flags.append("ADR off")
    return flags


# The run manifest's facts (CLAUDE.md §6); reporting adds time, versions and file hashes.


def manifest_facts(
    run: ScoringRun,
    config: C4Config,
    *,
    data_provenance: DataProvenance,
    code_commit: str | None,
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    scoring, ingestion, features = run.scoring, run.ingestion, run.features
    weights, normalised = scoring.weights, scoring.normalised
    outcomes = [record.outcome for record in ingestion.payloads]
    resolutions = [item.resolution.status for item in ingestion.resolved]
    return {
        "run_id": run.run_id,
        "system_id": run.system_id,
        "release_id": run.release_id,
        "data_provenance": data_provenance.value,
        "report_schema_version": SCHEMA_VERSION,
        "code_commit": code_commit,
        "inputs": dict(inputs),
        "counts": {
            "payloads": len(outcomes),
            "ranked": outcomes.count("ranked"),
            "skipped": outcomes.count("skipped"),
            "quarantined": outcomes.count("quarantined"),
            "skipped_by_reason": dict(sorted(ingestion.skip_counts().items())),
            "quarantined_by_reason": dict(sorted(ingestion.quarantine_counts().items())),
        },
        "resolution_rate": ingestion.resolution_rate,
        "active_dimensions": [d.value for d in weights.active_criteria],
        "weights": {
            "version": weights.version,
            "provenance": weights.provenance.value,
            "elicited_by": weights.elicited_by,
            "ahp_cr": weights.consistency_ratio,
            "ahp_ci": weights.consistency_index,
            "ahp_lambda_max": weights.lambda_max,
            "elicited": {d.value: w for d, w in weights.elicited.items()},
            "used": {d.value: w for d, w in weights.weights.items()},
        },
        "normalization": {
            "mode": normalised.mode.value,
            "frozen": normalised.frozen,
            "lower_percentile": normalised.calibration.lower_percentile,
            "upper_percentile": normalised.calibration.upper_percentile,
            "bounds": {
                key: bounds.model_dump() for key, bounds in normalised.calibration.bounds.items()
            },
        },
        "topsis_mode": scoring.topsis_mode,
        "hotspot": {
            **features.hotspot.model_dump(),
            "include_globs": config.history_include_globs,
            "exclude_globs": config.history_exclude_globs,
        },
        "adr": features.adr.model_dump(),
        "stand_ins": {
            "prefix_fallback_events": resolutions.count(ResolutionStatus.PREFIX_FALLBACK),
            "first_seen_fallback_events": sum(
                1 for row in features.events if row.hotspot and row.hotspot.first_seen_fallback
            ),
            "presence_fallback_events": sum(
                1 for row in features.events if row.persistence.presence_fallback
            ),
        },
        "explanation": {"run": False, "llm_model_id": None, "prompt_hashes": {}},
        "seeds": {"seed": config.seed},
        "settings": config.model_dump(mode="json"),
    }
