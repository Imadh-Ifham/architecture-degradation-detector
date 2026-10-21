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
  /**
   * How many records of each constraint kind.
   *
   * The total does not say what the records are, and the difference is large:
   * most of what a configuration scan reconstructs declares the operations a
   * service exposes, and an observed dependency carries no operation — so
   * those records are extracted, held and reported, and govern nothing.
   */
  by_constraint: Record<string, number>
  /** How many of them can govern an observed dependency at all. */
  governing: number
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
  /**
   * Ask the models again instead of replaying from the cache, and keep the
   * answers. The run costs its full token budget and leaves the cache warm
   * with the new verdicts, which is what refreshing a release means.
   */
  fresh?: boolean
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
  /**
   * Whether this edge was published or held for a person.
   *
   * A second axis from the bucket, not a stronger version of it: the bucket
   * is what was concluded and this is what happens to the conclusion. Older
   * documents predate the field and read as an empty string.
   */
  route: string
  /**
   * The sealed evidence package this verdict was reached from.
   *
   * It is the key the model request was cached on, so it is what joins an
   * edge back to the calls in the run transcript — which is where the
   * model's own sentences about this dependency are. Older documents predate
   * the field and read as an empty string.
   */
  evidence_hash: string
  /**
   * What the confidence is made of, as named contributions.
   *
   * The component's own rule is that a confidence number carries its score
   * trace. Without it a reader is shown `0.85` on every edge with no way to
   * learn what built it or what the scale is.
   */
  confidence_terms: Record<string, number>
  /** The ceiling that held the number down, or null if none did. */
  confidence_ceiling: string | null
  /** The most this method can publish for any fact. */
  confidence_maximum: number
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

/** One request to one model, as it was sent and as it was answered. */
export interface ModelCall {
  sequence: number
  task: string
  requested_model: string
  answered_model: string
  prompt: string
  prompt_version: string
  schema_mode: string
  evidence_hash: string
  /**
   * `answered` is a model reached on this run and `replayed` is the identical
   * question answered on an earlier one. The second is still a model's answer
   * and not the table's, which is why they are two words and not a boolean.
   */
  outcome: 'answered' | 'replayed' | 'unavailable' | 'unusable'
  latency_ms: number
  response: Record<string, unknown> | null
  error: string | null
  prompt_tokens: number
  completion_tokens: number
}

export interface TranscriptSummary {
  calls: number
  live: number
  replayed: number
  unavailable: number
  unusable: number
  prompt_tokens: number
  completion_tokens: number
}

export interface ModelTranscript {
  run_id: string
  repository_id: string
  release_id: string
  generated_at: string
  reasoner_model: string | null
  verifier_model: string | null
  schema_mode: string
  temperature: number
  base_url: string
  key_configured: boolean
  summary: TranscriptSummary
  calls: ModelCall[]
}

/**
 * Every model call the last run of this release made.
 *
 * A 404 means no transcript was kept, which is not the same as a run that
 * called nothing: a release validated before the calls were recorded has a
 * graph and no transcript.
 */
export function readTranscript(
  repositoryId: string,
  releaseId: string,
  options?: RequestOptions,
) {
  return get<ModelTranscript>('/validations/transcript', {
    ...options,
    query: { repository_id: repositoryId, release_id: releaseId },
  })
}

/** One configured model, asked a trivial question just now. */
export interface ModelProbe {
  task: string
  requested_model: string
  answered_model: string | null
  reachable: boolean
  latency_ms: number
  strict_schema: boolean
  /**
   * Which of strict, best_effort or json_object this call asked for.
   *
   * `strict_schema` alone cannot tell the last two apart, and they are not
   * the same request: one sends a schema the provider enforces, the other
   * sends the schema in the prompt and checks the answer after it arrives.
   * A screen that shows nothing for both reports a weaker guarantee as an
   * absent one.
   */
  schema_mode: string
  prompt: string
  response: Record<string, unknown> | null
  error: string | null
}

export interface ModelAccess {
  base_url: string
  key_configured: boolean
  schema_mode: string
  temperature: number
  /**
   * Whether this deployment lets a verdict come from the deterministic table
   * with no model behind it. It is the setting that makes a keyless run look
   * like a run with a model, so it is reported beside the probes rather than
   * left for somebody to find in a file.
   */
  arbiter_only_allowed: boolean
  reachable: number
  probed: ModelProbe[]
}

/**
 * Ask every configured model a trivial question, now.
 *
 * A POST because it spends tokens. It goes past the response cache on
 * purpose: a cached answer would report a reachable model on a machine with
 * no network, which is the one thing this call exists to rule out.
 */
export function checkModelAccess(options?: RequestOptions) {
  return post<ModelAccess>('/validations/model-access', undefined, options)
}

/**
 * A finished run, written out as sentences by a model.
 *
 * It is a reading of the result and not part of it. Nothing in it reaches a
 * verdict, a confidence or the published graph, and `figures` is exactly what
 * the model was shown so a sentence can be checked against the numbers behind
 * it rather than against the rest of the screen.
 */
export interface RunNarrative {
  headline: string
  what_it_read: string
  what_it_concluded: string
  what_to_distrust: string
  model_id: string
  prompt_version: string
  cached: boolean
  figures: Record<string, unknown>
}

export function narrateRun(
  repositoryId: string,
  releaseId: string,
  options?: RequestOptions,
) {
  return post<RunNarrative>('/validations/narrative', undefined, {
    ...options,
    query: { repository_id: repositoryId, release_id: releaseId },
  })
}

/** A rule the log held that a later release stopped stating. */
export interface WithdrawnRecord {
  decision_id: string
  constraint: string
  subject: string
  object: string
  reason: string | null
}

/**
 * What one release's scan changed in the decision history.
 *
 * The record count on the decisions screen answers *how many rules are in
 * force*, and two releases reporting the same count is the question it
 * cannot answer: the same rules, or a different set of the same size? This
 * is that answer, read out of the decision log rather than recomputed.
 */
export interface ReleaseMovement {
  release_id: string
  recorded: number
  closed: number
  sources: string[]
  withdrawn: WithdrawnRecord[]
}

export function readDecisionHistory(repositoryId: string, options?: RequestOptions) {
  return get<ReleaseMovement[]>('/validations/decision-history', {
    ...options,
    query: { repository_id: repositoryId },
  })
}
