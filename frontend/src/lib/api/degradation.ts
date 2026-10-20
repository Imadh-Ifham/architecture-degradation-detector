/**
 * Degradation detection endpoints.
 *
 * Description:
 *   A run reads every validated release of one repository - the graphs the
 *   validation phase published - and reports, release by release, which
 *   anti-patterns are present, and across releases, which measures are
 *   getting worse with statistical support.
 *
 *   The report is one document. It is small (a few releases of a few dozen
 *   elements), every card on the drift screen reads a different part of it,
 *   and fetching it in pieces would mean five loading states for one run.
 */

import { get, post, type RequestOptions } from './client'

export type Scope = 'ELEMENT' | 'INSTANCE' | 'SYSTEM'
export type GateStatus = 'ACCEPTED' | 'DOWNWEIGHTED' | 'EXCLUDED'
export type Worsening = 'INCREASE' | 'DECREASE'
export type TestMethod = 'EXACT' | 'PERMUTATION' | 'NORMAL' | 'DEGENERATE'
export type Transition = 'INTRODUCED' | 'GREW' | 'SHRANK' | 'PERSISTED'
export type Lifecycle = 'introduced' | 'growing' | 'persistent' | 'resolved'

export interface DetectionRunStamp {
  run_id: string
  system_id: string
  status: 'RUNNING' | 'COMPLETED' | 'FAILED'
  started_at: string
  finished_at: string | null
  config_hash: string
  code_version: string
  timings: Record<string, number>
  error: string | null
  trend: { min_releases: number; alpha: number; gate_on: string; time_axis: string }
  gate: { accept: number; exclude: number }
}

export interface DriftElement {
  id: string
  name: string
  kind: string
  size: number | null
  size_unit: string | null
  /** The same element across releases, renames included. */
  lineage_id: string | null
}

export interface DriftDependency {
  source: string
  target: string
  types: string[]
  count: number
}

export interface AntiPatternInstance {
  release_id: string
  local_instance_id: string
  anti_pattern_type: string
  catalog: string
  scope: Scope
  members: string[]
  measures: Record<string, number | null>
  /** The same instance across releases, once tracking has linked it. */
  track_id: string | null
  transition: Transition | null
}

export interface DriftRelease {
  release_id: string
  released_at: string
  /** Position on the run's timeline; null for a release that is not on it. */
  ordinal: number | null
  on_timeline: boolean
  absent_because: string | null
  gate_status: GateStatus
  validation_confidence: number
  architecture_style: string
  c2_validation_ref: string | null
  elements: DriftElement[]
  dependencies: DriftDependency[]
  datastore_access: { element_id: string; datastore: string; mode: string | null }[] | null
  /** Detectors that looked. A type not listed here was not checked. */
  detectors_run: string[]
  instances: AntiPatternInstance[]
  element_metrics: Record<string, Record<string, number | null>>
  system_metrics: Record<string, number | null>
}

export interface Lineage {
  lineage_id: string
  kind: string
  members: { release_id: string; element_id: string }[]
}

export interface InstanceTrack {
  track_id: string
  anti_pattern_type: string
  catalog: string
  scope: Scope
  end: 'OPEN' | 'RESOLVED' | 'UNCHECKED'
  ended_at: string | null
  lifecycle: Lifecycle | null
  occurrences: {
    release_id: string
    local_instance_id: string
    members: string[]
    transition: Transition
  }[]
}

export interface SeriesPoint {
  ordinal: number
  release_id: string
  /** Null stays null: a release with no value is a gap, never a zero. */
  value: number | null
}

/** One series that was tested: Mann-Kendall, Sen's slope, and the corrected q. */
export interface TrendResult {
  scope: Scope
  subject_id: string
  metric: string
  unit: string
  worsening: Worsening
  points: SeriesPoint[]
  n: number
  s: number
  var_s: number | null
  z: number | null
  tau: number
  p_value: number
  q_value: number
  method: TestMethod
  time_axis: string
  sen_slope: number
  intercept: number
  is_worsening: boolean
  is_significant: boolean
}

export interface UntestedSeries {
  scope: Scope
  subject_id: string
  metric: string
  reason: string
  n_points: number
}

export interface AffectedMetric {
  metric: string
  unit: string | null
  worsening: Worsening
  n: number
  s: number
  tau: number
  p_value: number
  q_value: number
  test_method: TestMethod
  sen_slope: number | null
  time_axis: string
  series: { release_id: string; value: number | null }[]
}

/** What is handed to the scoring phase: one anti-pattern that is getting worse. */
export interface DegradationEvent {
  schema_version: string
  event_id: string
  event_key: string
  run_id: string
  system_id: string
  scope: Scope
  anti_pattern_type: string
  catalog: string
  architecture_style: string
  instance_id: string | null
  members: string[]
  element_id: string | null
  lineage_id: string | null
  lifecycle: Lifecycle | null
  window: {
    start_release: string
    end_release: string
    n_releases: number
    low_confidence_releases: string[]
  }
  affected_metrics: AffectedMetric[]
  trend_strength: number
  context: { tag: string; stage: string }
  review_status: string
  provenance: Record<string, unknown>
}

export interface StaticFlag {
  release_id: string
  element_id: string
  metric: string
  value: number
  threshold: number
}

export interface DegradationReport {
  run: DetectionRunStamp
  /** The timeline in order, then the stored releases that are not on it. */
  releases: DriftRelease[]
  lineages: Lineage[]
  tracks: InstanceTrack[]
  trends: TrendResult[]
  untested: UntestedSeries[]
  events: DegradationEvent[]
  static_flags: StaticFlag[]
  /**
   * Where the scoring phase reads this run from: `scripts/c4_rank.py --events
   * <events> --graph <graph>`. A path is null when that file was not written,
   * as for a run made from the command line.
   */
  handover?: {
    events: string | null
    graph: string | null
    latest_events: string | null
    latest_graph: string | null
  }
}

/** What happened to one published graph on its way in. */
export interface IngestOutcome {
  source: string
  status: 'STORED' | 'UNCHANGED' | 'REPLACED' | 'REJECTED'
  system_id: string | null
  release_id: string | null
  gate_status: GateStatus | null
  reason: string | null
  detail: string | null
  accepted: boolean
}

export interface DegradationRun {
  ingest: IngestOutcome[]
  report: DegradationReport
}

/** Read every validated release of a repository and detect over them. */
export function runDegradation(repositoryId: string, options?: RequestOptions) {
  return post<DegradationRun>('/degradation/runs', { repository_id: repositoryId }, options)
}

/**
 * The latest completed run.
 *
 * A 404 means detection has not run for that repository, which is a state
 * with its own screen rather than a failure.
 */
export function readLatestDegradation(repositoryId: string, options?: RequestOptions) {
  return get<DegradationReport>('/degradation/runs/latest', {
    ...options,
    query: { repository_id: repositoryId },
  })
}
