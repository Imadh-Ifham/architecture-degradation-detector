/**
 * The workspace provider.
 *
 * Description:
 *   Loads the configured snapshots and the ingested repositories, then the
 *   releases recovery analysed for whichever repository is selected, and
 *   holds the pipeline run started over the configured snapshots.
 *
 *   **One repository, many clones.** A release-aware ingest produces one
 *   workspace directory per revision, all sharing a `repository_id`. The
 *   header offers repositories, not clones, so a repository with three
 *   analysed releases appears once; the releases it has are listed by the
 *   screens that show one.
 *
 *   **Releases come from what was analysed, not from what was typed.** A
 *   release exists here once recovery has stored an architecture for it,
 *   which is also the only state in which anything after it can run.
 *
 *   **Configuring and running are different things.** A configuration is a
 *   row in a list; the pipeline is the only thing that clones, recovers and
 *   validates, and it does so in an order the person can see. Nothing here
 *   clones as a side effect of saving.
 */

import { useCallback, useMemo, useState, type ReactNode } from 'react'
import {
  listConfigurations,
  listRepositories,
  listSnapshots,
  messageOf,
  removeConfiguration as deleteConfiguration,
  runValidation,
  saveConfiguration,
  type RepositoryConfigurationInput,
  type SnapshotSummary,
  type ValidationRun,
} from '../lib/api'
import { useRequest } from '../lib/useRequest'
import {
  WorkspaceContext,
  runKey,
  type DecisionChoice,
  type RepositoryOption,
  type Workspace,
} from './context'
import { runPipeline, type PipelinePhase, type SnapshotRun } from './pipeline'

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [pipelinePhase, setPipelinePhase] = useState<PipelinePhase>('idle')
  const [pipelineSnapshots, setPipelineSnapshots] = useState<SnapshotRun[]>([])
  const [pipelineError, setPipelineError] = useState<string | null>(null)
  const [isPipelineRunning, setIsPipelineRunning] = useState(false)
  const [runs, setRuns] = useState<Record<string, ValidationRun>>({})
  const [focusedRelease, setFocusedRelease] = useState<string | null>(null)
  const [decisionChoices, setDecisionChoices] = useState<
    Record<string, DecisionChoice>
  >({})
  const [validatingRelease, setValidatingRelease] = useState<string | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)

  const repositoriesRequest = useRequest((options) => listRepositories(options), [])
  const configurationsRequest = useRequest(
    (options) => listConfigurations(options),
    [],
  )

  const repositories = useMemo(
    () => repositoriesRequest.data ?? [],
    [repositoriesRequest.data],
  )

  const configurations = useMemo(
    () => configurationsRequest.data ?? [],
    [configurationsRequest.data],
  )

  // One entry per repository, because a clone per release would offer the same
  // system three times and name it after a revision.
  const repositoryOptions = useMemo<RepositoryOption[]>(() => {
    const seen = new Map<string, RepositoryOption>()

    for (const clone of repositories) {
      const key = clone.repository_id ?? clone.id
      if (!seen.has(key)) seen.set(key, { key, url: clone.url })
    }

    return [...seen.values()].sort((left, right) => left.url.localeCompare(right.url))
  }, [repositories])

  // Falling back to the first is a convenience, not a guess: with one
  // repository there is nothing to choose between, and with none every screen
  // says so rather than showing an empty frame.
  const repositoryKey =
    repositoryOptions.find((option) => option.key === selectedKey)?.key ??
    repositoryOptions[0]?.key ??
    ''

  const repository =
    repositories.find((clone) => (clone.repository_id ?? clone.id) === repositoryKey) ??
    null

  const snapshotsRequest = useRequest(
    (options) => listSnapshots(repositoryKey, options),
    [repositoryKey],
    Boolean(repositoryKey),
  )

  const snapshots = useMemo<SnapshotSummary[]>(
    () => snapshotsRequest.data ?? [],
    [snapshotsRequest.data],
  )

  const releases = useMemo(
    () => snapshots.map((item) => item.release_id),
    [snapshots],
  )

  const reloadRepositories = repositoriesRequest.reload
  const reloadSnapshots = snapshotsRequest.reload
  const reloadConfigurations = configurationsRequest.reload

  const rememberRun = useCallback((run: ValidationRun) => {
    setRuns((current) => ({
      ...current,
      [runKey(run.repository_id, run.release_id)]: run,
    }))
    setFocusedRelease(run.release_id)
  }, [])

  const focusRelease = useCallback((releaseId: string) => {
    setFocusedRelease(releaseId)
  }, [])

  const chooseDecision = useCallback((releaseId: string, choice: DecisionChoice) => {
    setDecisionChoices((current) => ({ ...current, [releaseId]: choice }))
  }, [])

  const chooseDecisionForAll = useCallback(
    (choice: DecisionChoice) => {
      // Over the releases recovery actually stored, not the configured list.
      // A release recovered in an earlier session is decidable and has no
      // configuration row this session, and applying to "all" while silently
      // skipping it is how one release ends up validated against a source
      // nobody picked for it.
      setDecisionChoices(
        Object.fromEntries(releases.map((release) => [release, choice])),
      )
    },
    [releases],
  )

  /**
   * Validate one release against the choice made for it.
   *
   * One release at a time, started by hand. A stack of fifty releases is
   * minutes of model calls, and a loop over all of them is a progress bar
   * somebody watches instead of a result they read - so the pipeline offers a
   * button per row and this validates the row.
   *
   * It refuses rather than defaulting when no choice has been made: a mode
   * picked by a constant is not a decision anybody made, and the release
   * would be reported as judged.
   */
  const validateRelease = useCallback(
    async (releaseId: string) => {
      if (validatingRelease) return false

      const choice = decisionChoices[releaseId]

      if (!choice) {
        setValidationError(
          `Nothing has been chosen for ${releaseId}. Pick what it is judged against on the decisions screen first.`,
        )
        return false
      }

      setValidatingRelease(releaseId)
      setValidationError(null)

      try {
        rememberRun(
          await runValidation({
            repository_id: repositoryKey,
            release_id: releaseId,
            decision_mode: choice.mode,
            adr_repository_id: choice.adrRepositoryId,
          }),
        )
        return true
      } catch (cause) {
        // The backend names the release and the input that is missing. A
        // message written here would throw that away.
        setValidationError(messageOf(cause))
        return false
      } finally {
        setValidatingRelease(null)
      }
    },
    [decisionChoices, rememberRun, repositoryKey, validatingRelease],
  )

  /**
   * Validate every release that has a source chosen, one after another.
   *
   * **Sequential, and it clones nothing.** Recovery already happened; this is
   * the second half of the work and the expensive half is the model calls, so
   * running them in parallel would hit the provider's per-minute limit and
   * return rate-limit refusals that look like model failures. One at a time
   * also means the pipeline can say which release it is on.
   *
   * A release with no choice is **skipped rather than defaulted**. Validating
   * it against a mode picked by a constant would report it as judged against
   * a source nobody chose, and the row says what it is waiting for instead.
   */
  const validateAllReleases = useCallback(async () => {
    if (validatingRelease) return

    setValidationError(null)

    for (const release of releases) {
      const choice = decisionChoices[release]
      if (!choice) continue

      setValidatingRelease(release)

      try {
        rememberRun(
          await runValidation({
            repository_id: repositoryKey,
            release_id: release,
            decision_mode: choice.mode,
            adr_repository_id: choice.adrRepositoryId,
          }),
        )
      } catch (cause) {
        // Named with the release it belongs to, and the loop stops: the rest
        // of the stack would fail the same way, and a wall of identical
        // messages buries the one that says why.
        setValidationError(`${release}: ${messageOf(cause)}`)
        break
      }
    }

    setValidatingRelease(null)
  }, [decisionChoices, releases, rememberRun, repositoryKey, validatingRelease])

  /**
   * Recover every configured snapshot.
   *
   * Returns whether the stack is ready to be judged, so the screen that
   * started it can send somebody to choose what it is judged against. It
   * returns the answer rather than navigating, because a context that routes
   * is a context two screens cannot both use.
   */
  const startPipeline = useCallback(async () => {
    if (isPipelineRunning || configurations.length === 0) return false

    setIsPipelineRunning(true)
    setPipelineError(null)
    setPipelineSnapshots([])
    setPipelinePhase('recovering')

    try {
      const outcome = await runPipeline(configurations, {
        onPhase: setPipelinePhase,
        onChange: setPipelineSnapshots,
      })

      if (outcome.blockedAt === 'recovery') {
        const failed = outcome.snapshots.filter(
          (snapshot) => snapshot.phase === 'failed',
        ).length

        setPipelineError(
          `${failed} of ${outcome.snapshots.length} snapshots did not recover, so the stack cannot be judged. A release validated against a partial stack would read like a clean run.`,
        )

        return false
      }

      return true
    } finally {
      setIsPipelineRunning(false)
      // The clones and their snapshots exist now, so the header's
      // repository list and the release lists must both see them.
      reloadRepositories()
      reloadSnapshots()
    }
  }, [configurations, isPipelineRunning, reloadRepositories, reloadSnapshots])

  const addConfiguration = useCallback(
    async (input: RepositoryConfigurationInput) => {
      const saved = await saveConfiguration(input)
      reloadConfigurations()
      return saved
    },
    [reloadConfigurations],
  )

  const removeConfiguration = useCallback(
    async (configurationId: string) => {
      await deleteConfiguration(configurationId)
      reloadConfigurations()
    },
    [reloadConfigurations],
  )

  const reload = useCallback(() => {
    reloadRepositories()
    reloadSnapshots()
    reloadConfigurations()
  }, [reloadRepositories, reloadSnapshots, reloadConfigurations])

  const value = useMemo<Workspace>(
    () => ({
      repositories,
      repositoryOptions,
      repository,
      repositoryKey,
      snapshots,
      releases,
      isLoading:
        repositoriesRequest.isLoading ||
        snapshotsRequest.isLoading ||
        configurationsRequest.isLoading,
      error: repositoriesRequest.error,
      configurations,
      configurationsError: configurationsRequest.error,
      isLoadingConfigurations: configurationsRequest.isLoading,
      addConfiguration,
      removeConfiguration,
      reloadConfigurations,
      pipelinePhase,
      pipelineSnapshots,
      isPipelineRunning,
      pipelineError,
      startPipeline,
      clearPipeline: () => {
        setPipelineSnapshots([])
        setPipelinePhase('idle')
        setPipelineError(null)
      },
      runs,
      rememberRun,
      focusedRelease,
      focusRelease,
      decisionChoices,
      chooseDecision,
      chooseDecisionForAll,
      validatingRelease,
      validateRelease,
      validateAllReleases,
      validationError,
      selectRepository: setSelectedKey,
      reload,
    }),
    [
      repositories,
      repositoryOptions,
      repository,
      repositoryKey,
      snapshots,
      releases,
      repositoriesRequest.isLoading,
      repositoriesRequest.error,
      snapshotsRequest.isLoading,
      configurationsRequest.isLoading,
      configurationsRequest.error,
      configurations,
      addConfiguration,
      removeConfiguration,
      reloadConfigurations,
      pipelinePhase,
      pipelineSnapshots,
      isPipelineRunning,
      pipelineError,
      startPipeline,
      runs,
      rememberRun,
      focusedRelease,
      focusRelease,
      decisionChoices,
      chooseDecision,
      chooseDecisionForAll,
      validatingRelease,
      validateRelease,
      validateAllReleases,
      validationError,
      reload,
    ],
  )

  return <WorkspaceContext value={value}>{children}</WorkspaceContext>
}
