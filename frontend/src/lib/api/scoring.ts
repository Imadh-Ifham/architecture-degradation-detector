/**
 * Scoring endpoints.
 *
 * Description:
 *   Scoring a detection run (the pipeline's Score phase), the saved rankings,
 *   and the severity report of one of them.
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
