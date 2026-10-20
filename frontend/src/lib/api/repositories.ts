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
