/**
 * The workspace provider.
 *
 * Description:
 *   Loads the configured snapshots and the ingested repositories, then the
 *   releases recovery analysed for whichever repository is selected, and
 *   holds the pipeline run started over the configured snapshots.
 *
 *   **Releases come from what was analysed, not from what was typed.** A
 *   release exists here once recovery has stored an architecture for it,
 *   which is also the only state in which anything after it can run. That
 *   removes the failure a person hits first: asking to validate a release
 *   nothing has recovered.
 *
 *   **Configuring and running are different things.** A configuration is a
 *   row in a list; the pipeline is the only thing that clones, recovers and
 *   validates, and it does so in an order the person can see. Nothing here
 *   clones as a side effect of saving.
 *
 *   The selection is held in memory and not in the URL. A deep link to one
 *   release is worth having and is not worth building before there is a
 *   second person to send one to; the shape here does not prevent it.
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
  type DecisionMode,
  type RepositoryConfigurationInput,
  type ValidationRun,
} from '../lib/api'
import { useRequest } from '../lib/useRequest'
import { WorkspaceContext, type Workspace } from './context'
import { runPipeline, type PipelinePhase, type SnapshotRun } from './pipeline'

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedRelease, setSelectedRelease] = useState<string | null>(null)
  const [decisionMode, setDecisionMode] = useState<DecisionMode | null>(null)
  const [run, setRun] = useState<ValidationRun | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)

  const [pipelinePhase, setPipelinePhase] = useState<PipelinePhase>('idle')
  const [pipelineSnapshots, setPipelineSnapshots] = useState<SnapshotRun[]>([])
  const [pipelineError, setPipelineError] = useState<string | null>(null)
  const [isPipelineRunning, setIsPipelineRunning] = useState(false)

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

  // Falling back to the first is a convenience, not a guess: with one
  // repository there is nothing to choose between, and with none every screen
  // says so rather than showing an empty frame.
  const repository =
    repositories.find((item) => item.id === selectedId) ?? repositories[0] ?? null

  // Recovery keeps two ids: the clone's, and the repository's own, which is
  // what architecture is stored under. Resolving it once here means no screen
  // has to know the difference.
  const repositoryKey = repository?.repository_id ?? repository?.id ?? ''

  const snapshots = useRequest(
    (options) => listSnapshots(repositoryKey, options),
    [repositoryKey],
    Boolean(repositoryKey),
  )

  const reloadRepositories = repositoriesRequest.reload
  const reloadSnapshots = snapshots.reload
  const reloadConfigurations = configurationsRequest.reload

  const releases = useMemo(
    () => (snapshots.data ?? []).map((item) => item.release_id),
    [snapshots.data],
  )

  const release =
    selectedRelease && releases.includes(selectedRelease)
      ? selectedRelease
      : (releases[releases.length - 1] ?? null)

  // The release was analysed at one commit; a clone here is at another. Only
  // a tree at the same commit can be read for the configuration a run is
  // judged against, so the two are compared rather than assumed to match.
  const analysedAt = (snapshots.data ?? []).find(
    (item) => item.release_id === release,
  )?.commit_sha
  const hasCheckout = Boolean(
    analysedAt && repositories.some((item) => item.commit === analysedAt),
  )

  const startRun = useCallback(
    async (mode: DecisionMode, adrRepositoryId?: string) => {
      if (!repository || !release) return false

      setIsRunning(true)
      setRunError(null)
      setRun(null)
      setDecisionMode(mode)

      try {
        setRun(
          await runValidation({
            // The repository's own identity, because that is what the graph
            // store keys architecture under - a release-aware clone's id
            // differs from it.
            repository_id: repositoryKey,
            release_id: release,
            decision_mode: mode,
            adr_repository_id: adrRepositoryId || null,
          }),
        )
        return true
      } catch (cause) {
        // The backend names the input that is missing and the release it is
        // missing for. A message written here would throw that away.
        setRunError(messageOf(cause))
        return false
      } finally {
        setIsRunning(false)
      }
    },
    [repository, repositoryKey, release],
  )

  const startPipeline = useCallback(
    async (mode: DecisionMode, adrRepositoryId?: string) => {
      if (isPipelineRunning || configurations.length === 0) return

      setIsPipelineRunning(true)
      setPipelineError(null)
      setPipelineSnapshots([])
      setPipelinePhase('recovering')
      setDecisionMode(mode)

      try {
        const outcome = await runPipeline(configurations, {
          decisionMode: mode,
          adrRepositoryId,
          onPhase: setPipelinePhase,
          onChange: setPipelineSnapshots,
          onValidated: (snapshot) => {
            // Each validated snapshot becomes what the result screens show,
            // so the run ends with the last release it produced selected.
            if (snapshot.repositoryId) setSelectedId(snapshot.repositoryId)
            setSelectedRelease(snapshot.configuration.release_tag)
            setRun(snapshot.run)
            setRunError(null)
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
        // The clones and their snapshots exist now, so the header's release
        // list and the repositories screen must both see them.
        reloadRepositories()
        reloadSnapshots()
      }
    },
    [
      configurations,
      isPipelineRunning,
      reloadRepositories,
      reloadSnapshots,
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
      repository,
      repositoryKey,
      releases,
      release,
      isRecovered: releases.length > 0 && release !== null,
      hasCheckout,
      isLoading:
        repositoriesRequest.isLoading ||
        snapshots.isLoading ||
        configurationsRequest.isLoading,
      error: repositoriesRequest.error,
      run,
      decisionMode,
      isRunning,
      runError,
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
      select: (repositoryId) => {
        setSelectedId(repositoryId)
        setSelectedRelease(null)
        setRun(null)
      },
      selectRelease: (releaseId) => {
        setSelectedRelease(releaseId)
        setRun(null)
      },
      chooseDecisionMode: setDecisionMode,
      startRun,
      recordRun: setRun,
      clearRun: () => {
        setRun(null)
        setRunError(null)
      },
      reload,
    }),
    [
      repositories,
      repository,
      repositoryKey,
      releases,
      release,
      hasCheckout,
      repositoriesRequest.isLoading,
      repositoriesRequest.error,
      snapshots.isLoading,
      configurationsRequest.isLoading,
      configurationsRequest.error,
      run,
      decisionMode,
      isRunning,
      runError,
      configurations,
      addConfiguration,
      removeConfiguration,
      reloadConfigurations,
      pipelinePhase,
      pipelineSnapshots,
      isPipelineRunning,
      pipelineError,
      startPipeline,
      startRun,
      reload,
    ],
  )

  return <WorkspaceContext value={value}>{children}</WorkspaceContext>
}
