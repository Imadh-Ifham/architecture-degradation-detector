/**
 * Reading the current workspace.
 *
 * Description:
 *   Its own module so the provider file exports a component and nothing else,
 *   which is what keeps hot reloading working while a screen is being built.
 */

import { useContext } from 'react'
import { WorkspaceContext, type Workspace } from './context'

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext)

  if (!value) {
    throw new Error('useWorkspace must be used inside a WorkspaceProvider')
  }

  return value
}
