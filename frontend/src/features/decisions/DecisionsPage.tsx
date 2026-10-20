/**
 * Decisions screen.
 *
 * Description:
 *   The one choice the analysis cannot make for a person, made once **per
 *   release**: what each release is judged against.
 *
 *   **A list, not a release picker.** An architect analysing ten releases of
 *   one system is deciding ten times, and a screen that shows one release at a
 *   time turns that into ten navigations with no way to see what has been
 *   decided and what has not. The list is the state of the whole stack.
 *
 *   **Per release, because a repository's history is not uniform.** A team
 *   adopts decision records partway through, so the source with something to
 *   say about `v0.9.0` is often not the one with something to say about
 *   `v2.0.0`. A single mode over the whole stack would quietly judge the early
 *   releases against a source that did not exist yet. Applying one choice to
 *   every release is offered, because it is the common case - but it is an
 *   action somebody takes, not the default.
 *
 *   **Nothing is validated here.** Choosing is this screen's job; running is
 *   the pipeline's, one release at a time, where the progress of a long stack
 *   can be watched. This screen hands over when the choosing is done.
 *
 *   **The empty source is the interesting one.** Most repositories keep no
 *   written decision records at all, and a screen that greys that row out
 *   hides the finding - so every source reports what it would supply, and a
 *   zero says which kind of zero it is.
 */

import { useState } from 'react'
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
import {
  readDecisionSources,
  type DecisionMode,
  type ModeAvailability,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { runKey, type DecisionChoice } from '../../workspace/context'
import { useWorkspace } from '../../workspace/useWorkspace'
import { MODE } from './modes'
import ProseExtraction from './ProseExtraction'
import ReleaseDecision from './ReleaseDecision'

export default function DecisionsPage() {
  const navigate = useNavigate()
  const {
    repository,
    repositoryKey,
    repositoryOptions,
    releases,
    runs,
    decisionChoices,
    chooseDecision,
    chooseDecisionForAll,
  } = useWorkspace()

  const [adrRepository, setAdrRepository] = useState('')

  const chosenCount = releases.filter((release) => decisionChoices[release]).length
  const readsANamedRepository = releases.some((release) => {
    const mode = decisionChoices[release]?.mode
    return mode === 'external_adr' || mode === 'combined'
  })

  const candidates = repositoryOptions.filter((option) => option.key !== repositoryKey)

  // One probe for the prose panel below. How much a repository documents is a
  // property of the repository rather than of a release, so the newest one
  // answers for the stack instead of fifty requests saying the same thing.
  const newest = releases[releases.length - 1] ?? null
  const probe = useRequest(
    (options) => readDecisionSources(repositoryKey, newest ?? '', options),
    [repositoryKey, newest],
    Boolean(repositoryKey && newest),
  )

  if (!repository || releases.length === 0) {
    return (
      <>
        <PageHeading eyebrow="intent" title="Decisions" />
        <Card>
          <EmptyState
            title={repository ? 'No recovered release yet' : 'No system selected'}
            body="A release has to be recovered before anything can report what it would be judged against. Adding releases and recovering them is the repositories screen."
            action={
              <Link to="/repositories">
                <Button variant="primary">Open repositories</Button>
              </Link>
            }
          />
        </Card>
      </>
    )
  }

  const applyToAll = (mode: DecisionMode) =>
    chooseDecisionForAll({ mode, adrRepositoryId: adrRepository.trim() || null })

  const choose = (release: string) => (choice: DecisionChoice) =>
    chooseDecision(release, {
      ...choice,
      adrRepositoryId: adrRepository.trim() || null,
    })

  /**
   * Naming the decision repository re-stamps every choice already made.
   *
   * The choices carry the repository with them, so one picked *after* a mode
   * would leave that release pointing at nothing - and it would validate,
   * reporting that the named source supplied no records, which is a finding
   * about the repository rather than about the order somebody clicked in.
   */
  const selectDecisionRepository = (value: string) => {
    setAdrRepository(value)

    for (const [release, choice] of Object.entries(decisionChoices)) {
      chooseDecision(release, { ...choice, adrRepositoryId: value.trim() || null })
    }
  }

  const handOver = (
    <Button variant="primary" disabled={chosenCount === 0} onClick={() => navigate('/')}>
      Go to the pipeline
    </Button>
  )

  return (
    <>
      <PageHeading
        eyebrow="intent"
        title="Decisions"
        description="What each release is judged against. Every source says what it would supply before it is chosen, so an empty one is visible rather than discovered."
        action={
          <div className="flex flex-wrap items-center gap-5">
            <Pill tone={chosenCount === releases.length ? 'ok' : 'warn'}>
              {chosenCount} of {releases.length} chosen
            </Pill>
            {handOver}
          </div>
        }
      />

      <Card
        title="Apply one source to every release"
        action={
          <span className="font-mono text-xs text-ink-4">
            {releases.length} releases
          </span>
        }
      >
        <div className="flex flex-col gap-6">
          <p className="max-w-prose text-sm leading-relaxed text-ink-3">
            {/* Offered because it is the common case, and not the default
                because a stack whose history is not uniform is the case this
                screen exists for. */}
            The usual case is one source for the whole stack. Where a team
            adopted decision records partway through its history, decide the
            affected releases individually below.
          </p>

          <div className="flex flex-wrap gap-3">
            {(Object.keys(MODE) as DecisionMode[]).map((mode) => (
              <Button key={mode} onClick={() => applyToAll(mode)}>
                {MODE[mode].short}
              </Button>
            ))}
          </div>
        </div>
      </Card>

      {readsANamedRepository && (
        <Card title="The decision repository">
          <div className="flex flex-col gap-6">
            <p className="max-w-prose text-sm leading-relaxed text-ink-3">
              For teams that keep their decisions in a repository of their own.
              It applies to every release judged against one.
            </p>

            {candidates.length > 0 ? (
              <Field label="Decision repository">
                <select
                  value={adrRepository}
                  onChange={(event) => selectDecisionRepository(event.target.value)}
                  className={inputClass}
                >
                  <option value="">none — do not read a second repository</option>
                  {candidates.map((option) => (
                    <option key={option.key} value={option.key}>
                      {option.url}
                    </option>
                  ))}
                </select>
              </Field>
            ) : (
              <div className="flex flex-col gap-4">
                <Pill tone="warn">nothing else has been ingested</Pill>
                <p className="max-w-prose text-sm leading-relaxed text-ink-3">
                  The only repository here is the one being analysed, and its
                  own records are already read by the first source.
                </p>
                <div>
                  <Link to="/repositories">
                    <Button>Add a decision repository</Button>
                  </Link>
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      <Card
        title="Every release, and what judges it"
        action={
          <span className="font-mono text-xs text-ink-4">
            open a release to see what each source would supply
          </span>
        }
      >
        <ol className="flex flex-col gap-px overflow-hidden rounded-card border border-line bg-line">
          {releases.map((release) => (
            <ReleaseDecision
              key={release}
              repositoryKey={repositoryKey}
              release={release}
              choice={decisionChoices[release]}
              onChoose={choose(release)}
              isValidated={Boolean(runs[runKey(repositoryKey, release)])}
            />
          ))}
        </ol>
      </Card>

      {probe.isLoading && <Spinner label="reading what this repository documents" />}
      {probe.error && <ErrorState message={probe.error} onRetry={probe.reload} />}
      <ProseExtraction documents={documentsFoundButUnused(probe.data?.modes ?? [])} />

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-6">
          <div className="flex flex-col gap-1.5">
            <span className="text-sm text-ink">
              {chosenCount === releases.length
                ? 'Every release has a source. Run them on the pipeline, one at a time.'
                : `${releases.length - chosenCount} release(s) still have nothing chosen.`}
            </span>
            <span className="text-xs text-ink-4">
              Nothing is validated here — the pipeline runs them, so a long
              stack can be watched release by release.
            </span>
          </div>

          {handOver}
        </div>
      </Card>
    </>
  )
}

/**
 * How many decision documents were found and produced no rule.
 *
 * Taken out of the source's own sentence rather than recomputed, because the
 * backend already published the number and a second derivation here is a
 * second number that disagrees on exactly the repository somebody is looking
 * at. Zero when no source reported one, which reads as "not applicable".
 */
function documentsFoundButUnused(modes: ModeAvailability[]): number {
  for (const mode of modes) {
    for (const note of Object.values(mode.source_notes)) {
      const found = note.match(/^(\d+) decision document/)
      if (found) return Number(found[1])
    }
  }
  return 0
}
