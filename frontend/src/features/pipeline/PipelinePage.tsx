/**
 * The pipeline screen - what the application opens on.
 *
 * Description:
 *   One job: configure the snapshots, recover them, and show it happening.
 *
 *   **A run is a stack, not a single release.** Recovery is executed for
 *   snapshot 1, then 2, then 3, sequentially on purpose: a run that is watched
 *   is a run whose progress can be reported, and "which snapshot is it on" has
 *   one answer.
 *
 *   **It recovers and stops.** Validation is not started here, because it
 *   cannot begin until somebody has chosen what the releases are judged
 *   against - and that is the one choice the analysis cannot make for a
 *   person. So a finished recovery hands over to the decisions screen, where
 *   every source shows what it would supply before it is picked. This screen
 *   held a second copy of that selector once, defaulted to one mode, and so
 *   validated against a source nobody had chosen.
 *
 *   **One stack, one row per snapshot, details under the row they belong to.**
 *   Details are open by default - they are what somebody came to read - and
 *   while a snapshot is moving it is the only one left expanded, so the row
 *   that is working is not pushed off the screen by three that are finished.
 *
 *   **Configured and running are separate.** Adding a snapshot here (or on the
 *   repositories screen) writes down what to analyse and clones nothing. Only
 *   pressing run starts the work.
 *
 *   **A failure is never carried forward.** A snapshot that fails to clone or
 *   recover is marked failed with the backend's own words, and the stack is
 *   reported as blocked rather than offered for judgement - a release
 *   validated against a partial stack would read like a clean run of a smaller
 *   pipeline.
 *
 *   The drawing is the explanation of the order, which is why it is the only
 *   place in the application where motion is allowed.
 */

import { useMemo, useState, type FormEvent } from 'react'
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
  Stat,
  StatRow,
  inputClass,
} from '../../components/ui'
import { PHASES, type PhaseId } from '../../layouts/navigation'
import {
  describePipeline,
  messageOf,
  type RepositoryConfiguration,
  type StageDescription,
  type ValidationRun,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { runKey } from '../../workspace/context'
import { useWorkspace } from '../../workspace/useWorkspace'
import type {
  PipelinePhase,
  SnapshotPhase,
  SnapshotRun,
} from '../../workspace/pipeline'
import PipelineFlow, { type PhaseState } from './PipelineFlow'
import RecoveryStages from './RecoveryStages'
import StageTrack from './StageTrack'
import { toStageViews } from './stageViews'

export default function PipelinePage() {
  const navigate = useNavigate()
  const {
    configurations,
    configurationsError,
    isLoadingConfigurations,
    addConfiguration,
    removeConfiguration,
    pipelinePhase,
    pipelineSnapshots,
    isPipelineRunning,
    pipelineError,
    startPipeline,
    runs,
  } = useWorkspace()

  const described = useRequest((options) => describePipeline(options), [])

  const [selectedPhase, setSelectedPhase] = useState<PhaseId>('recover')

  // Hidden, not opened. Details are what somebody came to read, so a row that
  // has them shows them; the list records the ones a person closed rather than
  // the ones they had to open.
  const [hidden, setHidden] = useState<string[]>([])

  const progress = useMemo(
    () => new Map(pipelineSnapshots.map((snapshot) => [snapshot.configuration.id, snapshot])),
    [pipelineSnapshots],
  )

  // While a snapshot is working, it is the only one expanded. Four open rows
  // during a run means the one that is moving is somewhere off the screen.
  const working = pipelineSnapshots.find((snapshot) =>
    snapshot.phase === 'ingesting' || snapshot.phase === 'recovering',
  )
  const activeId = isPipelineRunning ? (working?.configuration.id ?? null) : null

  const toggle = (configurationId: string) =>
    setHidden((current) =>
      current.includes(configurationId)
        ? current.filter((id) => id !== configurationId)
        : [...current, configurationId],
    )

  // A run reaches this screen through the session's runs, not through the
  // snapshot, because the decisions screen is what started it.
  const validated = pipelineSnapshots.some((snapshot) => runFor(snapshot, runs))

  const phaseStates = useMemo<Record<PhaseId, PhaseState>>(
    () => ({
      recover: recoverState(pipelinePhase, pipelineSnapshots, configurations.length),
      validate: validateState(pipelinePhase, validated),
      detect: 'reserved',
      prioritise: 'reserved',
    }),
    [pipelinePhase, pipelineSnapshots, validated, configurations.length],
  )

  const run = async () => {
    setHidden([])

    // Recovery is all this starts. A recovered stack has to be judged against
    // something, nothing but a person may choose what, and the screen that
    // asks shows every source's yield at the moment of choosing - so the
    // handoff is a redirect rather than a sentence somebody might not read.
    if (await startPipeline()) navigate('/decisions')
  }

  const phase = PHASES.find((item) => item.id === selectedPhase)!

  return (
    <>
      <PageHeading
        eyebrow="analysis"
        title="Pipeline"
        description="Four phases. Running the pipeline recovers every configured snapshot, one at a time, and stops there — what they are judged against is chosen on the decisions screen."
        action={
          <div className="flex items-center gap-5">
            {isPipelineRunning && <Spinner label="running" />}
            <Button
              variant="primary"
              disabled={configurations.length === 0 || isPipelineRunning}
              onClick={run}
            >
              {pipelinePhase === 'idle' ? 'Run pipeline' : 'Run again'}
            </Button>
          </div>
        }
      />

      <Card
        title="Flow"
        action={
          <span className="font-mono text-xs text-ink-4">
            {isPipelineRunning
              ? 'running'
              : pipelinePhase === 'idle'
                ? 'configure a snapshot to begin'
                : 'what this run did'}
          </span>
        }
      >
        <PipelineFlow
          states={phaseStates}
          selected={selectedPhase}
          onSelect={setSelectedPhase}
        />

        <RunStatus
          phase={pipelinePhase}
          snapshots={pipelineSnapshots}
          error={pipelineError}
          isRunning={isPipelineRunning}
        />
      </Card>

      <SnapshotsCard
        configurations={configurations}
        configurationsError={configurationsError}
        isLoading={isLoadingConfigurations}
        progress={progress}
        hidden={hidden}
        activeId={activeId}
        runs={runs}
        isRunning={isPipelineRunning}
        stagesDescribed={described.data?.stages ?? []}
        onAdd={addConfiguration}
        onRemove={removeConfiguration}
        onToggle={toggle}
      />

      <JudgedAgainst
        phase={pipelinePhase}
        isRunning={isPipelineRunning}
        validated={validated}
      />

      <Card
        title={`${phase.label} — what it does`}
        action={
          phase.state === 'reserved' ? (
            <Pill tone="warn">screen not built</Pill>
          ) : (
            <Link
              to={phase.page}
              className="font-mono text-xs text-ink-2 underline-offset-4 hover:text-ink hover:underline"
            >
              open the result →
            </Link>
          )
        }
      >
        <div className="flex flex-col gap-8">
          <dl className="grid gap-7 sm:grid-cols-3">
            <Detail term="reads" value={phase.input} />
            <Detail term="produces" value={phase.output} />
            <Detail term="cannot run until" value={phase.requires} />
          </dl>

          <p className="max-w-prose text-sm leading-relaxed text-ink-3">
            {phase.state === 'reserved'
              ? 'This phase runs in the backend. Its screen is reserved and not written yet — the pipeline draws it so that it is not forgotten.'
              : phase.id === 'recover'
                ? 'Recovery runs for every configured snapshot, one at a time, when the pipeline starts.'
                : 'Validation is started on the decisions screen, once somebody has chosen what these releases are judged against. The pipeline recovers the stack and stops there.'}
          </p>
        </div>
      </Card>

      {validated && (
        <Card title="The rest of this result">
          <div className="grid gap-5 sm:grid-cols-2">
            <Elsewhere
              to="/validation"
              title="Validation"
              body="How a release was judged, one release at a time."
            />
            <Elsewhere
              to="/findings"
              title="Findings"
              body="Every dependency with its verdict."
            />
            <Elsewhere to="/canvas" title="Canvas" body="The published graph, drawn." />
            <Elsewhere to="/architecture" title="Architecture" body="What recovery found." />
          </div>
        </Card>
      )}
    </>
  )
}

/* The stack ---------------------------------------------------------------- */

function SnapshotsCard({
  configurations,
  configurationsError,
  isLoading,
  progress,
  hidden,
  activeId,
  runs,
  isRunning,
  stagesDescribed,
  onAdd,
  onRemove,
  onToggle,
}: {
  configurations: RepositoryConfiguration[]
  configurationsError: string | null
  isLoading: boolean
  progress: Map<string, SnapshotRun>
  /** The rows this person closed. Everything else with details is open. */
  hidden: string[]
  /** The snapshot currently moving, which is the only one left expanded. */
  activeId: string | null
  runs: Record<string, ValidationRun>
  isRunning: boolean
  stagesDescribed: StageDescription[]
  onAdd: (input: {
    url: string
    branch: string
    release_tag: string
  }) => Promise<RepositoryConfiguration>
  onRemove: (configurationId: string) => Promise<void>
  onToggle: (configurationId: string) => void
}) {
  const [url, setUrl] = useState('')
  const [branch, setBranch] = useState('main')
  const [releaseTag, setReleaseTag] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const add = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setIsSaving(true)
    setFailure(null)

    try {
      await onAdd({ url, branch, release_tag: releaseTag.trim() })
      setReleaseTag('')
    } catch (cause) {
      setFailure(messageOf(cause))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Card
      title="Snapshots"
      action={
        <span className="font-mono text-xs text-ink-4">
          {configurations.length} configured · run in this order
        </span>
      }
    >
      <div className="flex flex-col gap-8">
        <form onSubmit={add} className="flex flex-col gap-5">
          <div className="grid gap-5 lg:grid-cols-[2fr_1fr_1fr_auto] lg:items-end">
            <Field label="Repository URL">
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://github.com/organisation/project.git"
                autoComplete="off"
                required
                disabled={isRunning}
                className={inputClass}
              />
            </Field>

            <Field label="Branch">
              <input
                value={branch}
                onChange={(event) => setBranch(event.target.value)}
                placeholder="main"
                autoComplete="off"
                required
                disabled={isRunning}
                className={inputClass}
              />
            </Field>

            <Field label="Release tag">
              <input
                value={releaseTag}
                onChange={(event) => setReleaseTag(event.target.value)}
                placeholder="v1.4.0"
                autoComplete="off"
                required
                disabled={isRunning}
                className={inputClass}
              />
            </Field>

            <Button type="submit" disabled={isSaving || isRunning}>
              {isSaving ? 'Saving…' : 'Add snapshot'}
            </Button>
          </div>

          {failure && <ErrorState message={failure} />}
        </form>

        {configurationsError && <ErrorState message={configurationsError} />}

        {isLoading && !configurationsError && (
          <Spinner label="reading the configured snapshots" />
        )}

        {!isLoading && !configurationsError && configurations.length === 0 && (
          <EmptyState
            title="No snapshots configured"
            body="Add one above, or configure several on the repositories screen. Nothing is cloned until the pipeline runs."
            action={
              <Link to="/repositories">
                <Button>Open repositories</Button>
              </Link>
            }
          />
        )}

        <ol className="flex flex-col gap-px overflow-hidden rounded-card border border-line bg-line">
          {configurations.map((configuration, index) => {
            const snapshot = progress.get(configuration.id)
            const phase = snapshot?.phase ?? 'queued'
            const run = runFor(snapshot, runs)
            const hasDetails = Boolean(snapshot?.recovery || run)

            // Open unless this person closed it, and collapsed while a
            // different snapshot is the one moving.
            const isOpen =
              hasDetails &&
              !hidden.includes(configuration.id) &&
              (activeId === null || activeId === configuration.id)

            return (
              <li key={configuration.id} className="flex flex-col gap-5 bg-panel px-6 py-5">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex min-w-0 items-center gap-4">
                    <span className="font-mono text-xs text-ink-4">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <div className="flex min-w-0 flex-col gap-1.5">
                      <span className="truncate font-mono text-sm text-ink">
                        {configuration.url}
                      </span>
                      <span className="font-mono text-xs text-ink-4">
                        {configuration.branch} · {configuration.release_tag}
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <SnapshotStatus phase={phase} />
                    <Button
                      size="sm"
                      variant="quiet"
                      onClick={() => onToggle(configuration.id)}
                      disabled={!hasDetails}
                    >
                      {isOpen ? 'Hide details' : 'Details'}
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => onRemove(configuration.id)}
                      disabled={isRunning}
                    >
                      Remove
                    </Button>
                  </div>
                </div>

                {snapshot?.error && (
                  <p className="max-w-prose border-l-2 border-bad/60 pl-4 text-xs leading-relaxed text-bad">
                    {snapshot.fault ? `${faultLabel(snapshot.fault)}: ` : ''}
                    {snapshot.error}
                  </p>
                )}

                {isOpen && snapshot?.recovery && (
                  <div className="flex flex-col gap-4 border-t border-line pt-5">
                    <span className="font-mono text-[11px] tracking-wide text-ink-4 uppercase">
                      what recovery found
                    </span>
                    <RecoveryStages recovery={snapshot.recovery} />
                  </div>
                )}

                {isOpen && run && (
                  <div className="flex flex-col gap-5 border-t border-line pt-5">
                    <div className="flex flex-wrap items-baseline justify-between gap-3">
                      <span className="font-mono text-[11px] tracking-wide text-ink-4 uppercase">
                        what validation did
                      </span>
                      <span className="font-mono text-xs text-ink-4">
                        run {run.run_id} · {run.status}
                      </span>
                    </div>

                    <StatRow>
                      <Stat
                        label="confidence"
                        value={run.validation_confidence.toFixed(2)}
                        note={`over ${countedFacts(run)} dependencies`}
                        tone="ok"
                      />
                      <Stat
                        label="model calls"
                        value={run.model_calls}
                        note={
                          run.verification_mode ?? 'verification not requested'
                        }
                        tone="ai"
                      />
                      <Stat
                        label="judged against"
                        value={(run.decision_mode ?? 'unknown').replace(/_/g, ' ')}
                        note={
                          run.style_resolved
                            ? `style ${run.style_resolved}`
                            : undefined
                        }
                      />
                      <Stat
                        label="published"
                        value={run.published_ref ? 'yes' : 'no'}
                        note={run.release_id}
                        tone={run.published_ref ? 'ok' : 'warn'}
                      />
                    </StatRow>

                    {stagesDescribed.length > 0 && (
                      <StageTrack
                        stages={toStageViews(
                          stagesDescribed,
                          run.stages,
                          run.stages.length,
                        )}
                      />
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ol>
      </div>
    </Card>
  )
}

function SnapshotStatus({ phase }: { phase: SnapshotPhase }) {
  const tone = {
    queued: 'neutral',
    ingesting: 'ai',
    recovering: 'ai',
    recovered: 'ok',
    failed: 'bad',
  }[phase] as 'neutral' | 'ok' | 'bad' | 'ai'

  return <Pill tone={tone}>{label(phase)}</Pill>
}

function label(phase: SnapshotPhase): string {
  return {
    queued: 'waiting',
    ingesting: 'cloning',
    recovering: 'recovering',
    recovered: 'recovered',
    failed: 'failed',
  }[phase]
}

function faultLabel(fault: NonNullable<SnapshotRun['fault']>): string {
  return {
    ingest: 'clone',
    recovery: 'recovery',
    validation: 'validation',
  }[fault]
}

/* The run's own status ------------------------------------------------------ */

/**
 * What this run is judged against — which is a question, not a setting.
 *
 * This card used to hold a second copy of the decision-source selector, with
 * `combined` as its default. That made the pipeline validate against a source
 * nobody had chosen, while the decisions screen presented itself as the place
 * the choice is made: two controls for one decision, and the one that actually
 * ran was the one with no yields on screen beside it.
 *
 * So it is a handoff now. **Highlighted once the stack is recovered**, because
 * at that moment it is the only thing left to do and a quiet row is a row
 * somebody reads past.
 */
function JudgedAgainst({
  phase,
  isRunning,
  validated,
}: {
  phase: PipelinePhase
  isRunning: boolean
  /** Whether anything in this stack has been judged yet. */
  validated: boolean
}) {
  // Recovered and not yet judged is the only moment this is the next thing to
  // do. The pipeline phase stays `recovered` after the decisions screen has
  // run, so without this the card would go on asking for a choice already made.
  const isWaiting = phase === 'recovered' && !isRunning && !validated

  return (
    <Card
      title="What this run is judged against"
      action={
        isWaiting ? (
          <Pill tone="ai">choose this next</Pill>
        ) : (
          <Pill tone="neutral">chosen on the decisions screen</Pill>
        )
      }
      className={isWaiting ? 'border-ai' : ''}
    >
      <div className="flex flex-wrap items-center justify-between gap-6">
        <p className="max-w-prose text-sm leading-relaxed text-ink-2">
          {isWaiting
            ? 'Every snapshot has recovered. Nothing has been judged yet — pick what these releases are validated against, and start it there.'
            : 'Validation is started on the decisions screen, where every source shows what it would supply before it is chosen. A release judged against a source nobody picked reports that nothing contradicts it, which is indistinguishable from a healthy system.'}
        </p>

        <Link to="/decisions">
          <Button variant={isWaiting ? 'primary' : undefined}>
            {isWaiting ? 'Choose and validate' : 'Open decisions'}
          </Button>
        </Link>
      </div>
    </Card>
  )
}

function RunStatus({
  phase,
  snapshots,
  error,
  isRunning,
}: {
  phase: PipelinePhase
  snapshots: SnapshotRun[]
  error: string | null
  isRunning: boolean
}) {
  const recovered = snapshots.filter((snapshot) => snapshot.phase === 'recovered').length
  const failed = snapshots.filter((snapshot) => snapshot.phase === 'failed').length
  const current = snapshots.find(
    (snapshot) => snapshot.phase === 'ingesting' || snapshot.phase === 'recovering',
  )
  const position = current ? snapshots.indexOf(current) + 1 : 0

  return (
    <div className="mt-8 flex flex-col gap-4 border-t border-line pt-7">
      {isRunning && current && (
        <div className="flex flex-wrap items-baseline gap-4">
          <span className="text-sm text-ink">
            Recovering {position} of {snapshots.length} —{' '}
            {current.configuration.release_tag}
          </span>
          <span className="font-mono text-xs text-ink-4">
            {current.phase === 'ingesting' ? 'cloning' : 'recovery stages running'}
          </span>
        </div>
      )}

      {!isRunning && phase === 'idle' && (
        <span className="text-sm text-ink-3">
          Nothing has run yet. Recovery runs for every configured snapshot; what
          they are then judged against is chosen on the decisions screen.
        </span>
      )}

      {!isRunning && phase === 'recovered' && (
        <div className="flex flex-col gap-1.5">
          <span className="text-sm text-ink">
            {recovered} of {snapshots.length} snapshots recovered. Nothing has
            been judged yet.
          </span>
          <span className="font-mono text-xs text-ink-4">
            choose what they are validated against on the decisions screen
          </span>
        </div>
      )}

      {!isRunning && phase === 'blocked' && (
        <div className="flex flex-col gap-1.5">
          <span className="text-sm text-bad">
            {failed} of {snapshots.length} snapshots did not finish.
          </span>
          {error && (
            <span className="max-w-prose text-xs leading-relaxed text-warn">{error}</span>
          )}
        </div>
      )}
    </div>
  )
}

function Elsewhere({ to, title, body }: { to: string; title: string; body: string }) {
  return (
    <Link
      to={to}
      className="flex flex-col gap-2 rounded-control border border-line px-6 py-5 transition hover:border-line-strong"
    >
      <span className="text-sm font-medium text-ink">{title} →</span>
      <span className="text-xs leading-relaxed text-ink-3">{body}</span>
    </Link>
  )
}

function Detail({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex flex-col gap-2">
      <dt className="text-xs tracking-wide text-ink-4">{term}</dt>
      <dd className="text-sm leading-relaxed text-ink-2">{value}</dd>
    </div>
  )
}

/* Phase states ------------------------------------------------------------- */

function recoverState(
  phase: PipelinePhase,
  snapshots: SnapshotRun[],
  configured: number,
): PhaseState {
  const recoveryFailed = snapshots.some(
    (snapshot) => snapshot.fault === 'ingest' || snapshot.fault === 'recovery',
  )

  if (phase === 'recovering') return 'running'
  if (recoveryFailed) return 'failed'
  if (phase === 'idle') return configured > 0 ? 'waiting' : 'blocked'
  return 'done'
}

/**
 * The validate node, which this screen no longer runs.
 *
 * It is `waiting` from the moment the stack is recovered until somebody has
 * chosen what judges it - waiting on a person rather than on a call, and for
 * as long as they take. Drawing it `done` before that would put a green phase
 * over a result that does not exist, and drawing it `blocked` would say the
 * stack is not ready when it is.
 */
function validateState(phase: PipelinePhase, validated: boolean): PhaseState {
  if (validated) return 'done'
  if (phase === 'recovered') return 'waiting'
  if (phase === 'recovering') return 'waiting'
  return 'blocked'
}

function countedFacts(run: ValidationRun | undefined): number {
  return run?.stages.find((stage) => stage.name === 'classification')?.counts.facts ?? 0
}

/**
 * The validation this snapshot got, if it has had one.
 *
 * Looked up rather than carried on the snapshot, because the pipeline no
 * longer runs validation - the decisions screen does, and what it produced
 * reaches this screen through the runs the session remembers. Keyed by the
 * identity recovery stores the architecture under, which is the key the run
 * was started with.
 */
function runFor(
  snapshot: SnapshotRun | undefined,
  runs: Record<string, ValidationRun>,
): ValidationRun | undefined {
  const key = snapshot?.recovery?.repository_id
  if (!key) return undefined

  return runs[runKey(key, snapshot.configuration.release_tag)]
}
