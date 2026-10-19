/**
 * What the whole application is currently looking at.
 *
 * Description:
 *   One repository and one release, chosen once and read everywhere. Without
 *   it every screen grows its own repository picker, they disagree, and a
 *   person running a validation has to say which repository three times.
 *
 *   The selection is held in memory and not in the URL. A deep link to a
 *   specific release is worth having and is not worth building before there
 *   is a second person to send one to - the shape here does not prevent it.
 */

import { useMemo, useState, type ReactNode } from 'react'
import { listRepositories } from '../lib/api'
import { WorkspaceContext, type Workspace } from './context'
import { useRequest } from '../lib/useRequest'

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedRelease, setSelectedRelease] = useState<string | null>(null)

  const { data, isLoading, error, reload } = useRequest(
    (options) => listRepositories(options),
    [],
  )

  const repositories = useMemo(() => data ?? [], [data])

  const value = useMemo<Workspace>(() => {
    // Falling back to the first is a convenience, not a guess: with one
    // repository ingested there is nothing to choose between, and with none
    // every screen says so rather than showing an empty frame.
    const repository =
      repositories.find((item) => item.id === selectedId) ?? repositories[0] ?? null

    return {
      repositories,
      repository,
      release: selectedRelease ?? repository?.release_tag ?? repository?.branch ?? null,
      isLoading,
      error,
      select: (repositoryId) => {
        setSelectedId(repositoryId)
        setSelectedRelease(null)
      },
      selectRelease: setSelectedRelease,
      reload,
    }
  }, [repositories, selectedId, selectedRelease, isLoading, error, reload])

  return <WorkspaceContext value={value}>{children}</WorkspaceContext>
}
