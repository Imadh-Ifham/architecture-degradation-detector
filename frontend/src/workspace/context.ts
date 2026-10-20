/**
 * What the application is looking at, as a type and a context.
 *
 * Description:
 *   The configured snapshots, the selected repository, the releases recovery
 *   analysed for it, and the pipeline run in progress.
 *
 *   **The repository is the only thing selected globally.** Which release you
 *   are looking at is a property of a screen, not of the application: one
 *   person compares v0.9.0 on one screen while reading v0.10.6 on another, and
 *   a single global answer makes one of those two screens wrong. Each screen
 *   therefore keeps its own selection (`useReleases`), and the header changes
 *   the repository only.
 *
 *   The pipeline is here because it is started on one screen and read on
 *   several, and leaving it in the page that started it would lose the run the
 *   moment somebody looked at a result. The last run is here for the same
 *   reason, keyed by release: the run record only exists in this browser, and
 *   a screen showing a release should be able to show how it was judged.
 */

import { createContext } from 'react'
import type {
  DecisionMode,
  IngestedRepository,
  RepositoryConfiguration,
  RepositoryConfigurationInput,
  SnapshotSummary,
  ValidationRun,
} from '../lib/api'
import type { PipelinePhase, SnapshotRun } from './pipeline'

/** The key a run is remembered under: one repository, one release. */
export function runKey(repositoryKey: string, releaseId: string | null): string {
  return releaseId ? `${repositoryKey}::${releaseId}` : ''
}

export interface RepositoryOption {
  /** The repository's own identity, which every clone of it shares. */
  key: string
  url: string
}

export interface Workspace {
  /** Every clone currently on the machine, newest first. */
  repositories: IngestedRepository[]
  /** One entry per repository - not per clone, so releases do not repeat it. */
  repositoryOptions: RepositoryOption[]
  /** The clone that represents the selected repository. */
  repository: IngestedRepository | null
  /** The identity recovery stores architecture under, which is not the clone's id. */
  repositoryKey: string
  /** Releases recovery has analysed for the selected repository, oldest first. */
  snapshots: SnapshotSummary[]
  releases: string[]
  isLoading: boolean
  error: string | null

  /* Configured snapshots ------------------------------------------------- */

  /** Every snapshot configured for a pipeline run, in the order it was added. */
  configurations: RepositoryConfiguration[]
  configurationsError: string | null
  isLoadingConfigurations: boolean
  addConfiguration: (
    input: RepositoryConfigurationInput,
  ) => Promise<RepositoryConfiguration>
  removeConfiguration: (configurationId: string) => Promise<void>
  reloadConfigurations: () => void

  /* The pipeline --------------------------------------------------------- */

  pipelinePhase: PipelinePhase
  /** One row per configured snapshot, with what has happened to it so far. */
  pipelineSnapshots: SnapshotRun[]
  isPipelineRunning: boolean
  /** Why validation did not start, when a recovery failure stopped it. */
  pipelineError: string | null
  startPipeline: (mode: DecisionMode, adrRepositoryId?: string) => Promise<void>
  clearPipeline: () => void

  /* Runs this session produced ------------------------------------------- */

  /** Keyed by `runKey(repositoryKey, release_id)`; empty until something runs. */
  runs: Record<string, ValidationRun>
  /** Keep a finished run so the screens showing that release can read it. */
  rememberRun: (run: ValidationRun) => void
  /** The release the last run was about, as a starting point for a screen. */
  focusedRelease: string | null

  selectRepository: (repositoryKey: string) => void
  reload: () => void
}

export const WorkspaceContext = createContext<Workspace | null>(null)
