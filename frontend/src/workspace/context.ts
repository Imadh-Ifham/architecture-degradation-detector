/**
 * The workspace selection, as a type and a context.
 *
 * Description:
 *   Separate from the provider so that file exports one component and nothing
 *   else, which is what keeps hot reloading working while a screen is being
 *   built.
 */

import { createContext } from 'react'
import type { IngestedRepository } from '../lib/api'

export interface Workspace {
  repositories: IngestedRepository[]
  repository: IngestedRepository | null
  release: string | null
  isLoading: boolean
  error: string | null
  select: (repositoryId: string) => void
  selectRelease: (releaseId: string) => void
  reload: () => void
}

export const WorkspaceContext = createContext<Workspace | null>(null)
