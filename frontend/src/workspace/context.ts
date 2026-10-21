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
  DegradationReport,
  IngestOutcome,
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

/** What one release is judged against. */
export interface DecisionChoice {
  mode: DecisionMode
  /** Only the modes that read a second repository use this. */
  adrRepositoryId: string | null
}

/** Where a run over every release has got to. */
export interface StackProgress {
  /** Releases finished, successfully or not. */
  done: number
  total: number
  /** The one being validated now, or null while pausing between releases. */
  release: string | null
  /** Seconds left of a deliberate pause, or 0 when not pausing. */
  pausingFor: number
  /**
   * Releases that failed, with the reason.
   *
   * Collected rather than thrown, because a stack run is left unattended: one
   * release refused by a rate limit used to stop the other nineteen, and the
   * person came back to a job that had done almost nothing and said so once.
   */
  failures: { release: string; reason: string }[]
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
  /** Why the stack cannot be judged, when a recovery failure stopped it. */
  pipelineError: string | null
  /**
   * Recover every configured snapshot. Resolves to whether the stack is ready
   * to be judged, so the caller can send somebody to choose what judges it.
   * It does not validate: nothing may pick that source but a person.
   */
  startPipeline: () => Promise<boolean>
  clearPipeline: () => void

  /* Runs this session produced ------------------------------------------- */

  /** Keyed by `runKey(repositoryKey, release_id)`; empty until something runs. */
  runs: Record<string, ValidationRun>
  /** Keep a finished run so the screens showing that release can read it. */
  rememberRun: (run: ValidationRun) => void
  /** The release the last run was about, as a starting point for a screen. */
  focusedRelease: string | null
  /**
   * Point every result screen at one release.
   *
   * What makes a link from a pipeline row to the architecture of *that*
   * release work: the screens already fall back to this when they have no
   * local choice of their own, so a link sets it and navigates.
   */
  focusRelease: (releaseId: string) => void

  /* What each release is judged against ---------------------------------- */

  /**
   * One choice per release, keyed by release id.
   *
   * **Per release rather than per run.** A stack of ten releases is not
   * necessarily judged the same way throughout: a team adopts decision
   * records partway through its history, so the mode that has anything to say
   * about `v0.9.0` may not be the one that has anything to say about `v2.0.0`.
   * One global mode would quietly validate the early releases against a source
   * that did not exist yet.
   */
  decisionChoices: Record<string, DecisionChoice>
  chooseDecision: (releaseId: string, choice: DecisionChoice) => void
  /** Apply one choice to every release at once, for the common case. */
  chooseDecisionForAll: (choice: DecisionChoice) => void

  /**
   * Whether a run asks the second model to attack the first one's verdict.
   *
   * On by default, because an unaudited verdict is what the second model
   * exists to stop being trusted. Off roughly halves the model calls and the
   * tokens, which on a per-minute tier is the difference between a cold run
   * of three minutes and one of about ninety seconds - and every fact it
   * produces is published **unverified and capped**, reported as *not
   * requested* rather than as agreement.
   *
   * A run-level choice rather than a per-release one: it is about what this
   * run is for, not about what any release deserves.
   */
  verifyRuns: boolean
  setVerifyRuns: (verify: boolean) => void

  /** The release being validated right now, or null. One at a time. */
  validatingRelease: string | null
  /**
   * How a run over the whole stack is going, or null when none is.
   *
   * Twenty releases take long enough that "validating v0.9.0" does not say
   * whether it is nearly done or barely started, and whether to keep waiting
   * is the one thing somebody who walked away needs to know.
   */
  stackProgress: StackProgress | null
  /** Validate one release against the choice made for it. */
  validateRelease: (releaseId: string) => Promise<boolean>
  /**
   * Validate every release that has a source chosen, one after another.
   * Clones nothing: recovery already happened, and the expensive half is
   * the model calls, which are paced one release at a time.
   */
  validateAllReleases: () => Promise<void>
  /** Why the last validation failed, named with the release it was for. */
  validationError: string | null

  /* Degradation detection over the validated releases ------------------ */

  /**
   * The latest completed detection run for the selected repository, or null
   * when detection has not run for it.
   *
   * Read from the backend rather than remembered here, because a run is
   * stored: a refresh, or another screen, sees the same run.
   */
  degradation: DegradationReport | null
  /** What happened to each published graph the last run read; empty after a refresh. */
  degradationIngest: IngestOutcome[]
  isLoadingDegradation: boolean
  isDetecting: boolean
  /**
   * Whether a release has been validated since the stored run was made, so
   * the run no longer describes the stack. A stored run from an earlier
   * session is not stale by this measure; the pipeline treats it as not yet
   * run for this stack until something is validated and detected here.
   */
  isDetectionStale: boolean
  detectionError: string | null
  /**
   * Run detection over every release of the repository that has been
   * validated. Resolves to whether a run was stored.
   */
  detectDegradation: () => Promise<boolean>

  selectRepository: (repositoryKey: string) => void
  reload: () => void
}

export const WorkspaceContext = createContext<Workspace | null>(null)
