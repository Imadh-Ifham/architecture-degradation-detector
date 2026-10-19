/**
 * The application shell.
 *
 * Description:
 *   A fixed rail of pages on the left, a thin instrument bar across the top,
 *   and one work surface. Every screen renders into the surface and nothing
 *   else moves, so a person always knows where they are and what else there
 *   is.
 *
 *   The content column is width-capped and generously padded. Dense is not
 *   the same as informative: a screen with room around its figures is read,
 *   and one without it is skimmed.
 */

import { NavLink, Outlet } from 'react-router'
import { PAGES } from './navigation'
import ConnectionBadge from '../components/ConnectionBadge'
import { useWorkspace } from '../workspace/useWorkspace'

export default function AppLayout() {
  const { repository, release } = useWorkspace()

  return (
    <div className="min-h-svh lg:grid lg:grid-cols-[248px_minmax(0,1fr)]">
      <Sidebar />

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex flex-wrap items-center gap-5 border-b border-line bg-panel px-8 py-3.5">
          <Context label="repository" value={repository?.url.split('/').pop() ?? 'none selected'} />
          <span className="text-ink-4">/</span>
          <Context label="release" value={release ?? 'none selected'} />
          <div className="grow" />
          <ConnectionBadge />
        </header>

        <main className="min-w-0 grow px-8 py-10 lg:px-12 lg:py-14">
          <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-10">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}

function Context({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-2 text-sm">
      <span className="text-xs text-ink-4">{label}</span>
      <span className="font-mono text-ink">{value}</span>
    </span>
  )
}

function Sidebar() {
  return (
    <nav
      aria-label="Sections"
      className="border-line bg-panel lg:sticky lg:top-0 lg:h-svh lg:self-start lg:border-r"
    >
      <div className="flex items-center gap-2.5 border-b border-line px-6 py-4">
        <Mark />
        <span className="text-sm font-semibold tracking-tight">Plumbline</span>
      </div>

      <div className="flex gap-1 overflow-x-auto px-3 py-3 lg:flex-col lg:overflow-visible lg:py-5">
        {PAGES.map((page) => (
          <NavLink
            key={page.path}
            to={page.path}
            end={page.path === '/'}
            title={page.summary}
            className={({ isActive }) =>
              `flex shrink-0 items-center gap-2.5 rounded-control px-3.5 py-2.5 text-sm whitespace-nowrap transition ${
                isActive
                  ? 'bg-raised text-ink'
                  : 'text-ink-2 hover:bg-raised/60 hover:text-ink'
              }`
            }
          >
            <span>{page.label}</span>
            {page.state === 'reserved' && (
              <span className="ml-auto font-mono text-[10px] text-ink-4">soon</span>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}

/** A plumb bob: the instrument for checking a thing is true. */
function Mark() {
  return (
    <svg viewBox="0 0 20 20" className="size-[18px]" aria-hidden="true">
      <line x1="10" y1="2" x2="10" y2="12" stroke="currentColor" strokeWidth="1.4" />
      <path d="M6 12 L10 18 L14 12 Z" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="10" cy="2.2" r="1.7" fill="currentColor" />
    </svg>
  )
}
