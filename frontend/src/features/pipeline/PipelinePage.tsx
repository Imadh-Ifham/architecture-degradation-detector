/**
 * The pipeline screen - what the application opens on.
 *
 * Description:
 *   One job: start the analysis and show it moving. Everything a run produces
 *   has its own screen, and this one links to them rather than growing them.
 *
 *   **The run is paced on purpose.** The backend answers in a couple of
 *   seconds with every stage already finished, and rendering that truthfully
 *   means a flash and nothing learned. So the stages are revealed at reading
 *   speed, slower on the two that call a model. It is a replay of a real run,
 *   never invented data, and the screen says so.
 */

import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router'
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
import { describePipeline, messageOf, runValidation, type ValidationRun } from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { useWorkspace } from '../../workspace/useWorkspace'
import PipelineFlow, { type PhaseState } from './PipelineFlow'
import StageTrack from './StageTrack'
import { toStageViews } from './stageViews'

/** How long one stage is held on screen, so the eye can follow it. */
const STAGE_MS = 380
const MODEL_STAGE_MS = 1100

export default function PipelinePage() {
  const { repository, release } = useWorkspace()
  const pipeline = useRequest((options) => describePipeline(options), [])

  const [run, setRun] = useState<ValidationRun | null>(null)
  const [revealed, setRevealed] = useState(-1)
  const [isRunning, setIsRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [phase, setPhase] = useState<PhaseId>('validate')

  // Memoised so the run callback and the stage views are not rebuilt on
  // every render by a fresh empty array.
  const stages = useMemo(() => pipeline.data?.stages ?? [], [pipeline.data])

  const start = useCallback(async () => {
    if (!repository || !release) return

    setIsRunning(true)
    setRunError(null)
    setRun(null)
    setRevealed(0)
    setPhase('validate')

    try {
      const result = await runValidation({
        repository_id: repository.id,
        release_id: release,
      })

      setRun(result)
      await reveal(result, stages.map((stage) => stage.uses_model), setRevealed)
    } catch (cause) {
      setRunError(messageOf(cause))
      setRevealed(-1)
    } finally {
      setIsRunning(false)
    }
  }, [repository, release, stages])

  const phaseStates = useMemo<Record<PhaseId, PhaseState>>(
    () => ({
      recover: repository ? 'done' : 'waiting',
      validate: isRunning ? 'running' : run ? 'done' : 'waiting',
      detect: 'reserved',
      prioritise: 'reserved',
    }),
    [repository, isRunning, run],
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
        description="Four phases. Each one reads what the one before it left behind, and every result has a screen of its own."
        action={
          <div className="flex items-center gap-4">
            {isRunning && <Spinner label="running" />}
            <Button variant="primary" onClick={start} disabled={isRunning || !repository}>
              {isRunning ? 'Running…' : 'Run analysis'}
            </Button>
          </div>
        }
      />

      {!repository && !pipeline.isLoading && (
        <Card>
          <EmptyState
            title="Nothing to analyse yet"
            body="Add a repository and the pipeline runs against it. Everything after that reads what the step before it produced."
            action={
              <Link to="/repositories">
                <Button>Add a repository</Button>
              </Link>
            }
          />
        </Card>
      )}

      <Card
        title="Flow"
        action={
          <span className="font-mono text-xs text-ink-4">
            {isRunning ? 'replayed at reading speed' : 'select a phase for its detail'}
          </span>
        }
      >
        <PipelineFlow states={phaseStates} selected={phase} onSelect={setPhase} />
      </Card>

      {runError && <ErrorState message={runError} onRetry={start} />}

      {run && (
        <StatRow>
          <Stat
            label="confidence"
            value={run.validation_confidence.toFixed(2)}
            note={`over ${factCount(run)} dependencies`}
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
            value={run.decision_mode?.replace(/_/g, ' ') ?? 'unknown'}
            note={run.style_resolved ? `style ${run.style_resolved}` : undefined}
          />
          <Stat
            label="status"
            value={run.status}
            note={run.published_ref ? 'published' : 'nothing published'}
            tone={run.status === 'completed' ? 'ok' : 'warn'}
          />
        </StatRow>
      )}

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
        <div className="flex flex-col gap-7">
          <dl className="grid gap-6 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <dt className="text-xs tracking-wide text-ink-4">reads</dt>
              <dd className="text-sm text-ink-2">{selected.input}</dd>
            </div>
            <div className="flex flex-col gap-1.5">
              <dt className="text-xs tracking-wide text-ink-4">produces</dt>
              <dd className="text-sm text-ink-2">{selected.output}</dd>
            </div>
          </dl>

          {phase === 'validate' ? (
            <ValidateDetail
              isLoading={pipeline.isLoading}
              error={pipeline.error}
              onRetry={pipeline.reload}
              stageViews={stageViews}
              built={pipeline.data?.implemented_count ?? 0}
              total={pipeline.data?.stage_count ?? 0}
            />
          ) : (
            <p className="max-w-prose text-sm leading-relaxed text-ink-3">
              {selected.state === 'reserved'
                ? 'This phase runs in the backend. Its screen is reserved and not written yet — the pipeline draws it so that it is not forgotten.'
                : 'This phase has its own screen, which shows what it produced for the selected release.'}
            </p>
          )}
        </div>
      </Card>
    </>
  )
}

function ValidateDetail({
  isLoading,
  error,
  onRetry,
  stageViews,
  built,
  total,
}: {
  isLoading: boolean
  error: string | null
  onRetry: () => void
  stageViews: ReturnType<typeof toStageViews>
  built: number
  total: number
}) {
  if (error) return <ErrorState message={error} onRetry={onRetry} />
  if (isLoading) return <Spinner label="reading the stages" />
  if (stageViews.length === 0) {
    return <p className="text-sm text-ink-3">The backend reported no stages.</p>
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-4">
        <span className="font-mono text-xs text-ink-4">
          {built} of {total} stages built
        </span>
        <span className="font-mono text-xs text-ink-4">
          ◆ marks a stage that calls a model
        </span>
      </div>
      <StageTrack stages={stageViews} />
    </div>
  )
}

/** Reveal the stages one at a time, pausing longer on a model stage. */
async function reveal(
  run: ValidationRun,
  usesModel: boolean[],
  setRevealed: (value: number) => void,
) {
  for (let index = 0; index < run.stages.length; index += 1) {
    setRevealed(index)
    await wait(usesModel[index] ? MODEL_STAGE_MS : STAGE_MS)
  }

  setRevealed(run.stages.length)
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function factCount(run: ValidationRun): number {
  const classification = run.stages.find((stage) => stage.name === 'classification')
  return classification?.counts.facts ?? 0
}
