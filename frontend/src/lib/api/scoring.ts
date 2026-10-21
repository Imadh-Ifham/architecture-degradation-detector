/**
 * Scoring endpoints.
 *
 * Description:
 *   Scoring a detection run (the pipeline's Score phase), the saved rankings,
 *   the severity report of one of them, and that run's saved files (the
 *   report as JSON or a standalone page, and the manifest of how it was made).
 *
 *   The report's types are generated from the backend's JSON Schema
 *   (`../severityReport.ts`) and re-exported here, so a screen imports them
 *   from `lib/api` like every other shape.
 */

import { get, post, type RequestOptions } from './client'
import type { DataProvenance, Dimension, SeverityReportV1 } from '../severityReport'

export type {
  DataProvenance,
  Dimension,
  DimensionScore,
  QuarantinedEvent,
  SeverityRecord,
  SeverityReportV1,
  SkippedEvent,
} from '../severityReport'

/** One saved scoring run, as the run list describes it. */
export interface ScoringRunSummary {
  run_id: string
  system_id: string
  release_id: string
  data_provenance: DataProvenance
  active_dimensions: Dimension[]
  counts: {
    payloads: number
    ranked: number
    skipped: number
    quarantined: number
  }
  resolution_rate: number
  created_at: string
}

/** The ranking a detection run gets: one per detection run, named after it. */
export function scoringRunId(detectionRunId: string): string {
  return `score-${detectionRunId}`
}

/** Score one detection run; a run already scored comes back as it is. */
export function scoreDetectionRun(
  repositoryId: string,
  detectionRunId: string,
  options?: RequestOptions,
) {
  return post<ScoringRunSummary>(
    '/degradation-scoring/runs',
    { repository_id: repositoryId, detection_run_id: detectionRunId },
    options,
  )
}

export function listScoringRuns(options?: RequestOptions) {
  return get<ScoringRunSummary[]>('/degradation-scoring/runs', options)
}

export function readSeverityReport(runId: string, options?: RequestOptions) {
  return get<SeverityReportV1>(
    `/degradation-scoring/runs/${encodeURIComponent(runId)}/report`,
    options,
  )
}

/** A saved run's files that can be read back unchanged. */
export type RunFile =
  | 'c4_report.json'
  | 'c4_report.html'
  | 'c4_run_manifest.json'
  | 'c4_quarantine.json'

/** Where a run's file is served, for a link or a download. */
export function runFileUrl(runId: string, name: RunFile): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? '/api'
  return `${base}/degradation-scoring/runs/${encodeURIComponent(runId)}/files/${name}`
}

/** How a run was made: what the run manifest records, as far as the screen shows it. */
export interface RunManifest {
  run_id: string
  created_at: string
  code_commit: string | null
  report_schema_version: string
  python: string
  topsis_mode: string
  inputs: {
    events_hash: string
    graph_hash: string
    adr_index_hash: string | null
    source_paths_hash: string | null
    path_mapping: string | null
    repo_path: string | null
  }
  weights: {
    version: string
    provenance: string
    ahp_cr: number
    used: Partial<Record<Dimension, number>>
  }
  normalization: { mode: string; lower_percentile: number; upper_percentile: number }
  hotspot: { active: boolean; inactive_reason: string | null; unmapped_line_share?: number | null }
  adr: { active: boolean; inactive_reason: string | null }
  seeds: { seed: number }
  packages: Record<string, string>
}

export function readRunManifest(runId: string, options?: RequestOptions) {
  return get<RunManifest>(
    `/degradation-scoring/runs/${encodeURIComponent(runId)}/files/c4_run_manifest.json`,
    options,
  )
}

