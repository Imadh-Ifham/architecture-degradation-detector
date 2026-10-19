/**
 * The workspace provider.
 *
 * Description:
 *   Loads the ingested repositories, then the releases recovery analysed for
 *   whichever is selected, and holds the run started against one of them.
 *
 *   **Releases come from what was analysed, not from what was typed.** A
 *   release exists here once recovery has stored an architecture for it,
 *   which is also the only state in which anything after it can run. That
 *   removes the failure a person hits first: asking to validate a release
 *   nothing has recovered.
 *
 *   The selection is held in memory and not in the URL. A deep link to one
 *   release is worth having and is not worth building before there is a
 *   second person to send one to; the shape here does not prevent it.
 */

import { useCallback, useMemo, useState, type ReactNode } from 'react'
import {
  listRepositories,
  listSnapshots,
  messageOf,
  runValidation,
  type DecisionMode,
  type ValidationRun,
} from '../lib/api'
import { useRequest } from '../lib/useRequest'
import { WorkspaceContext, type Workspace } from './context'

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedRelease, setSelectedRelease] = useState<string | null>(null)
  const [decisionMode, setDecisionMode] = useState<DecisionMode | null>(null)
  const [run, setRun] = useState<ValidationRun | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)

  const repositoriesRequest = useRequest((options) => listRepositories(options), [])

  const repositories = useMemo(
    () => repositoriesRequest.data ?? [],
    [repositoriesRequest.data],
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
            repository_id: repository.id,
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
    [repository, release],
  )

  const reloadRepositories = repositoriesRequest.reload
  const reloadSnapshots = snapshots.reload

  const reload = useCallback(() => {
    reloadRepositories()
    reloadSnapshots()
  }, [reloadRepositories, reloadSnapshots])

  const value = useMemo<Workspace>(
    () => ({
      repositories,
      repository,
      repositoryKey,
      releases,
      release,
      isRecovered: releases.length > 0 && release !== null,
      hasCheckout,
      isLoading: repositoriesRequest.isLoading || snapshots.isLoading,
      error: repositoriesRequest.error,
      run,
      decisionMode,
      isRunning,
      runError,
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
      run,
      decisionMode,
      isRunning,
      runError,
      startRun,
      reload,
    ],
  )

  return <WorkspaceContext value={value}>{children}</WorkspaceContext>
}
