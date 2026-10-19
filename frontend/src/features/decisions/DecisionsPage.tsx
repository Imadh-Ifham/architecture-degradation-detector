/**
 * Decisions screen.
 *
 * Description:
 *   The one choice the analysis cannot make for a person: what this release
 *   is judged against. Three sources, each showing what it would supply
 *   **before** it is chosen, and the choice starts the run.
 *
 *   **The empty source is the interesting one.** Most repositories keep no
 *   written decision records at all, and a screen that greys that row out
 *   hides the finding. It is shown with its count, because running against
 *   nothing would report "nothing contradicts the architecture" — which is
 *   indistinguishable from a clean result on a healthy system.
 *
 *   **Every number is what the backend would actually find**, asked for
 *   before anything is run and without writing anything.
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
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
import { readDecisionSources, type DecisionMode, type ModeAvailability } from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { useWorkspace } from '../../workspace/useWorkspace'

const MODE: Record<DecisionMode, { title: string; detail: string }> = {
  repo_adr: {
    title: 'Decision records in this repository',
    detail: 'Written decisions kept alongside the code.',
  },
  external_adr: {
    title: 'Decision records in a repository you name',
    detail: 'For teams that keep their decisions outside the codebase.',
  },
  combined: {
    title: 'Both, plus rules recovered from configuration',
    detail:
      'The only option that produces a result on a repository holding no written decisions.',
  },
}

export default function DecisionsPage() {
  const navigate = useNavigate()
  const {
    repository,
    release,
    isRecovered,
    hasCheckout,
    decisionMode,
    chooseDecisionMode,
    startRun,
    isRunning,
    runError,
  } = useWorkspace()

  const [adrRepository, setAdrRepository] = useState('')

  const sources = useRequest(
    (options) => readDecisionSources(repository?.id ?? '', release ?? '', options),
    [repository?.id, release],
    Boolean(repository && release),
  )

  // The backend already knows which source has the most to offer. Starting on
  // its answer means the common case is one button rather than a decision.
  const recommended = sources.data?.recommended ?? null
  useEffect(() => {
    if (recommended && !decisionMode) chooseDecisionMode(recommended)
  }, [recommended, decisionMode, chooseDecisionMode])

  if (!repository || !isRecovered) {
    return (
      <>
        <PageHeading eyebrow="intent" title="Decisions" />
        <Card>
          <EmptyState
            title={repository ? 'No architecture for this release yet' : 'No system selected'}
            body="Decisions are read for one release of one repository, so there has to be a recovered release first."
            action={
              <Link to="/repositories">
                <Button variant="primary">
                  {repository ? 'Add a release' : 'Add a repository'}
                </Button>
              </Link>
            }
          />
        </Card>
      </>
    )
  }

  const chosen = decisionMode ?? recommended
  const needsRepository = chosen === 'external_adr' && !adrRepository.trim()

  const run = async () => {
    if (!chosen) return

    const started = await startRun(chosen, adrRepository.trim())
    if (started) navigate('/')
  }

  return (
    <>
      <PageHeading
        eyebrow="intent"
        title="Decisions"
        description={`What ${release} is judged against. Every source says what it would supply before it is chosen, so an empty one is visible rather than discovered.`}
        action={
          sources.data?.recommended ? (
            <Pill tone="ok">recommended: {MODE[sources.data.recommended].title.split(',')[0]}</Pill>
          ) : undefined
        }
      />

      {!hasCheckout && release && (
        <Card>
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <Pill tone="warn">no working copy for this release</Pill>
            </div>
            <p className="max-w-prose text-sm leading-relaxed text-ink-2">
              {release} was analysed from a revision that is not checked out
              here, so its configuration cannot be read. The run will still
              finish, and it will report every dependency as ungoverned —
              which looks exactly like a repository that records no decisions.
            </p>
            <div>
              <Link to="/repositories">
                <Button>Add {release} as a release</Button>
              </Link>
            </div>
          </div>
        </Card>
      )}

      {sources.error && <ErrorState message={sources.error} onRetry={sources.reload} />}
      {sources.isLoading && <Spinner label="asking what each source holds" />}

      {sources.data && (
        <>
          <div className="grid gap-7 lg:grid-cols-3">
            {sources.data.modes.map((mode) => (
              <Source
                key={mode.mode}
                mode={mode}
                isChosen={mode.mode === chosen}
                isRecommended={mode.mode === sources.data?.recommended}
                onChoose={() => chooseDecisionMode(mode.mode)}
              />
            ))}
          </div>

          {chosen === 'external_adr' && (
            <Card title="The decision repository">
              <div className="flex flex-col gap-6">
                <p className="max-w-prose text-sm leading-relaxed text-ink-3">
                  Add it on the repositories screen first — it is cloned and
                  scanned like any other — then name it here by the id it was
                  given.
                </p>
                <Field label="Repository id">
                  <input
                    value={adrRepository}
                    onChange={(event) => setAdrRepository(event.target.value)}
                    placeholder="the id shown on the repositories screen"
                    className={inputClass}
                  />
                </Field>
              </div>
            </Card>
          )}

          {runError && <ErrorState message={runError} />}

          <Card>
            <div className="flex flex-wrap items-center justify-between gap-6">
              <div className="flex flex-col gap-1.5">
                <span className="text-sm text-ink">
                  Validate {release} against{' '}
                  {chosen ? MODE[chosen].title.toLowerCase() : 'nothing selected'}
                </span>
                <span className="text-xs text-ink-4">
                  The run takes a few seconds, then the pipeline replays what each stage did.
                </span>
              </div>

              <div className="flex items-center gap-5">
                {isRunning && <Spinner label="running" />}
                <Button
                  variant="primary"
                  disabled={!chosen || isRunning || needsRepository}
                  onClick={run}
                >
                  {isRunning ? 'Running…' : `Validate ${release}`}
                </Button>
              </div>
            </div>
          </Card>
        </>
      )}
    </>
  )
}

function Source({
  mode,
  isChosen,
  isRecommended,
  onChoose,
}: {
  mode: ModeAvailability
  isChosen: boolean
  isRecommended: boolean
  onChoose: () => void
}) {
  const empty = mode.records === 0
  const breakdown = Object.entries(mode.by_source)

  return (
    <button
      type="button"
      onClick={onChoose}
      className={`rounded-card border p-7 text-left transition ${
        isChosen
          ? 'border-ai bg-ai-wash'
          : 'border-line bg-panel hover:border-line-strong'
      }`}
    >
      <div className="flex flex-col gap-5">
        <div className="flex items-start justify-between gap-4">
          <span className="text-sm leading-snug font-medium">{MODE[mode.mode].title}</span>
          <span
            className={`mt-1 size-3.5 shrink-0 rounded-full border ${
              isChosen ? 'border-ai bg-ai shadow-[inset_0_0_0_3px_var(--color-field)]' : 'border-ink-4'
            }`}
          />
        </div>

        <div className="flex items-baseline gap-3">
          <span className={`font-mono text-4xl leading-none ${empty ? 'text-ink-4' : 'text-ink'}`}>
            {mode.records}
          </span>
          <span className="text-xs text-ink-3">
            {mode.records === 1 ? 'decision' : 'decisions'}
          </span>
        </div>

        <div className="flex flex-wrap gap-2">
          {isRecommended && <Pill tone="ok">most to offer</Pill>}
          {!mode.ran && <Pill tone="warn">not configured</Pill>}
        </div>

        <p className="text-xs leading-relaxed text-ink-3">
          {mode.reason ?? MODE[mode.mode].detail}
        </p>

        {breakdown.length > 0 && (
          <ul className="flex flex-col gap-1.5 border-t border-line pt-4">
            {breakdown.map(([source, count]) => (
              <li key={source} className="font-mono text-xs text-ink-2">
                <span className="text-ink">{count}</span> {source.replace(/_/g, ' ')}
              </li>
            ))}
          </ul>
        )}
      </div>
    </button>
  )
}
