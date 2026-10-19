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
