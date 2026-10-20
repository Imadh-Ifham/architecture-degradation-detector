/**
 * Validation endpoints.
 *
 * Description:
 *   Describing the validation stages, asking what a release could be
 *   validated against, running a validation, and the review queue.
 *
 *   `describePipeline` is the one call the pipeline screen cannot do without:
 *   it returns the stages in run order, which of them call a model and which
 *   are written yet. The screen renders build progress from that rather than
 *   hard-coding a list that goes stale.
 */

import { get, post, type RequestOptions } from './client'

export type DecisionMode = 'repo_adr' | 'external_adr' | 'combined'

export interface StageDescription {
  name: string
  order: number
  role: string
  research_module: string | null
  uses_model: boolean
  implemented: boolean
}

export interface PipelineDescription {
  stage_count: number
  implemented_count: number
  stages: StageDescription[]
}

export interface ModeAvailability {
  mode: DecisionMode
  ran: boolean
  records: number
  reason: string | null
  by_source: Record<string, number>
  /**
   * What each source said for itself.
   *
   * A zero beside a source is not self-explanatory: it can mean the repository
   * holds no written decisions, or that it holds many and none of them states
   * a checkable constraint. `reason` cannot carry that - it is empty whenever
   * another source supplied something, which is the mode where it matters.
   */
  source_notes: Record<string, string>
}

/** One rule a mode supplies, with the line it was read from. */
export interface DecisionRecord {
  decision_id: string
  subject: string
  constraint: string
  object: string
  valid_from: string
  valid_to: string | null
  source: string
  source_tier: string
  source_strength: string
  extraction_method: string
  source_ref: string
  start_line: number | null
  end_line: number | null
  rationale: string | null
}

export interface DecisionRecords {
  repository_id: string
  release_id: string
  mode: DecisionMode
  records: DecisionRecord[]
}

export interface DecisionSources {
  repository_id: string
  release_id: string
  recommended: DecisionMode | null
  modes: ModeAvailability[]
}

export interface StageRecord {
  name: string
  status: 'completed' | 'skipped' | 'pending' | 'failed'
  counts: Record<string, number>
  duration_ms: number
  note: string | null
  warnings: string[]
}

export interface ValidationRun {
  run_id: string
  repository_id: string
  release_id: string
  status: string
  model_calls: number
  validation_confidence: number
  published_ref: string | null
  style_resolved: string | null
  style_source: string | null
  verification_mode: string | null
  verification_arm: string | null
  decision_mode: DecisionMode | null
  stages: StageRecord[]
}

export interface ValidationRequest {
  repository_id: string
  release_id: string
  decision_mode?: DecisionMode
  adr_repository_id?: string | null
  verify?: boolean
  arm?: string
  released_at?: string | null
}

export interface ReviewItem {
  item_id: string
  fact_id: string
  bucket: string
  confidence: number
  source_tier: string | null
  evidence_refs: string[]
  candidate_decision_id: string | null
  status: string
}

export interface ReviewOutcome {
  item_id: string
  status: string
  ratified: number
  note: string
}

export function describePipeline(options?: RequestOptions) {
  return get<PipelineDescription>('/validations/pipeline', options)
}

export function readDecisionSources(
  repositoryId: string,
  releaseId: string,
  options?: RequestOptions,
) {
  return get<DecisionSources>('/validations/decision-sources', {
    ...options,
    query: { repository_id: repositoryId, release_id: releaseId },
  })
}

/** The rules behind a mode's count, each naming the line it came from. */
export function readDecisionRecords(
  repositoryId: string,
  releaseId: string,
  mode: DecisionMode,
  options?: RequestOptions,
) {
  return get<DecisionRecords>('/validations/decision-records', {
    ...options,
    query: { repository_id: repositoryId, release_id: releaseId, mode },
  })
}

export function runValidation(request: ValidationRequest, options?: RequestOptions) {
  return post<ValidationRun>('/validations', request, options)
}

export function listReviews(
  repositoryId?: string,
  releaseId?: string,
  options?: RequestOptions,
) {
  return get<ReviewItem[]>('/validations/reviews', {
    ...options,
    query: { repository_id: repositoryId, release_id: releaseId },
  })
}

export function decideReview(
  itemId: string,
  accepted: boolean,
  decidedBy: string,
  options?: RequestOptions,
) {
  return post<ReviewOutcome>(
    `/validations/reviews/${encodeURIComponent(itemId)}`,
    { accepted, decided_by: decidedBy },
    options,
  )
}

/** One node of the published graph: an element with its validation rollup. */
export interface ValidatedNode {
  id: string
  name: string
  canonical: string
  kind: string
  size: number | null
  size_unit: string | null
  /** The document's own name for it; absent on a node nothing judged. */
  validation_rollup?: ValidationRollup
}

export interface ValidationRollup {
  confirmed: number
  contradicted: number
  uncovered: number
  needs_review: number
}

/** What produced the document, including which models answered. */
export interface RunStamp {
  run_id: string
  generated_at: string
  mode: string
  reasoner_model: string | null
  verifier_model: string | null
  prompt_versions: string[]
}

/** One edge: a dependency with the verdict reached about it. */
export interface ValidatedEdge {
  fact_id: string
  source: string
  target: string
  relationship: string
  bucket: string
  confidence: number
  governing_decision: string | null
  evidence_refs: string[]
  source_tier: string | null
  model_calls: number
  produced_by: string
  verification_outcome: string | null
  arbiter_agreement: string | null
  attributes: Record<string, unknown>
}

export interface PublishedGraph {
  graph: {
    schema_version: string
    repository_id: string
    release_id: string
    released_at: string | null
    architecture_style: string
    validation_confidence: number
    architecture_style_source: string
    released_at_source: string | null
    run: RunStamp
    summary: Record<string, number | string>
  }
  nodes: ValidatedNode[]
  links: ValidatedEdge[]
}

/**
 * The document the most recent completed run published.
 *
 * A 404 means that release has not been validated, which is a state with its
 * own screen rather than a failure.
 */
export function readPublishedGraph(
  repositoryId: string,
  releaseId: string,
  options?: RequestOptions,
) {
  return get<PublishedGraph>('/validations/graph', {
    ...options,
    query: { repository_id: repositoryId, release_id: releaseId },
  })
}
