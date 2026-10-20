/**
 * What the application is looking at, as a type and a context.
 *
 * Description:
 *   The configured snapshots, the repository and release being looked at, the
 *   last validation run, and the pipeline run currently in progress.
 *
 *   Held in one place because every screen needs the same answer: without it
 *   each one grows its own picker, they disagree, and a person has to say
 *   which release they mean three times on three screens. The pipeline is
 *   here for the same reason - it is started on one screen and read on
 *   several, and leaving it in the page that started it would lose the run
 *   the moment somebody looked at a result.
 */

import { createContext } from 'react'
import type {
  DecisionMode,
  IngestedRepository,
  RepositoryConfiguration,
  RepositoryConfigurationInput,
  ValidationRun,
} from '../lib/api'
import type { PipelinePhase, SnapshotRun } from './pipeline'

export interface Workspace {
  repositories: IngestedRepository[]
  repository: IngestedRepository | null
  /** The identity recovery stores architecture under, which is not the clone's id. */
  repositoryKey: string
  /** Releases recovery has analysed, newest last. */
  releases: string[]
  release: string | null
  /** Whether the architecture for the selected release exists to validate. */
  isRecovered: boolean
  /**
   * Whether a clone here sits at the commit this release was analysed at.
   *
   * The configuration a release is judged against is read from a working
   * tree, and a tree at a different commit is a different file. Without one
   * the run still completes and reports every dependency as ungoverned,
   * which looks exactly like a repository that records no decisions.
   */
  hasCheckout: boolean
  isLoading: boolean
  error: string | null

  /** The run started from the decisions screen, once it has finished. */
  run: ValidationRun | null
  /** What a single-release run is judged against, chosen on that screen. */
  decisionMode: DecisionMode | null
  /** True between pressing run and the backend answering. */
  isRunning: boolean
  runError: string | null

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

  select: (repositoryId: string) => void
  selectRelease: (releaseId: string) => void
  chooseDecisionMode: (mode: DecisionMode) => void
  startRun: (mode: DecisionMode, adrRepositoryId?: string) => Promise<boolean>
  /** Hand a finished run to the screens that read it. */
  recordRun: (run: ValidationRun) => void
  clearRun: () => void
  reload: () => void
}

export const WorkspaceContext = createContext<Workspace | null>(null)
