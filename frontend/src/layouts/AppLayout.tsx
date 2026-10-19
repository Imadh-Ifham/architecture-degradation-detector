/**
 * The application shell.
 *
 * Description:
 *   A rail of pages on the left, grouped by what somebody is doing, a thin
 *   instrument bar across the top saying what is being looked at, and one
 *   work surface. Every screen renders into the surface and nothing else
 *   moves.
 *
 *   The rail carries the state of the work as well as its names: whether a
 *   repository is selected, whether its architecture has been recovered, and
 *   whether this release has been validated. Those three answers decide what
 *   every screen can show, so a person should not have to open three screens
 *   to find them.
 *
 *   The content column is width-capped and generously padded. Dense is not
 *   the same as informative: a screen with room around its figures is read,
 *   and one without it is skimmed.
 */

import { NavLink, Outlet } from 'react-router'
import { PAGES, PAGE_GROUPS } from './navigation'
import ConnectionBadge from '../components/ConnectionBadge'
import { useWorkspace } from '../workspace/useWorkspace'

export default function AppLayout() {
  const { repository, release, releases, selectRelease } = useWorkspace()

  return (
    <div className="min-h-svh lg:grid lg:grid-cols-[264px_minmax(0,1fr)]">
      <Sidebar />

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex flex-wrap items-center gap-6 border-b border-line bg-panel px-8 py-4">
          <span className="flex items-baseline gap-2.5 text-sm">
            <span className="text-xs text-ink-4">repository</span>
            <span className="font-mono text-ink">
              {repository ? shortName(repository.url) : 'none yet'}
            </span>
          </span>

          <span className="h-4 w-px bg-line" />

          <span className="flex items-center gap-2.5 text-sm">
            <span className="text-xs text-ink-4">release</span>
            {releases.length > 0 ? (
              <select
                value={release ?? ''}
                onChange={(event) => selectRelease(event.target.value)}
                aria-label="Release"
                className="rounded-control border border-line-strong bg-raised px-2.5 py-1 font-mono text-sm text-ink focus:border-ai focus:outline-none"
              >
                {releases.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            ) : (
              <span className="font-mono text-ink-4">not recovered yet</span>
            )}
          </span>

          <div className="grow" />
          <ConnectionBadge />
        </header>

        <main className="min-w-0 grow px-8 py-10 lg:px-14 lg:py-16">
          <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-12">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}

function Sidebar() {
  const { repository, releases, run, isRecovered } = useWorkspace()

  return (
    <nav
      aria-label="Sections"
      className="flex flex-col border-line bg-panel lg:sticky lg:top-0 lg:h-svh lg:self-start lg:border-r"
    >
      <div className="flex items-center gap-2.5 border-b border-line px-6 py-4">
        <Mark />
        <span className="text-sm font-semibold tracking-tight">Plumbline</span>
      </div>

      <div className="flex grow gap-1 overflow-x-auto px-3 py-3 lg:flex-col lg:overflow-visible lg:py-6">
        {PAGE_GROUPS.map((group) => (
          <div key={group} className="flex gap-1 lg:flex-col">
            <span className="hidden px-3.5 pt-5 pb-2 font-mono text-[10.5px] tracking-[0.16em] text-ink-4 uppercase first:pt-0 lg:block">
              {group}
            </span>

            {PAGES.filter((page) => page.group === group).map((page) => (
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
        ))}
      </div>

      {/* The three answers every screen depends on, so nobody has to go and
          find out which of them is the reason a page is empty. */}
      <div className="hidden flex-col gap-3 border-t border-line px-6 py-5 lg:flex">
        <Readiness label="repository added" met={Boolean(repository)} />
        <Readiness
          label="architecture recovered"
          met={isRecovered}
          detail={releases.length > 0 ? `${releases.length} releases` : undefined}
        />
        <Readiness
          label="release validated"
          met={Boolean(run)}
          detail={run ? `${run.model_calls} model calls` : undefined}
        />
      </div>
    </nav>
  )
}

function Readiness({
  label,
  met,
  detail,
}: {
  label: string
  met: boolean
  detail?: string
}) {
  return (
    <div className="flex items-center gap-2.5">
      <span
        className={`size-1.5 shrink-0 rounded-full ${met ? 'bg-ok' : 'bg-ink-4'}`}
      />
      <span className={`text-xs ${met ? 'text-ink-2' : 'text-ink-4'}`}>{label}</span>
      {detail && <span className="ml-auto font-mono text-[10.5px] text-ink-4">{detail}</span>}
    </div>
  )
}

/** The last segment of a clone url, which is what a person calls the system. */
function shortName(url: string): string {
  return url.replace(/\.git$/, '').split('/').filter(Boolean).pop() ?? url
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
