/**
 * Repository and architecture endpoints.
 *
 * Description:
 *   Ingesting a repository, listing what is ingested, and reading the
 *   architecture snapshots the analysis stored for each release.
 *
 *   The types mirror the backend's response schemas field for field. Where a
 *   field is optional here it is optional there, and a mismatch is meant to
 *   surface as a type error rather than as an empty box on a screen.
 */

import { get, post, remove, type RequestOptions } from './client'

export interface RepositorySource {
  url: string
  branch: string
}

export interface ReleaseSource extends RepositorySource {
  revision: string
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

/** Counts a stage of the analysis reports about what it found. */
export interface StageSummary {
  path: string
  [metric: string]: string | number | boolean | Record<string, number>
}

export interface IngestResult extends IngestedRepository {
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

export function listRepositories(options?: RequestOptions) {
  return get<IngestedRepository[]>('/repositories', options)
}

export function ingestRepository(source: RepositorySource, options?: RequestOptions) {
  return post<IngestResult>('/repositories', source, options)
}

/**
 * Clone one explicit revision and record it as its own release.
 *
 * Separate from `ingestRepository` because it is a different act: ingesting a
 * branch follows a moving target, ingesting a revision pins one and leaves the
 * others alone.
 */
export function ingestRelease(source: ReleaseSource, options?: RequestOptions) {
  return post<IngestResult>('/repositories/releases', source, options)
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
