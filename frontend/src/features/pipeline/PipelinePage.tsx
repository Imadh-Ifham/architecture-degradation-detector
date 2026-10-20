/**
 * The pipeline screen - what the application opens on.
 *
 * Description:
 *   One job: configure the snapshots, run them, and show the run happening.
 *
 *   **A run is a stack, not a single release.** Recovery is executed for
 *   snapshot 1, then 2, then 3; validation starts only once every one of them
 *   has recovered, and then runs in the same order. Both phases are sequential
 *   on purpose: a run that is watched is a run whose progress can be reported,
 *   and "which snapshot is it on" has one answer.
 *
 *   **One stack, one row per snapshot, details under the row they belong to.**
 *   The header selects a repository and never a release, and this screen does
 *   not inherit a release from anywhere: every configured snapshot carries its
 *   own recovery and its own verdict, and opening one does not hide the others.
 *
 *   **Configured and running are separate.** Adding a snapshot here (or on the
 *   repositories screen) writes down what to analyse and clones nothing. Only
 *   pressing run starts the work.
 *
 *   **A failure is never carried forward.** A snapshot that fails to clone or
 *   recover is marked failed with the backend's own words, and validation does
 *   not start at all while any snapshot is in that state - validating the ones
 *   that happened to work would publish a result that reads like a clean run of
 *   a smaller pipeline.
 *
 *   The drawing is the explanation of the order, which is why it is the only
 *   place in the application where motion is allowed.
 */

import { useMemo, useState, type FormEvent } from 'react'
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
  Stat,
  StatRow,
  inputClass,
} from '../../components/ui'
import { PHASES, type PhaseId } from '../../layouts/navigation'
import {
  describePipeline,
  messageOf,
  type DecisionMode,
  type RepositoryConfiguration,
  type StageDescription,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
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

const MODE: Record<DecisionMode, string> = {
  combined: 'Both, plus rules recovered from configuration',
  repo_adr: 'Decision records in this repository',
  external_adr: 'Decision records in a repository you name',
}

export default function PipelinePage() {
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
  } = useWorkspace()

  const described = useRequest((options) => describePipeline(options), [])

  const [mode, setMode] = useState<DecisionMode>('combined')
  const [adrRepository, setAdrRepository] = useState('')
  const [selectedPhase, setSelectedPhase] = useState<PhaseId>('recover')
  const [opened, setOpened] = useState<string[]>([])

  const progress = useMemo(
    () => new Map(pipelineSnapshots.map((snapshot) => [snapshot.configuration.id, snapshot])),
    [pipelineSnapshots],
  )

  const toggle = (configurationId: string) =>
    setOpened((current) =>
      current.includes(configurationId)
        ? current.filter((id) => id !== configurationId)
        : [...current, configurationId],
    )

  const phaseStates = useMemo<Record<PhaseId, PhaseState>>(
    () => ({
      recover: recoverState(pipelinePhase, pipelineSnapshots, configurations.length),
      validate: validateState(pipelinePhase, pipelineSnapshots),
      detect: 'reserved',
      prioritise: 'reserved',
    }),
    [pipelinePhase, pipelineSnapshots, configurations.length],
  )

  const run = async () => {
    setOpened([])
    await startPipeline(mode, adrRepository.trim())
  }

  const phase = PHASES.find((item) => item.id === selectedPhase)!
  const validated = pipelineSnapshots.some((snapshot) => snapshot.phase === 'validated')

  return (
    <>
      <PageHeading
        eyebrow="analysis"
        title="Pipeline"
        description="Four phases. Recovery runs for every configured snapshot first; validation starts only after all of them have recovered, and runs in the same order."
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
        opened={opened}
        isRunning={isPipelineRunning}
        stagesDescribed={described.data?.stages ?? []}
        onAdd={addConfiguration}
        onRemove={removeConfiguration}
        onToggle={toggle}
      />

      <Card
        title="What this run is judged against"
        action={<Pill tone="neutral">{MODE[mode].split(',')[0]}</Pill>}
      >
        <div className="flex flex-wrap items-end gap-6">
          <Field label="Decisions come from">
            <select
              value={mode}
              onChange={(event) => setMode(event.target.value as DecisionMode)}
              disabled={isPipelineRunning}
              className={inputClass}
            >
              <option value="combined">{MODE.combined}</option>
              <option value="repo_adr">{MODE.repo_adr}</option>
              <option value="external_adr">{MODE.external_adr}</option>
            </select>
          </Field>

          {mode === 'external_adr' && (
            <Field
              label="Decision repository id"
              hint="Added on the repositories screen first, then named here."
            >
              <input
                value={adrRepository}
                onChange={(event) => setAdrRepository(event.target.value)}
                disabled={isPipelineRunning}
                placeholder="the id shown on the repositories screen"
                className={inputClass}
              />
            </Field>
          )}

          <p className="max-w-prose text-xs leading-relaxed text-ink-4">
            Every snapshot in this run is judged against the same source. A mode
            that would supply nothing stops the run at validation rather than
            reporting a clean result.
          </p>
        </div>
      </Card>

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
                : 'Validation runs for every recovered snapshot, one at a time, after recovery has finished for all of them.'}
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
  opened,
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
  opened: string[]
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
            const isOpen = opened.includes(configuration.id)
            const hasDetails = Boolean(snapshot?.recovery || snapshot?.run)

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

                {isOpen && snapshot?.run && (
                  <div className="flex flex-col gap-5 border-t border-line pt-5">
                    <div className="flex flex-wrap items-baseline justify-between gap-3">
                      <span className="font-mono text-[11px] tracking-wide text-ink-4 uppercase">
                        what validation did
                      </span>
                      <span className="font-mono text-xs text-ink-4">
                        run {snapshot.run.run_id} · {snapshot.run.status}
                      </span>
                    </div>

                    <StatRow>
                      <Stat
                        label="confidence"
                        value={snapshot.run.validation_confidence.toFixed(2)}
                        note={`over ${countedFacts(snapshot.run)} dependencies`}
                        tone="ok"
                      />
                      <Stat
                        label="model calls"
                        value={snapshot.run.model_calls}
                        note={
                          snapshot.run.verification_mode ?? 'verification not requested'
                        }
                        tone="ai"
                      />
                      <Stat
                        label="judged against"
                        value={(snapshot.run.decision_mode ?? 'unknown').replace(/_/g, ' ')}
                        note={
                          snapshot.run.style_resolved
                            ? `style ${snapshot.run.style_resolved}`
                            : undefined
                        }
                      />
                      <Stat
                        label="published"
                        value={snapshot.run.published_ref ? 'yes' : 'no'}
                        note={snapshot.run.release_id}
                        tone={snapshot.run.published_ref ? 'ok' : 'warn'}
                      />
                    </StatRow>

                    {stagesDescribed.length > 0 && (
                      <StageTrack
                        stages={toStageViews(
                          stagesDescribed,
                          snapshot.run.stages,
                          snapshot.run.stages.length,
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
    validating: 'ai',
    validated: 'ok',
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
    validating: 'validating',
    validated: 'validated',
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
  const validated = snapshots.filter((snapshot) => snapshot.phase === 'validated').length
  const failed = snapshots.filter((snapshot) => snapshot.phase === 'failed').length
  const current = snapshots.find(
    (snapshot) =>
      snapshot.phase === 'ingesting' ||
      snapshot.phase === 'recovering' ||
      snapshot.phase === 'validating',
  )
  const position = current ? snapshots.indexOf(current) + 1 : 0

  return (
    <div className="mt-8 flex flex-col gap-4 border-t border-line pt-7">
      {isRunning && current && (
        <div className="flex flex-wrap items-baseline gap-4">
          <span className="text-sm text-ink">
            {current.phase === 'validating' ? 'Validating' : 'Recovering'} {position} of{' '}
            {snapshots.length} — {current.configuration.release_tag}
          </span>
          <span className="font-mono text-xs text-ink-4">
            {current.phase === 'ingesting'
              ? 'cloning'
              : current.phase === 'recovering'
                ? 'recovery stages running'
                : 'validation stages running'}
          </span>
        </div>
      )}

      {!isRunning && phase === 'idle' && (
        <span className="text-sm text-ink-3">
          Nothing has run yet. Recovery runs for every configured snapshot, then
          validation runs for every recovered one.
        </span>
      )}

      {!isRunning && phase === 'complete' && (
        <div className="flex flex-col gap-1.5">
          <span className="text-sm text-ink">
            {validated} of {snapshots.length} snapshots recovered and validated.
          </span>
          <span className="font-mono text-xs text-ink-4">
            each one keeps its own result — open a row to read it
          </span>
        </div>
      )}

      {!isRunning && (phase === 'failed' || phase === 'blocked') && (
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

function validateState(phase: PipelinePhase, snapshots: SnapshotRun[]): PhaseState {
  const validationFailed = snapshots.some((snapshot) => snapshot.fault === 'validation')

  if (phase === 'validating') return 'running'
  if (validationFailed) return 'failed'
  if (phase === 'recovering') return 'waiting'
  if (phase === 'complete') return 'done'
  return 'blocked'
}

function countedFacts(run: SnapshotRun['run']): number {
  return run?.stages.find((stage) => stage.name === 'classification')?.counts.facts ?? 0
}
