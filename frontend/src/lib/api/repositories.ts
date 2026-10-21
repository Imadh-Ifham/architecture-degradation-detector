/**
 * Repository setup, ingestion, recovery, and architecture snapshots.
 *
 * Description:
 *   Four different acts, deliberately four different calls.
 *
 *   **Saving a snapshot clones nothing.** A configuration is a url, a branch
 *   and a release tag written down for a later run, which is what makes the
 *   pipeline's input reviewable before anything expensive happens.
 *
 *   **Ingesting clones, and only clones.** Recovery is its own endpoint, so
 *   the two can fail, retry and be ordered independently - which is what the
 *   pipeline needs to recover one snapshot before starting the next.
 *
 *   The types mirror the backend's response schemas field for field. Where a
 *   field is optional here it is optional there, and a mismatch is meant to
 *   surface as a type error rather than as an empty box on a screen.
 */

import { get, post, remove, type RequestOptions } from './client'

export interface RepositorySource {
  url: string
  branch: string
  /** A tag or commit. Present means pin one revision instead of a branch tip. */
  revision?: string
}

export interface IngestedRepository {
  id: string
  url: string
  branch: string
  commit: string
  path: string
  ingested_at: string
  repository_id?: string | null
  release_tag?: string | null
  release_date?: string | null
}

/** One snapshot written down for a later pipeline run. */
export interface RepositoryConfiguration {
  id: string
  url: string
  branch: string
  release_tag: string
  created_at: string
}

export type RepositoryConfigurationInput = Omit<
  RepositoryConfiguration,
  'id' | 'created_at'
>

/** How far a configured snapshot has got on this machine. */
export type SnapshotStage = 'pending' | 'cloned' | 'recovered'

/**
 * What the pipeline would still have to do for one configured snapshot.
 *
 * `needs_clone` and `needs_recovery` say the same thing as `stage` from the
 * run's side. Re-cloning is not idle: it replaces the checkout directory,
 * which is where that snapshot's recovery artifacts live.
 */
export interface ConfigurationState {
  configuration_id: string
  url: string
  branch: string
  release_tag: string
  /** The directory ingestion derives from the url and revision. */
  workspace_id: string
  /**
   * The identity the architecture is stored under, shared by every release of
   * the repository. It is what a validation run is keyed by.
   */
  repository_id: string
  stage: SnapshotStage
  needs_clone: boolean
  needs_recovery: boolean
  clone: {
    id: string
    commit: string
    branch: string
    release_tag: string | null
    ingested_at: string
  } | null
  recovery: {
    release_id: string
    commit_sha: string
    finished_at: string | null
    duration_ms: number | null
    element_count: number | null
    relationship_count: number | null
  } | null
}

/** Counts a stage of the analysis reports about what it found. */
export interface StageSummary {
  path: string
  [metric: string]: string | number | boolean | Record<string, number>
}

/** An ingested repository plus what each recovery stage found in it. */
export interface RecoveryResult extends IngestedRepository {
  inventory?: StageSummary | null
  inventory_error?: string | null
  manifest_analysis?: StageSummary | null
  manifest_analysis_error?: string | null
  component_discovery?: StageSummary | null
  component_discovery_error?: string | null
  dependency_resolution?: StageSummary | null
  dependency_resolution_error?: string | null
  source_code_analysis?: StageSummary | null
  source_code_analysis_error?: string | null
  graph_construction?: StageSummary | null
  graph_construction_error?: string | null
}

export interface SnapshotSummary {
  snapshot_id: string
  repository_id: string
  release_id: string
  release_tag: string | null
  commit_sha: string
  status: string
  order_timestamp: string
  order_source: string
  element_count: number
  relationship_count: number
  analysis_id: string
  analysis_timestamp: string
}

export interface SnapshotElement {
  id: string
  logical_id: string | null
  name: string
  kind: string
  identity_basis: string
  size: number | null
  size_unit: string | null
  confidence: string | null
}

export interface SnapshotRelationship {
  id: string
  source_id: string
  target_id: string
  kind: string
  confirmed_by_source: boolean
}

export interface SnapshotUnresolved {
  stage: string
  status: string
  reference: string
  reason: string
}

export interface ArchitectureSnapshot {
  schema_version: string
  snapshot_id: string
  status: string
  repository: Record<string, string | null>
  order_timestamp: string
  order_source: string
  elements: SnapshotElement[]
  relationships: SnapshotRelationship[]
  unresolved: SnapshotUnresolved[]
  diagnostics: string[]
  notes: string[]
}

/* The evidence behind a snapshot ------------------------------------------ */

/** What discovery concluded about one element, and from what. */
export interface ElementDetection {
  type: string | null
  method: string | null
  confidence: string | null
  root_path: string | null
  languages: string[]
  file_count: number | null
  inventory_kind: string | null
  inventory_confidence: string | null
}

/** One artifact that contributed to identifying a component. */
export interface ElementArtifact {
  id: string
  role: string | null
  kind: string | null
  path: string | null
  name: string | null
  line: number | null
  confidence: string | null
  evidence: DiscoveryEvidence[]
}

export interface DiscoveryEvidence {
  source?: string
  type?: string
  detail?: string
  confidence?: string
  path?: string | null
  line?: number | null
  rule?: string | null
}

/** One file the inventory attributed to a component. */
export interface ElementFile {
  path: string
  name: string | null
  category: string | null
  language: string | null
  format: string | null
  size_bytes: number | null
}

/** One entry of the snapshot's own stage-level evidence. */
export interface SnapshotEvidenceEntry {
  stage: string
  type: string
  declared: boolean
  count: number
  references: string[]
}

export interface ElementDetails {
  id: string
  name: string
  kind: string
  logical_id: string | null
  identity_basis: string
  size: number | null
  size_unit: string | null
  confidence: string | null
  detected: ElementDetection
  artifacts: ElementArtifact[]
  discovery_evidence: DiscoveryEvidence[]
  snapshot_evidence: SnapshotEvidenceEntry[]
  files: ElementFile[]
  source_file_count: number
  languages: string[]
}

/** Where a protocol was established, strongest first. */
export type ProtocolSource = 'declared' | 'source' | 'unknown'

export interface ResolutionDetails {
  type: string | null
  confidence: string | null
  status: string | null
  method: string | null
  target_class: string | null
  target_infrastructure_kind: string | null
}

export interface DeclaredEvidence {
  source: string
  type: string
  detail: string
  declared: boolean
  path: string | null
  line: number | null
  key: string | null
  endpoint: string | null
  resolution_method: string | null
}

export interface SourceEvidenceEntry {
  evidence_type: string
  strength: string
  path: string
  line: number
  symbol: string | null
  method: string | null
  detail: string
  target_reference: string | null
  language: string
}

export interface RelationshipDetails {
  id: string
  source_id: string
  target_id: string
  kind: string
  confirmed_by_source: boolean
  protocols: string[]
  protocol_source: ProtocolSource
  endpoints: string[]
  ports: number[]
  resolution: ResolutionDetails | null
  declared_evidence: DeclaredEvidence[]
  source_evidence: SourceEvidenceEntry[]
  source_findings: {
    id: string
    type: string | null
    strength: string | null
    language: string | null
    target_reference: string | null
  }[]
  snapshot_evidence: SnapshotEvidenceEntry[]
}

export interface ArtifactAvailability {
  name: string
  file: string
  present: boolean
}

/** Everything the recovery artifacts can say about one snapshot. */
export interface ArchitectureDetails {
  snapshot_id: string
  repository_id: string
  release_id: string
  artifacts: ArtifactAvailability[]
  elements: ElementDetails[]
  relationships: RelationshipDetails[]
}

/* Configured snapshots ---------------------------------------------------- */

export function listConfigurations(options?: RequestOptions) {
  return get<RepositoryConfiguration[]>('/repositories/configurations', options)
}

/** Write down a snapshot. Nothing is cloned and nothing is analysed. */
export function saveConfiguration(
  input: RepositoryConfigurationInput,
  options?: RequestOptions,
) {
  return post<RepositoryConfiguration>('/repositories/configurations', input, options)
}

/**
 * What the pipeline still has to do for each configured snapshot.
 *
 * The answer is read from what previous runs left on disk, so pressing run
 * again does not re-clone a checkout that exists or re-recover one whose
 * architecture is already stored. Nothing is cloned or analysed by this call.
 */
export function readConfigurationStates(options?: RequestOptions) {
  return get<ConfigurationState[]>('/repositories/configurations/state', options)
}

export function removeConfiguration(
  configurationId: string,
  options?: RequestOptions,
) {
  return remove(
    `/repositories/configurations/${encodeURIComponent(configurationId)}`,
    options,
  )
}

/* Ingestion and recovery -------------------------------------------------- */

export function listRepositories(options?: RequestOptions) {
  return get<IngestedRepository[]>('/repositories', options)
}

/** Clone a repository. This does not run architecture recovery. */
export function ingestRepository(source: RepositorySource, options?: RequestOptions) {
  return post<IngestedRepository>('/repositories', source, options)
}

/**
 * Run architecture recovery over a repository that is already cloned.
 *
 * The stages report themselves; a stage that could not run leaves its summary
 * null and says why in `<stage>_error`. A snapshot is only usable by
 * validation when `graph_construction` came back.
 */
export function runRecovery(repositoryId: string, options?: RequestOptions) {
  return post<RecoveryResult>(
    `/repositories/${encodeURIComponent(repositoryId)}/recovery`,
    undefined,
    options,
  )
}

export function removeRepository(repositoryId: string, options?: RequestOptions) {
  return remove(`/repositories/${encodeURIComponent(repositoryId)}`, options)
}

export function listSnapshots(repositoryId: string, options?: RequestOptions) {
  return get<SnapshotSummary[]>(
    `/repositories/${encodeURIComponent(repositoryId)}/snapshots`,
    options,
  )
}

export function readSnapshot(
  repositoryId: string,
  snapshotId: string,
  options?: RequestOptions,
) {
  return get<ArchitectureSnapshot>(
    `/repositories/${encodeURIComponent(repositoryId)}/snapshots/${encodeURIComponent(snapshotId)}`,
    options,
  )
}

/**
 * The evidence behind one snapshot, joined from the recovery artifacts.
 *
 * The snapshot says what was concluded; this says which manifest declared the
 * endpoint, which line of which source file invoked the service, and what the
 * evidence establishes about how the two communicate - including when it
 * establishes nothing.
 */
export function readSnapshotDetails(
  repositoryId: string,
  snapshotId: string,
  options?: RequestOptions,
) {
  return get<ArchitectureDetails>(
    `/repositories/${encodeURIComponent(repositoryId)}/snapshots/${encodeURIComponent(snapshotId)}/details`,
    options,
  )
}

/* How one release was recovered ------------------------------------------- */

export interface RecoveryStageRecord {
  name: string
  order: number
  status: 'completed' | 'skipped' | 'failed'
  duration_ms: number
  counts: Record<string, number>
  note: string | null
  warnings: string[]
  artifact: string | null
  artifact_present: boolean
}

export interface RecoveryRun {
  schema_version: string
  repository_id: string | null
  workspace_id: string | null
  release_id: string | null
  repository_url: string | null
  branch: string | null
  commit_sha: string | null
  started_at: string
  finished_at: string
  duration_ms: number
  status: 'completed' | 'incomplete' | 'failed'
  stages: RecoveryStageRecord[]
  stage_count: number
}

export interface RecoveredArchitectureSummary {
  element_count: number
  relationship_count: number
  confirmed_by_source: number
  by_component_type: Record<string, number>
  by_language: Record<string, number>
  by_relationship_type: Record<string, number>
  resolved_dependencies: number
  unresolved_dependencies: number
  ambiguous_dependencies: number
  by_finding_type: Record<string, number>
  source_file_count: number
  unresolved_references: SnapshotUnresolved[]
  diagnostics: string[]
  missing_inputs: string[]
  notes: string[]
}

/**
 * The numbers at the top of the recovery page.
 *
 * `null` where the run record is missing: zero completed stages and an
 * unknown number of them are different facts, and only one of them means the
 * pipeline ran six stages and completed none.
 */
export interface RecoverySummary {
  stage_count: number | null
  completed: number | null
  skipped: number | null
  failed: number | null
  duration_ms: number | null
  element_count: number
  relationship_count: number
  artifact_count: number
  warning_count: number | null
  unresolved_count: number
}

export interface RecoveryStageDescription {
  name: string
  order: number
  role: string
  reads: string
  artifact: string | null
  artifact_role: string | null
}

export interface RecoveryReport {
  repository_id: string
  release_id: string
  snapshot_id: string
  commit_sha: string
  branch: string | null
  repository_url: string | null
  released_at: string | null
  snapshot_status: string
  /** Whether this release has a run record at all. */
  recorded: boolean
  run: RecoveryRun | null
  /** The pipeline in run order, described by the backend. */
  pipeline: RecoveryStageDescription[]
  artifacts: ArtifactAvailability[]
  architecture: RecoveredArchitectureSummary
  summary: RecoverySummary
}

/**
 * How one release's architecture was recovered.
 *
 * `recorded: false` means no run record exists for that release - it was
 * analysed before records were kept, or its clone has been removed. The page
 * reports that rather than presenting an empty stage list as a clean run.
 */
export function readRecoveryReport(
  repositoryId: string,
  snapshotId: string,
  options?: RequestOptions,
) {
  return get<RecoveryReport>(
    `/repositories/${encodeURIComponent(repositoryId)}/snapshots/${encodeURIComponent(snapshotId)}/recovery`,
    options,
  )
}
