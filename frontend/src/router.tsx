/**
 * The routes.
 *
 * Description:
 *   One route per page in the sidebar, in the same order. A screen that is
 *   not written yet still has its route, pointing at a placeholder that says
 *   what belongs there - so the name, the path and the position are decided
 *   once rather than reinvented by whoever builds it.
 *
 *   To take one over: replace its element here with your own page component
 *   and delete the placeholder. Nothing else changes.
 */

import { createBrowserRouter } from 'react-router'
import AppLayout from './layouts/AppLayout'
import ArchitecturePage from './features/architecture/ArchitecturePage'
import DecisionsPage from './features/decisions/DecisionsPage'
import PipelinePage from './features/pipeline/PipelinePage'
import RepositoriesPage from './features/repositories/RepositoriesPage'
import NotFound from './pages/NotFound'
import {
  DriftPage,
  FindingsPage,
  PrioritiesPage,
} from './features/reserved/reservedPages'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <PipelinePage /> },
      { path: 'repositories', element: <RepositoriesPage /> },
      { path: 'architecture', element: <ArchitecturePage /> },
      { path: 'decisions', element: <DecisionsPage /> },
      { path: 'findings', element: <FindingsPage /> },
      { path: 'drift', element: <DriftPage /> },
      { path: 'priorities', element: <PrioritiesPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
])
