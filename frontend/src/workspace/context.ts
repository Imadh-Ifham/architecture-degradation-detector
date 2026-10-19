/**
 * What the application is looking at, as a type and a context.
 *
 * Description:
 *   One repository, one release, and the run that was last started for it.
 *   Held in one place because every screen needs the same answer: without it
 *   each one grows its own picker, they disagree, and a person has to say
 *   which release they mean three times on three screens.
 *
 *   The last run lives here for the same reason. The pipeline starts it, the
 *   decisions screen supplies what it is judged against, and the findings
 *   screen reads what it produced - three screens, one run.
 */

import { createContext } from 'react'
import type { DecisionMode, IngestedRepository, ValidationRun } from '../lib/api'

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

  /** The run started from the pipeline, once it has finished. */
  run: ValidationRun | null
  /** What the run is judged against, chosen on the decisions screen. */
  decisionMode: DecisionMode | null
  /** True between pressing run and the backend answering. */
  isRunning: boolean
  runError: string | null

  select: (repositoryId: string) => void
  selectRelease: (releaseId: string) => void
  chooseDecisionMode: (mode: DecisionMode) => void
  startRun: (mode: DecisionMode, adrRepositoryId?: string) => Promise<boolean>
  clearRun: () => void
  reload: () => void
}

export const WorkspaceContext = createContext<Workspace | null>(null)
