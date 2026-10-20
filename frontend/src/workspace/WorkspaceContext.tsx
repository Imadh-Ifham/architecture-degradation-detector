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
  removeConfiguration as deleteConfiguration,
  saveConfiguration,
  type DecisionMode,
  type RepositoryConfigurationInput,
  type SnapshotSummary,
  type ValidationRun,
} from '../lib/api'
import { useRequest } from '../lib/useRequest'
import {
  WorkspaceContext,
  runKey,
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

  const startPipeline = useCallback(
    async (mode: DecisionMode, adrRepositoryId?: string) => {
      if (isPipelineRunning || configurations.length === 0) return

      setIsPipelineRunning(true)
      setPipelineError(null)
      setPipelineSnapshots([])
      setPipelinePhase('recovering')

      try {
        const outcome = await runPipeline(configurations, {
          decisionMode: mode,
          adrRepositoryId,
          onPhase: setPipelinePhase,
          onChange: setPipelineSnapshots,
          onValidated: (snapshot) => {
            if (snapshot.run) rememberRun(snapshot.run)
          },
        })

        if (outcome.blockedAt === 'recovery') {
          const failed = outcome.snapshots.filter(
            (snapshot) => snapshot.phase === 'failed',
          ).length

          setPipelineError(
            `${failed} of ${outcome.snapshots.length} snapshots did not recover, so validation did not start. A release validated against a partial stack would read like a clean run.`,
          )
        }
      } finally {
        setIsPipelineRunning(false)
        // The clones and their snapshots exist now, so the header's
        // repository list and the release lists must both see them.
        reloadRepositories()
        reloadSnapshots()
      }
    },
    [
      configurations,
      isPipelineRunning,
      reloadRepositories,
      reloadSnapshots,
      rememberRun,
    ],
  )

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
      reload,
    ],
  )

  return <WorkspaceContext value={value}>{children}</WorkspaceContext>
}
