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
  listScoringRuns,
  messageOf,
  scoreDetectionRun,
  scoringRunId,
  type RepositoryConfiguration,
  type StageDescription,
  type ValidationRun,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { runKey, type DecisionChoice } from '../../workspace/context'
import { useWorkspace } from '../../workspace/useWorkspace'
import type {
  PipelinePhase,
  SnapshotPhase,
  SnapshotRun,
} from '../../workspace/pipeline'
import DetectionCard from './DetectionCard'
import ScoringCard from './ScoringCard'
import PipelineFlow, { type PhaseState } from './PipelineFlow'
import RecoveryStages from './RecoveryStages'
import ReleaseActions from './ReleaseActions'
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
    decisionChoices,
    validatingRelease,
    validateRelease,
    validateAllReleases,
    validationError,
    focusRelease,
    releases,
    degradation,
    isDetecting,
    isDetectionStale,
    detectionError,
    detectDegradation,
  } = useWorkspace()

  const described = useRequest((options) => describePipeline(options), [])

  const [selectedPhase, setSelectedPhase] = useState<PhaseId>('recover')

  // Rows a person flipped away from what the run would show them.
  //
  // The default is not a constant: a release being validated, or one that has
  // a result, is open, and a release waiting its turn is thin. So this records
  // *disagreement* with that rather than a set of closed rows - otherwise the
  // same list would mean "closed" on one row and "open" on the next.
  const [toggled, setToggled] = useState<string[]>([])

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
    setToggled((current) =>
      current.includes(configurationId)
        ? current.filter((id) => id !== configurationId)
        : [...current, configurationId],
    )

  // Starting a validation puts every row back to the state the run implies.
  // Done here rather than in an effect on `validatingRelease`: the thing that
  // changes the defaults is somebody pressing validate, and deriving it from
  // the state afterwards is a second render that says so.
  const validateOne = (releaseId: string) => {
    setToggled([])
    return validateRelease(releaseId)
  }

  const validateAll = async () => {
    setToggled([])
    await validateAllReleases()
  }

  // A run reaches this screen through the session's runs, not through the
  // snapshot, because the decisions screen is what started it.
  const validated = pipelineSnapshots.some((snapshot) => runFor(snapshot, runs))

  // Scoring ranks the current detection run, from its own card; the phase is
  // complete once that run has its ranking (`score-<detection run>`). A
  // ranking of an older run, or of hand-made events, does not count. "Current"
  // is what the detect phase calls fresh: over this session's validations.
  const scoring = useRequest((options) => listScoringRuns(options), [])
  const [isScoring, setIsScoring] = useState(false)
  const [scoringError, setScoringError] = useState<string | null>(null)
  const currentDetection = validated && degradation && !isDetectionStale ? degradation : null
  const ranking = currentDetection
    ? ((scoring.data ?? []).find(
        (run) => run.run_id === scoringRunId(currentDetection.run.run_id),
      ) ?? null)
    : null

  const score = async () => {
    if (!currentDetection) return
    setIsScoring(true)
    setScoringError(null)
    try {
      await scoreDetectionRun(currentDetection.run.system_id, currentDetection.run.run_id)
      scoring.reload()
    } catch (cause) {
      setScoringError(messageOf(cause))
    } finally {
      setIsScoring(false)
    }
  }

  const phaseStates = useMemo<Record<PhaseId, PhaseState>>(
    () => ({
      recover: recoverState(pipelinePhase, pipelineSnapshots, configurations.length),
      validate: validateState(pipelinePhase, validated),
      detect: detectState(
        isDetecting,
        detectionError,
        Boolean(degradation) && !isDetectionStale,
        validated,
      ),
      prioritise: scoringState(isScoring, scoringError, ranking !== null, currentDetection !== null),
    }),
    [
      pipelinePhase,
      pipelineSnapshots,
      validated,
      configurations.length,
      isDetecting,
      isDetectionStale,
      detectionError,
      degradation,
      isScoring,
      scoringError,
      ranking,
      currentDetection,
    ],
  )

  // Releases with a source picked for them: what the continue button runs.
  const ready = releases.filter((release) => decisionChoices[release])
  const isRecovered = pipelinePhase === 'recovered' || releases.length > 0

  const recover = async () => {
    setToggled([])

    // Recovery clones, so it is the expensive half and it happens once. The
    // first pass hands over to the decisions screen because nothing has been
    // chosen yet; afterwards there is nothing to go there for, and sending
    // somebody back to re-make a choice they already made is how a flow earns
    // the reputation of starting over.
    const recovered = await startPipeline()
    if (recovered && ready.length === 0) navigate('/decisions')
  }

  const phase = PHASES.find((item) => item.id === selectedPhase)!

  // Once something is validated, detecting is the next thing to do, so it
  // takes the primary button and validating steps back. "Again" only for a run
  // that already describes this stack.
  const detectIsNext = validated && (!degradation || isDetectionStale)
  const hasFreshDetection = validated && Boolean(degradation) && !isDetectionStale

  return (
    <>
      <PageHeading
        eyebrow="analysis"
        title="Pipeline"
        description="Four phases. Recovery clones and analyses every configured release; validation then judges each one against the source chosen for it."
        action={
          <div className="flex flex-wrap items-center gap-5">
            {validatingRelease && <Spinner label={`validating ${validatingRelease}`} />}
            {isPipelineRunning && <Spinner label="recovering" />}
            {isDetecting && <Spinner label="detecting" />}
            {isScoring && <Spinner label="scoring" />}

            {isRecovered && (
              <Button
                size="sm"
                variant="quiet"
                disabled={isPipelineRunning || Boolean(validatingRelease)}
                onClick={recover}
              >
                Recover again
              </Button>
            )}

            <Button
              variant={detectIsNext || hasFreshDetection ? undefined : 'primary'}
              disabled={
                isPipelineRunning ||
                Boolean(validatingRelease) ||
                (isRecovered ? ready.length === 0 : configurations.length === 0)
              }
              onClick={isRecovered ? validateAll : recover}
            >
              {/* Not "run again". That reads as starting the whole thing over,
                  and the thing it would start over is the cloning - which is
                  the half that is already done and the half that costs
                  minutes. What is left is validation. */}
              {isRecovered
                ? `Validate ${ready.length} release${ready.length === 1 ? '' : 's'}`
                : 'Run recovery'}
            </Button>

            {validated && (
              <Button
                variant={detectIsNext ? 'primary' : undefined}
                disabled={isPipelineRunning || Boolean(validatingRelease) || isDetecting}
                onClick={() => void detectDegradation()}
              >
                {isDetecting
                  ? 'Detecting…'
                  : hasFreshDetection
                    ? 'Detect again'
                    : 'Detect degradation'}
              </Button>
            )}

            {hasFreshDetection &&
              (ranking ? (
                <Button
                  variant="primary"
                  onClick={() => navigate(`/priorities?run=${encodeURIComponent(ranking.run_id)}`)}
                >
                  Open priorities
                </Button>
              ) : (
                <Button variant="primary" disabled={isScoring} onClick={() => void score()}>
                  {isScoring ? 'Scoring…' : 'Score'}
                </Button>
              ))}
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
        toggled={toggled}
        activeId={activeId}
        runs={runs}
        releases={releases}
        decisionChoices={decisionChoices}
        validatingRelease={validatingRelease}
        onValidate={validateOne}
        onFocus={focusRelease}
        isRunning={isPipelineRunning}
        stagesDescribed={described.data?.stages ?? []}
        onAdd={addConfiguration}
        onRemove={removeConfiguration}
        onToggle={toggle}
      />

      {validationError && <ErrorState message={validationError} />}

      <JudgedAgainst
        phase={pipelinePhase}
        isRunning={isPipelineRunning}
        chosen={
          configurations.filter(
            (configuration) => decisionChoices[configuration.release_tag],
          ).length
        }
        total={configurations.length}
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
                : phase.id === 'detect'
                  ? 'Detection reads the graph validation published for every release, finds the anti-patterns in each, and tests across the releases whether they are getting worse. It is started from its own card below, once the releases somebody wants compared are validated.'
                  : phase.id === 'prioritise'
                  ? 'Scoring reads what the detect phase found, adds how far each problem reaches, how actively its code changes, whether it breaks a recorded decision and how long it has lasted, and ranks the problems with a reason for each. It is started from its card below once detection has run; open the result to read the ranking.'
                  : 'Validation is started on the decisions screen, once somebody has chosen what these releases are judged against. The pipeline recovers the stack and stops there.'}
          </p>
        </div>
      </Card>

      {/* Shown from recovery on, not only after a validation in this session:
          validations are stored, so a refresh must not hide the button. If
          nothing is validated the backend says so in its own words. */}
      {isRecovered && (
        <DetectionCard
          report={degradation}
          isDetecting={isDetecting}
          error={detectionError}
          canDetect={releases.length > 0}
          isStale={!validated || isDetectionStale}
          onDetect={() => void detectDegradation()}
          onFocus={focusRelease}
        />
      )}

      {isRecovered && (
        <ScoringCard
          events={currentDetection ? currentDetection.events.length : null}
          ranking={ranking}
          isScoring={isScoring}
          error={scoringError}
          canScore={currentDetection !== null}
          onScore={() => void score()}
        />
      )}

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
            <Elsewhere
              to="/drift"
              title="Drift"
              body="Every release in turn, its anti-patterns, and what is getting worse."
            />
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
  toggled,
  activeId,
  runs,
  releases,
  decisionChoices,
  validatingRelease,
  onValidate,
  onFocus,
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
  /** Rows flipped away from the state the run implies for them. */
  toggled: string[]
  /** The snapshot currently moving, which is the only one left expanded. */
  activeId: string | null
  runs: Record<string, ValidationRun>
  /** The releases recovery has stored, which outlive this session's run. */
  releases: string[]
  decisionChoices: Record<string, DecisionChoice>
  /** The release being validated right now, so only its button spins. */
  validatingRelease: string | null
  onValidate: (releaseId: string) => Promise<boolean>
  onFocus: (releaseId: string) => void
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

            // Recovered in *any* session, not only this one. A refresh empties
            // the in-memory run and would otherwise hide the validate button
            // for a release the backend has stored all along.
            const isRecovered =
              snapshot?.phase === 'recovered' ||
              releases.includes(configuration.release_tag)
            const hasDetails = Boolean(snapshot?.recovery || run)

            // Expanded when this release is the one moving, or when it has
            // a result to read. A release still waiting stays thin - and thin
            // is not empty: its row keeps the decision it will be judged
            // against, the validate button and the links, which is what
            // somebody scanning fifty rows actually needs from it.
            const isMoving =
              validatingRelease === configuration.release_tag ||
              (isRunning && activeId === configuration.id)
            const openByDefault = isMoving || Boolean(run)

            const isOpen =
              hasDetails &&
              (toggled.includes(configuration.id) ? !openByDefault : openByDefault)

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
                        {configuration.branch} ·{' '}
                        <span className="rounded bg-field px-1.5 py-0.5 text-ink-2">
                          {configuration.release_tag}
                        </span>
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <SnapshotStatus
                      phase={isRecovered ? 'recovered' : phase}
                      isValidating={
                        validatingRelease === configuration.release_tag
                      }
                      isValidated={Boolean(run)}
                    />
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

                {isRecovered && (
                  <ReleaseActions
                    release={configuration.release_tag}
                    choice={decisionChoices[configuration.release_tag]}
                    run={run}
                    isRecovered={isRecovered}
                    isValidating={validatingRelease === configuration.release_tag}
                    onValidate={() => onValidate(configuration.release_tag)}
                    onFocus={onFocus}
                  />
                )}

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

/**
 * Where one release has got to, as one word.
 *
 * It reports the **validation** state where there is one, because recovery is
 * the thing that already happened and judging is the thing somebody is
 * waiting on. A stack of fifty rows is scanned down this column, and a
 * release that has been judged reading `recovered` makes the column useless
 * for the question it is there to answer.
 */
function SnapshotStatus({
  phase,
  isValidating,
  isValidated,
}: {
  phase: SnapshotPhase
  isValidating: boolean
  isValidated: boolean
}) {
  if (isValidating) return <Pill tone="ai">validating</Pill>
  if (isValidated) return <Pill tone="ok">judged</Pill>

  const tone = {
    queued: 'neutral',
    ingesting: 'ai',
    recovering: 'ai',
    recovered: 'warn',
    failed: 'bad',
  }[phase] as 'neutral' | 'ok' | 'bad' | 'ai' | 'warn'

  // `recovered` is amber rather than green on purpose: the release exists and
  // nothing has judged it, which is a state somebody still has to act on.
  return <Pill tone={tone}>{phase === 'recovered' ? 'not judged' : label(phase)}</Pill>
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
  chosen,
  total,
}: {
  phase: PipelinePhase
  isRunning: boolean
  /** How many releases have a source picked for them. */
  chosen: number
  total: number
}) {
  // Recovered and not yet judged is the only moment this is the next thing to
  // do. The pipeline phase stays `recovered` after the decisions screen has
  // run, so without this the card would go on asking for a choice already made.
  // Only while something is still undecided. The pipeline phase stays
  // `recovered` after the decisions screen has run, so without counting the
  // choices this card would go on asking for ones already made.
  const isWaiting = phase === 'recovered' && !isRunning && chosen < total

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
            ? `${total - chosen} of ${total} releases have no source chosen yet. A release cannot be validated until somebody picks what judges it.`
            : 'Each release is judged against the source chosen for it, and validated from its own row below. A release judged against a source nobody picked reports that nothing contradicts it, which is indistinguishable from a healthy system.'}
        </p>

        <Link to="/decisions">
          <Button variant={isWaiting ? 'primary' : undefined}>
            {isWaiting ? 'Choose the sources' : 'Open decisions'}
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

/**
 * The detect node.
 *
 * **It follows the order, like every other node.** Detection reads what
 * validation published, so it is `blocked` until something has been validated
 * in this run - a stored detection from an earlier session describes an
 * earlier stack, and drawing it green beside an unjudged one would say this
 * stack had been checked when it had not.
 *
 * Then `waiting` until somebody detects, and `done` only for a run made after
 * the last validation. Validating another release makes it `waiting` again:
 * the stored run did not read that release.
 */
function detectState(
  isDetecting: boolean,
  error: string | null,
  hasFreshRun: boolean,
  validated: boolean,
): PhaseState {
  if (isDetecting) return 'running'
  if (!validated) return 'blocked'
  if (error) return 'failed'
  return hasFreshRun ? 'done' : 'waiting'
}

function scoringState(
  isScoring: boolean,
  error: string | null,
  hasRanking: boolean,
  hasDetection: boolean,
): PhaseState {
  if (isScoring) return 'running'
  if (!hasDetection) return 'blocked'
  if (error) return 'failed'
  return hasRanking ? 'done' : 'waiting'
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
