/**
 * The pipeline screen - what the application opens on.
 *
 * Description:
 *   One job: start the analysis and show it moving. Everything a run produces
 *   has its own screen, and this one links to them rather than growing them.
 *
 *   **A phase cannot be skipped.** Each one reads what the phase before it
 *   left behind, so a phase whose input does not exist is drawn blocked and
 *   says which input is missing. Letting it be started would produce a
 *   failure from the backend that a person then has to translate; saying it
 *   up front is the same information before the mistake instead of after it.
 *
 *   **Validation asks before it runs.** What a release is judged against is a
 *   real choice with three answers, so starting it hands over to the
 *   decisions screen rather than picking one quietly. Coming back with an
 *   answer starts the run, and the stages replay here.
 *
 *   **The replay is paced on purpose.** The backend answers in a couple of
 *   seconds with every stage already finished, and rendering that truthfully
 *   is a flash and nothing learned. Stages are revealed at reading speed,
 *   slower on the two that call a model. It is a replay of a real run, never
 *   invented data, and the screen says so.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeading,
  Pill,
  Spinner,
  Stat,
  StatRow,
} from '../../components/ui'
import { PHASES, type PhaseId } from '../../layouts/navigation'
import { describePipeline, type ValidationRun } from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { useWorkspace } from '../../workspace/useWorkspace'
import PipelineFlow, { type PhaseState } from './PipelineFlow'
import StageTrack from './StageTrack'
import { toStageViews } from './stageViews'

/** How long one stage is held on screen, so the eye can follow it. */
const STAGE_MS = 420
const MODEL_STAGE_MS = 1150

export default function PipelinePage() {
  const navigate = useNavigate()
  const { repository, isRecovered, run, decisionMode, isRunning, runError } =
    useWorkspace()

  const pipeline = useRequest((options) => describePipeline(options), [])
  const stages = useMemo(() => pipeline.data?.stages ?? [], [pipeline.data])

  const [revealed, setRevealed] = useState(-1)
  const [phase, setPhase] = useState<PhaseId>('validate')

  // Which stages call a model. Mirrored into a ref so the replay can read it
  // without depending on it: the description and the run arrive from two
  // requests in either order, and depending on both restarts the replay the
  // moment the second lands - which is how it used to stop on whichever stage
  // it had reached.
  const modelStages = useMemo(
    () => new Set(stages.filter((stage) => stage.uses_model).map((stage) => stage.name)),
    [stages],
  )
  const modelStagesRef = useRef(modelStages)

  useEffect(() => {
    modelStagesRef.current = modelStages
  }, [modelStages])

  // A run arriving is what starts the replay, so a run started on the
  // decisions screen plays here without that screen knowing this one exists.
  useEffect(() => {
    if (!run) return

    let cancelled = false

    const play = async () => {
      for (let index = 0; index < run.stages.length; index += 1) {
        if (cancelled) return
        setRevealed(index)
        await wait(
          modelStagesRef.current.has(run.stages[index].name)
            ? MODEL_STAGE_MS
            : STAGE_MS,
        )
      }

      if (!cancelled) setRevealed(run.stages.length)
    }

    void play()

    return () => {
      cancelled = true
    }
  }, [run])

  const phaseStates = useMemo<Record<PhaseId, PhaseState>>(
    () => ({
      recover: isRecovered ? 'done' : 'blocked',
      validate: isRunning
        ? 'running'
        : run
          ? 'done'
          : isRecovered
            ? 'waiting'
            : 'blocked',
      detect: 'reserved',
      prioritise: 'reserved',
    }),
    [isRecovered, isRunning, run],
  )

  const stageViews = useMemo(
    () => toStageViews(stages, run?.stages ?? [], revealed),
    [stages, run, revealed],
  )

  const selected = PHASES.find((item) => item.id === phase)!

  return (
    <>
      <PageHeading
        eyebrow="analysis"
        title="Pipeline"
        description="Four phases. Each one reads what the phase before it left behind, so none of them runs out of order — and every result has a screen of its own."
        action={
          <div className="flex items-center gap-5">
            {isRunning && <Spinner label="validating" />}
            <Button
              variant="primary"
              disabled={!isRecovered || isRunning}
              onClick={() => navigate('/decisions')}
            >
              {run ? 'Run again' : 'Start validation'}
            </Button>
          </div>
        }
      />

      {!repository && (
        <Card>
          <EmptyState
            title="Nothing to analyse yet"
            body="Add a repository and its architecture is recovered as part of adding it. Everything after that reads what the phase before it produced."
            action={
              <Link to="/repositories">
                <Button variant="primary">Add a repository</Button>
              </Link>
            }
          />
        </Card>
      )}

      {repository && !isRecovered && (
        <Card>
          <EmptyState
            title="No architecture for this repository yet"
            body="Recovery stores one architecture per release. Add a release — a tag, or the branch head — and the rest of the pipeline unlocks."
            action={
              <Link to="/repositories">
                <Button variant="primary">Add a release</Button>
              </Link>
            }
          />
        </Card>
      )}

      <Card
        title="Flow"
        action={
          <span className="font-mono text-xs text-ink-4">
            {isRunning
              ? 'running'
              : run
                ? 'replayed at reading speed'
                : 'select a phase for its detail'}
          </span>
        }
      >
        <PipelineFlow states={phaseStates} selected={phase} onSelect={setPhase} />

        <RunStatus
          run={run}
          revealed={revealed}
          isRunning={isRunning}
          isRecovered={isRecovered}
        />
      </Card>

      {runError && (
        <ErrorState message={runError} onRetry={() => navigate('/decisions')} />
      )}

      {run && revealed >= run.stages.length && <RunSummary run={run} />}

      <Card
        title={`${selected.label} — what it does`}
        action={
          selected.state === 'reserved' ? (
            <Pill tone="warn">screen not built</Pill>
          ) : (
            <Link
              to={selected.page}
              className="font-mono text-xs text-ink-2 underline-offset-4 hover:text-ink hover:underline"
            >
              open the result →
            </Link>
          )
        }
      >
        <div className="flex flex-col gap-8">
          <dl className="grid gap-7 sm:grid-cols-3">
            <Detail term="reads" value={selected.input} />
            <Detail term="produces" value={selected.output} />
            <Detail term="cannot run until" value={selected.requires} />
          </dl>

          {phase === 'validate' ? (
            <ValidateDetail
              isLoading={pipeline.isLoading}
              error={pipeline.error}
              onRetry={pipeline.reload}
              stageViews={stageViews}
              built={pipeline.data?.implemented_count ?? 0}
              total={pipeline.data?.stage_count ?? 0}
              mode={decisionMode}
            />
          ) : (
            <p className="max-w-prose text-sm leading-relaxed text-ink-3">
              {selected.state === 'reserved'
                ? 'This phase runs in the backend. Its screen is reserved and not written yet — the pipeline draws it so that it is not forgotten.'
                : 'This phase runs when a release is added, and its result has its own screen.'}
            </p>
          )}
        </div>
      </Card>
    </>
  )
}

/**
 * Where the run has got to, and what to do about it.
 *
 * The pipeline is where somebody comes back to, so it has to answer "what is
 * happening now" and "what next" without them reading the stage track. A
 * drawing that shows a phase lit and says nothing else leaves a person
 * watching it, which is what this strip is for.
 */
function RunStatus({
  run,
  revealed,
  isRunning,
  isRecovered,
}: {
  run: ValidationRun | null
  revealed: number
  isRunning: boolean
  isRecovered: boolean
}) {
  const finished = run && revealed >= run.stages.length
  const current = run && !finished ? run.stages[Math.max(0, revealed)] : null

  return (
    <div className="mt-8 flex flex-wrap items-center justify-between gap-5 border-t border-line pt-7">
      <div className="flex min-w-0 flex-col gap-1.5">
        {isRunning && (
          <span className="text-sm text-ink">Asking the backend to validate this release…</span>
        )}

        {!isRunning && run && current && (
          <>
            <span className="text-sm text-ink">{current.name.replace(/_/g, ' ')}</span>
            <span className="font-mono text-xs text-ink-4">
              stage {Math.min(revealed + 1, run.stages.length)} of {run.stages.length}
            </span>
          </>
        )}

        {!isRunning && run && finished && (
          <>
            <span className="text-sm text-ink">
              Validation complete — {run.stages.find((item) => item.name === 'classification')?.counts.facts ?? 0}{' '}
              dependencies judged
            </span>
            <span className="font-mono text-xs text-ink-4">
              run {run.run_id} · {run.model_calls} model calls
            </span>
          </>
        )}

        {!run && !isRunning && (
          <span className="text-sm text-ink-3">
            {isRecovered
              ? 'Nothing has been validated for this release yet.'
              : 'Recover a release and the rest of the pipeline unlocks.'}
          </span>
        )}
      </div>

      {finished && (
        <div className="flex flex-wrap items-center gap-3">
          <Link to="/validation">
            <Button variant="primary" size="sm">
              How it was judged
            </Button>
          </Link>
          <Link to="/findings">
            <Button size="sm">Findings</Button>
          </Link>
          <Link to="/canvas">
            <Button size="sm">Canvas</Button>
          </Link>
        </div>
      )}
    </div>
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

function RunSummary({ run }: { run: ValidationRun }) {
  const facts = run.stages.find((stage) => stage.name === 'classification')?.counts ?? {}

  return (
    <StatRow>
      <Stat
        label="confidence"
        value={run.validation_confidence.toFixed(2)}
        note={`over ${facts.facts ?? 0} dependencies`}
        tone="ok"
      />
      <Stat
        label="model calls"
        value={run.model_calls}
        note={run.verification_mode ?? 'verification not requested'}
        tone="ai"
      />
      <Stat
        label="judged against"
        value={(run.decision_mode ?? 'unknown').replace(/_/g, ' ')}
        note={run.style_resolved ? `style ${run.style_resolved}` : undefined}
      />
      <Stat
        label="status"
        value={run.status}
        note={run.published_ref ? 'published' : 'nothing published'}
        tone={run.status === 'completed' ? 'ok' : 'warn'}
      />
    </StatRow>
  )
}

function ValidateDetail({
  isLoading,
  error,
  onRetry,
  stageViews,
  built,
  total,
  mode,
}: {
  isLoading: boolean
  error: string | null
  onRetry: () => void
  stageViews: ReturnType<typeof toStageViews>
  built: number
  total: number
  mode: string | null
}) {
  if (error) return <ErrorState message={error} onRetry={onRetry} />
  if (isLoading) return <Spinner label="reading the stages" />
  if (stageViews.length === 0) {
    return <p className="text-sm text-ink-3">The backend reported no stages.</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <span className="font-mono text-xs text-ink-4">
          {built} of {total} stages built
          {mode ? ` · judged against ${mode.replace(/_/g, ' ')}` : ''}
        </span>
        <span className="font-mono text-xs text-ink-4">
          a purple mark is a stage that calls a model
        </span>
      </div>
      <StageTrack stages={stageViews} />
    </div>
  )
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
