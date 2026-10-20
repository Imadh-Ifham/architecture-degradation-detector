/**
 * Which release one screen is looking at.
 *
 * Description:
 *   Every screen that shows a release owns the choice. The workspace holds the
 *   releases recovery analysed for the selected repository; this turns that
 *   list plus a local choice into the release the screen renders.
 *
 *   **Local on purpose.** Two screens comparing two releases is the normal
 *   case, not an edge case, so a global "current release" would make one of
 *   them wrong. What is shared is only a starting point: the release the last
 *   run was about, so a run started on one screen opens on its own result.
 *
 *   The default when nothing has run is the newest release, which is what
 *   somebody arriving at a result screen almost always means.
 */

import { useCallback, useMemo, useState } from 'react'
import type { SnapshotSummary } from '../lib/api'
import { useWorkspace } from './useWorkspace'

export interface ReleaseSelection {
  /** Every analysed release of the selected repository, oldest first. */
  snapshots: SnapshotSummary[]
  releases: string[]
  release: string | null
  snapshot: SnapshotSummary | null
  selectRelease: (releaseId: string) => void
  isLoading: boolean
  error: string | null
  reload: () => void
}

export function useReleases(): ReleaseSelection {
  const {
    snapshots,
    releases,
    focusedRelease,
    isLoading,
    error,
    reload,
  } = useWorkspace()

  const [chosen, setChosen] = useState<string | null>(null)

  // A local choice wins while it is still a release that exists; the shared
  // hint is only a starting point, never an instruction.
  const release =
    chosen && releases.includes(chosen)
      ? chosen
      : focusedRelease && releases.includes(focusedRelease)
        ? focusedRelease
        : (releases[releases.length - 1] ?? null)

  const snapshot = useMemo(
    () => snapshots.find((item) => item.release_id === release) ?? null,
    [snapshots, release],
  )

  const selectRelease = useCallback((releaseId: string) => setChosen(releaseId), [])

  return {
    snapshots,
    releases,
    release,
    snapshot,
    selectRelease,
    isLoading,
    error,
    reload,
  }
}
