/**
 * Validation screen.
 *
 * Description:
 *   Everything the validation phase did for one release, in one place: what
 *   it read, what it judged, who judged it, and what checked that judgement.
 *   The pipeline shows that it ran; this shows how.
 *
 *   **Three judges, and only two of them are models.** A language model
 *   reaches a verdict, a different model is asked what is wrong with it, and
 *   a table with no model in it decides whether they are believed. That
 *   difference is the component's main claim and the easiest thing to lose on
 *   a screen, so the three are drawn side by side with the model names on
 *   them and the third one visibly not a model.
 *
 *   **An absent check never looks like a passed check.** A stage that was
 *   skipped says so and says why; verification that did not run is reported
 *   as not run rather than as agreement. Those two sentences are the whole
 *   reason this screen exists rather than a row on the pipeline.
 *
 *   **Whether a model was involved is shown rather than claimed.** With no
 *   key the ladder ends at a deterministic table, every governed fact still
 *   gets a verdict, and the two runs publish the same buckets - so the
 *   transcript panel carries the calls themselves, and the probe beside it
 *   asks the configured models a question now.
 *
 *   It links out rather than growing: the verdicts are on Findings, the
 *   picture is on Canvas, what it was judged against is on Decisions.
 */

import { Link } from 'react-router'
import {
  Button,
  Card,
  EmptyState,
  PageHeading,
  Pill,
  Spinner,
  Stat,
  StatRow,
} from '../../components/ui'
import {
  describePipeline,
  readPublishedGraph,
  type PublishedGraph,
  type StageDescription,
  type StageRecord,
  type ValidationRun,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { runKey } from '../../workspace/context'
import { useReleases } from '../../workspace/useReleases'
import { useWorkspace } from '../../workspace/useWorkspace'
import ReleasePicker from '../../components/ReleasePicker'
import ModelComparison from './ModelComparison'
import ModelEvidence from './ModelEvidence'
import RunNarrative from './RunNarrative'

export default function ValidationPage() {
  const { repository, repositoryKey, runs } = useWorkspace()
  const { releases, release, selectRelease } = useReleases()
  const run = runs[runKey(repositoryKey, release)] ?? null

  const published = useRequest(
    (options) => readPublishedGraph(repositoryKey, release ?? '', options),
    [repositoryKey, release, run?.run_id],
    Boolean(repository && release),
  )

  // What each stage is for, in the backend's own words. Written there rather
  // than here so a stage that changes its job does not leave a sentence
  // behind on a screen nobody thought to update.
  const pipeline = useRequest((options) => describePipeline(options), [])

  if (!repository || releases.length === 0) {
    return (
      <>
        <PageHeading eyebrow="judging" title="Validation" />
        <Card>
          <EmptyState
            title={repository ? 'No recovered release yet' : 'No system selected'}
            body="Validation reads a recovered architecture and the decisions recorded about it, so both have to exist first."
            action={
              <Link to={repository ? '/' : '/repositories'}>
                <Button variant="primary">
                  {repository ? 'Run the pipeline' : 'Add a repository'}
                </Button>
              </Link>
            }
          />
        </Card>
      </>
    )
  }

  const document = published.data

  return (
    <>
      <PageHeading
        eyebrow="judging"
        title="Validation"
        description={`What was judged about ${release}, who judged it, and what checked that judgement.`}
        action={
          <div className="flex flex-wrap items-center gap-5">
            <ReleasePicker releases={releases} value={release} onChange={selectRelease} />
            <Link to="/">
              <Button size="sm" variant="quiet">
                Back to the pipeline
              </Button>
            </Link>
            <Link to="/">
              <Button variant="primary">{run ? 'Run again' : 'Start validation'}</Button>
            </Link>
          </div>
        }
      />

      {published.isLoading && <Spinner label="reading the published result" />}

      {!published.isLoading && !document && (
        <Card>
          <EmptyState
            title="This release has not been validated yet"
            body={
              published.error ??
              'Choose what it should be judged against, and the run starts from there.'
            }
            action={
              <Link to="/decisions">
                <Button variant="primary">Choose what to validate it against</Button>
              </Link>
            }
          />
        </Card>
      )}

      {document && (
        <>
          <Outcome document={document} />
          <Judges document={document} run={run} />
          <ModelComparison document={document} />
        </>
      )}

      {/* Outside the block above on purpose. Whether this machine can reach a
          model is the first question asked when a release has *not* been
          validated, and hiding it behind a published document would put the
          answer out of reach exactly when it is wanted. */}
      <ModelEvidence
        repositoryKey={repositoryKey}
        release={release ?? ''}
        runId={run?.run_id}
      />

      {document && (
        <>
          <RunNarrative repositoryKey={repositoryKey} release={release ?? ''} />
          {run ? (
            <Stages run={run} describedBy={pipeline.data?.stages ?? []} />
          ) : (
            <NoStageRecord />
          )}
          <Elsewhere />
        </>
      )}
    </>
  )
}

/** The result, before any of the machinery that produced it. */
function Outcome({ document }: { document: PublishedGraph }) {
  const counts = document.links.reduce(
    (counts, edge) => {
      const bucket = edge.bucket.toLowerCase()
      if (bucket.includes('confirm')) counts.confirmed += 1
      else if (bucket.includes('contradict')) counts.contradicted += 1
      else if (bucket.includes('uncovered')) counts.uncovered += 1
      // Deliberately not a bucket. Which facts reach a person is the route,
      // and reading it off the bucket reported zero every time: no bucket is
      // ever named "review", so the only count that could come out of that
      // test was none held back at all.
      if (edge.route === 'review') counts.review += 1
      return counts
    },
    { confirmed: 0, contradicted: 0, review: 0, uncovered: 0 },
  )

  // A document published before schema 1.2.0 carries no route on its edges,
  // and it does carry the count in its summary. Reading that rather than
  // printing zero, because zero is the wrong answer this stat is being fixed
  // for and an old document would have gone on giving it.
  const review = document.links.some((edge) => edge.route)
    ? counts.review
    : Number(document.graph.summary?.review ?? 0)

  // A model is behind a verdict it produced, whether or not this run paid for
  // the call. Counting calls instead reported one fact in seventeen on a
  // warmed cache, four lines above a panel saying sixteen came from a model.
  // Read off the document rather than written here, so the scale cannot
  // drift from the scoring that produced the number.
  const ceiling =
    document.links.find((edge) => edge.confidence_maximum > 0)?.confidence_maximum ??
    0.85

  const withModel = document.links.filter((edge) => edge.produced_by === 'model').length
  const liveCalls = document.links.reduce((total, edge) => total + edge.model_calls, 0)

  return (
    <StatRow>
      <Stat
        label="dependencies judged"
        value={document.links.length}
        note={`${counts.confirmed} confirmed · ${withModel} with a model behind them · ${liveCalls} live call${
          liveCalls === 1 ? '' : 's'
        } this run`}
      />
      {/* The finding the component exists to produce, and it was computed
          and then not shown: the summary counted confirmations, held-back
          facts and ungoverned ones, and left out the only row anybody came
          to this screen to read. */}
      <Stat
        label="contradicted"
        value={counts.contradicted}
        note={
          counts.contradicted > 0
            ? 'runs against the recorded intent'
            : 'nothing runs against the recorded intent'
        }
        tone={counts.contradicted > 0 ? 'bad' : 'ok'}
      />
      {/* The scale, not just the value. 0.85 is the most this method
          publishes for anything, so a release where every fact is strongly
          evidenced and fully checked reads 0.85 - and "0.85" alone looks
          like a number that failed to reach 1.00 rather than one that
          reached the top. */}
      <Stat
        label="how sure of the verdicts"
        value={`${document.graph.validation_confidence.toFixed(2)} / ${ceiling.toFixed(2)}`}
        note={
          document.graph.validation_confidence >= ceiling
            ? 'every dependency is as certain as this method gets'
            : `the mean across this release · ${ceiling.toFixed(2)} is the maximum`
        }
        tone={document.graph.validation_confidence > 0 ? 'ok' : 'neutral'}
      />
      <Stat
        label="needs a person"
        value={review}
        note={
          counts.uncovered > 0
            ? `held back rather than claimed · ${counts.uncovered} governed by nothing`
            : 'held back rather than claimed · every dependency is governed'
        }
        tone={review > 0 ? 'warn' : 'neutral'}
      />
    </StatRow>
  )
}

/**
 * The three judges, with the two that are models named.
 *
 * The verifier's box is filled from the run's own counts rather than from the
 * verdicts, because "nobody asked" and "it could not be reached" are
 * different facts and only the run record tells them apart.
 */
function Judges({
  document,
  run,
}: {
  document: PublishedGraph
  run: ValidationRun | null
}) {
  const stamp = document.graph.run
  const verification = stage(run, 'independent_verification')
  const reasoning = stage(run, 'validation_reasoning')

  return (
    <Card
      title="Who judged it"
      action={
        <span className="font-mono text-xs text-ink-4">
          prompts {stamp?.prompt_versions?.join(', ') || 'none recorded'}
        </span>
      }
    >
      <div className="grid gap-7 lg:grid-cols-3">
        <Judge
          role="reaches the verdict"
          model={stamp?.reasoner_model}
          tone="ai"
          lines={[
            `${reasoning?.counts.verdicts ?? 0} verdicts`,
            `${reasoning?.counts.from_model ?? 0} from the model`,
            `${reasoning?.counts.from_cache ?? 0} from cache`,
            `${reasoning?.counts.from_arbiter ?? 0} from the table alone`,
          ]}
          note={reasoning?.note}
        />

        <Judge
          role="asked what is wrong with it"
          model={stamp?.verifier_model}
          tone="ai"
          lines={[
            `${verification?.counts.verifications ?? 0} checked`,
            `${verification?.counts.agreed ?? 0} agreed`,
            `${verification?.counts.disagreed ?? 0} objected`,
            `${verification?.counts.uncertain ?? 0} uncertain`,
          ]}
          note={verification?.note}
        />

        <Judge
          role="decides whether they are believed"
          model={null}
          tone="neutral"
          lines={[
            'a table, not a model',
            'it cannot invent a rule',
            `${reasoning?.counts.guard_rejections ?? 0} answers rejected by a guard`,
            `${reasoning?.counts.insufficient_evidence ?? 0} refused for want of evidence`,
          ]}
        />
      </div>

      <p className="mt-7 max-w-prose border-t border-line pt-6 text-sm leading-relaxed text-ink-3">
        Agreement between the two models is not evidence that they are right.
        Where they agreed and the table disagreed, the finding is held for a
        person rather than published either way — and that count is reported
        whether or not anybody asks for it.
      </p>
    </Card>
  )
}

function Judge({
  role,
  model,
  tone,
  lines,
  note,
}: {
  role: string
  model: string | null | undefined
  tone: 'ai' | 'neutral'
  lines: string[]
  note?: string | null
}) {
  return (
    <div
      className={`flex flex-col gap-4 rounded-card border p-6 ${
        tone === 'ai' ? 'border-ai/40' : 'border-line'
      }`}
    >
      <span className="text-xs tracking-wide text-ink-4">{role}</span>

      {model ? (
        <Pill tone="ai">{model}</Pill>
      ) : (
        <Pill>no model</Pill>
      )}

      <ul className="flex flex-col gap-1.5">
        {lines.map((line) => (
          <li key={line} className="font-mono text-xs text-ink-2">
            {line}
          </li>
        ))}
      </ul>

      {note && <p className="text-xs leading-relaxed text-warn">{note}</p>}
    </div>
  )
}

/**
 * Every stage, with what it is for, what it counted and why it was skipped.
 *
 * One block per stage rather than a row, because the interesting part is
 * never the status: it is the counts, and a skipped stage's reason. Those
 * read as sentences at this size and as noise in a table.
 */
function Stages({
  run,
  describedBy,
}: {
  run: ValidationRun
  describedBy: StageDescription[]
}) {
  const described = new Map(describedBy.map((stage) => [stage.name, stage]))

  return (
    <Card
      title="What each stage did"
      action={
        <span className="font-mono text-xs text-ink-4">
          run {run.run_id} · {run.status}
        </span>
      }
    >
      <ol className="flex flex-col gap-px bg-line">
        {run.stages.map((record, index) => (
          <Stage
            key={record.name}
            index={index}
            record={record}
            describedBy={described.get(record.name)}
          />
        ))}
      </ol>
    </Card>
  )
}

function Stage({
  index,
  record,
  describedBy,
}: {
  index: number
  record: StageRecord
  describedBy?: StageDescription
}) {
  const counts = Object.entries(record.counts)
  const reported = counts.filter(([, value]) => value !== 0)

  return (
    <li className="flex flex-col gap-5 bg-panel px-1 py-7 first:pt-1 last:pb-1">
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div className="flex min-w-0 items-start gap-4">
          <span className="mt-0.5 font-mono text-xs text-ink-4">
            {String(index + 1).padStart(2, '0')}
          </span>
          <div className="flex min-w-0 flex-col gap-1.5">
            <span className="text-sm font-medium text-ink">
              {record.name.replace(/_/g, ' ')}
            </span>
            {describedBy && (
              <span className="max-w-prose text-xs leading-relaxed text-ink-3">
                {describedBy.role}
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2.5">
          {describedBy?.uses_model && <Pill tone="ai">calls a model</Pill>}
          <StageStatus status={record.status} />
          <span className="font-mono text-[11px] text-ink-4">{record.duration_ms} ms</span>
        </div>
      </div>

      {reported.length > 0 && (
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-3 lg:grid-cols-4">
          {reported.map(([key, value]) => (
            <div key={key} className="flex flex-col gap-1 bg-panel px-4 py-3">
              <dt className="text-[11px] leading-tight text-ink-4">
                {key.replace(/_/g, ' ')}
              </dt>
              <dd className="font-mono text-lg leading-none text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {reported.length === 0 && record.status === 'completed' && (
        <p className="font-mono text-xs text-ink-4">
          ran and counted nothing, which is a result rather than a gap
        </p>
      )}

      {record.note && (
        <p className="max-w-prose border-l-2 border-warn/60 pl-4 text-xs leading-relaxed text-warn">
          {record.note}
        </p>
      )}

      {record.warnings.length > 0 && (
        <ul className="flex flex-col gap-2">
          {record.warnings.map((warning) => (
            <li
              key={warning}
              className="max-w-prose border-l-2 border-line-strong pl-4 text-xs leading-relaxed text-ink-3"
            >
              {warning}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function StageStatus({ status }: { status: StageRecord['status'] }) {
  const tone = {
    completed: 'ok',
    skipped: 'neutral',
    pending: 'neutral',
    failed: 'bad',
  }[status] as 'ok' | 'neutral' | 'bad'

  return <Pill tone={tone}>{status}</Pill>
}

/**
 * The published document outlives the session that produced it.
 *
 * Saying so is better than an empty panel: a reader who opened this screen
 * after a refresh has not lost the result, only the record of the run.
 */
function NoStageRecord() {
  return (
    <Card title="What each stage did">
      <EmptyState
        title="No run record in this session"
        body="The result above was read from the published document, which outlives the run that wrote it. Run the release again to watch the stages."
        action={
          <Link to="/decisions">
            <Button>Run it again</Button>
          </Link>
        }
      />
    </Card>
  )
}

/** Where the rest of this result lives, rather than repeating it here. */
function Elsewhere() {
  const links = [
    {
      to: '/findings',
      title: 'Findings',
      body: 'Every dependency with its verdict, confidence and the evidence behind it.',
    },
    {
      to: '/canvas',
      title: 'Canvas',
      body: 'The validated architecture graph — the artifact the next phase reads — with the verdict drawn on the dependency it is about.',
    },
    {
      to: '/decisions',
      title: 'Decisions',
      body: 'What this release was judged against, and what each source would have supplied.',
    },
    {
      to: '/architecture',
      title: 'Architecture',
      body: 'The input: the system as recovery found it, before anything judged it.',
    },
  ]

  return (
    <Card title="The rest of this result">
      <div className="grid gap-5 sm:grid-cols-2">
        {links.map((link) => (
          <Link
            key={link.to}
            to={link.to}
            className="flex flex-col gap-2 rounded-control border border-line px-6 py-5 transition hover:border-line-strong"
          >
            <span className="text-sm font-medium text-ink">{link.title} →</span>
            <span className="text-xs leading-relaxed text-ink-3">{link.body}</span>
          </Link>
        ))}
      </div>
    </Card>
  )
}

function stage(run: ValidationRun | null, name: string): StageRecord | undefined {
  return run?.stages.find((record) => record.name === name)
}
