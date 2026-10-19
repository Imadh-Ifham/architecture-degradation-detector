import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'
import { router } from './router.tsx'
import { WorkspaceProvider } from './workspace/WorkspaceContext.tsx'
import './index.css'

// The workspace sits above the router: which repository and release are being
// looked at is one answer for the whole application, not one per screen.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <WorkspaceProvider>
      <RouterProvider router={router} />
    </WorkspaceProvider>
  </StrictMode>,
)
