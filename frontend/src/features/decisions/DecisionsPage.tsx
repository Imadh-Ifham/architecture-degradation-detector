/**
 * Decisions screen.
 *
 * Description:
 *   What the architecture is judged against, and how much of it there is.
 *   Three sources, each showing what it would supply **before** it is chosen:
 *   decision records kept in the repository, records kept in a repository
 *   somebody names, and rules recovered from the repository's own
 *   configuration.
 *
 *   **The empty source is the interesting one.** Most repositories keep no
 *   written decision records at all, and a screen that greys that row out
 *   hides the finding. It is shown with its count, because a validation run
 *   against nothing would report "nothing contradicts the architecture",
 *   which is indistinguishable from a clean result on a healthy system.
 */

import { useState } from 'react'
import { Link } from 'react-router'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  PageHeading,
  Pill,
  Spinner,
  inputClass,
} from '../../components/ui'
import { readDecisionSources, type ModeAvailability } from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { useWorkspace } from '../../workspace/useWorkspace'

const MODE_LABEL: Record<string, string> = {
  repo_adr: 'Decision records in this repository',
  external_adr: 'Decision records in a repository you name',
  combined: 'Both, plus rules recovered from this release’s configuration',
}

export default function DecisionsPage() {
  const { repository, release } = useWorkspace()
  const [decisionRepository, setDecisionRepository] = useState('')

  const sources = useRequest(
    (options) => readDecisionSources(repository?.id ?? '', release ?? '', options),
    [repository?.id, release],
    Boolean(repository && release),
  )

  if (!repository) {
    return (
      <>
        <PageHeading eyebrow="intent" title="Decisions" />
        <Card>
          <EmptyState
            title="No system selected"
            body="Decisions are read from a repository, so one has to be here first."
            action={
              <Link to="/repositories">
                <Button>Add a repository</Button>
              </Link>
            }
          />
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeading
        eyebrow="intent"
        title="Decisions"
        description="What the architecture is measured against. Every source says what it would supply before it is chosen, so an empty one is visible rather than discovered."
        action={
          sources.data?.recommended ? (
            <Pill tone="ok">recommended: {MODE_LABEL[sources.data.recommended]?.split(',')[0]}</Pill>
          ) : undefined
        }
      />

      {sources.error && <ErrorState message={sources.error} onRetry={sources.reload} />}
      {sources.isLoading && <Spinner label="asking what each source holds" />}

      {sources.data && (
        <div className="grid gap-7 lg:grid-cols-3">
          {sources.data.modes.map((mode) => (
            <Source key={mode.mode} mode={mode} />
          ))}
        </div>
      )}

      <Card title="A separate decision repository">
        <div className="flex flex-col gap-7">
          <p className="max-w-prose text-sm leading-relaxed text-ink-3">
            Teams that keep their architecture decisions outside the codebase can
            point at that repository here. It is cloned and scanned the same way,
            and its records are read alongside the rules recovered from
            configuration.
          </p>

          <Field
            label="Repository URL"
            hint="Added through the repositories screen, then named on the run."
          >
            <input
              value={decisionRepository}
              onChange={(event) => setDecisionRepository(event.target.value)}
              placeholder="https://github.com/organisation/architecture-decisions"
              className={inputClass}
            />
          </Field>

          <div className="flex items-center gap-4">
            <Link to="/repositories">
              <Button>Add it as a repository</Button>
            </Link>
            <span className="text-xs text-ink-4">
              Decision repositories are ingested like any other, then selected on the run.
            </span>
          </div>
        </div>
      </Card>
    </>
  )
}

function Source({ mode }: { mode: ModeAvailability }) {
  const empty = mode.records === 0
  const breakdown = Object.entries(mode.by_source)

  return (
    <Card
      className={empty ? '' : 'border-line-strong'}
      title={<span className="text-sm leading-snug">{MODE_LABEL[mode.mode] ?? mode.mode}</span>}
    >
      <div className="flex flex-col gap-5">
        <div className="flex items-baseline gap-3">
          <span
            className={`font-mono text-4xl leading-none ${empty ? 'text-ink-4' : 'text-ink'}`}
          >
            {mode.records}
          </span>
          <span className="text-xs text-ink-3">
            {mode.records === 1 ? 'decision' : 'decisions'}
          </span>
        </div>

        {!mode.ran && <Pill tone="warn">not configured</Pill>}

        {mode.reason && (
          <p className="text-xs leading-relaxed text-ink-3">{mode.reason}</p>
        )}

        {breakdown.length > 0 && (
          <ul className="flex flex-col gap-1.5">
            {breakdown.map(([source, count]) => (
              <li key={source} className="font-mono text-xs text-ink-2">
                <span className="text-ink">{count}</span> {source.replace(/_/g, ' ')}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}
