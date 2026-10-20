/**
 * Drift screen.
 *
 * Description:
 *   Every validated release of one system, one after another, with the
 *   anti-patterns found in each - and across them, which measures are getting
 *   worse with the evidence to say so.
 *
 *   Read top to bottom it answers three questions in order: *which releases
 *   is this about* (the strip), *what does each one look like and what is
 *   wrong with it* (the graph and its anti-patterns), and *what is getting
 *   worse* (the trends, and the events handed on).
 *
 *   **The graph is the validated one.** Every release here is the graph the
 *   validation phase published for it, drawn with the same component as the
 *   canvas and in fixed positions across releases, so stepping through them
 *   reads as one system changing.
 *
 *   Detection is started here or from the pipeline; both read the same stored
 *   run through the workspace, so the two screens cannot disagree.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import GraphCanvas, { GraphKey } from '../../components/graph/GraphCanvas'
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
import type { DegradationReport, IngestOutcome } from '../../lib/api'
import { useWorkspace } from '../../workspace/useWorkspace'
import AntiPatternTable from './AntiPatternTable'
import EventsHandover from './EventsHandover'
import ReleaseStrip from './ReleaseStrip'
import TrendCharts from './TrendCharts'
import { releaseGraph, runLayout } from './graphs'

export default function DriftPage() {
  const {
    repository,
    degradation,
    degradationIngest,
    isLoadingDegradation,
    isDetecting,
    detectionError,
    detectDegradation,
  } = useWorkspace()

  const heading = (
    <PageHeading
      eyebrow="over time"
      title="Drift"
      description="Every validated release of this system in order, the anti-patterns found in each, and which measures are getting worse with the evidence to say so."
      action={
        <div className="flex flex-wrap items-center gap-5">
          {isDetecting && <Spinner label="detecting" />}
          <Link to="/">
            <Button size="sm" variant="quiet">
              Back to the pipeline
            </Button>
          </Link>
          {repository && (
            <Button
              variant={degradation ? undefined : 'primary'}
              disabled={isDetecting}
              onClick={() => void detectDegradation()}
            >
              {degradation ? 'Detect again' : 'Detect degradation'}
            </Button>
          )}
        </div>
      }
    />
  )

  if (!repository) {
    return (
      <>
        {heading}
        <Card>
          <EmptyState
            title="No system selected"
            body="Drift is measured across the validated releases of one system, so a repository has to have been added and validated first."
            action={
              <Link to="/repositories">
                <Button variant="primary">Add a repository</Button>
              </Link>
            }
          />
        </Card>
      </>
    )
  }

  return (
    <>
      {heading}

      {detectionError && <ErrorState message={detectionError} />}

      <Intake outcomes={degradationIngest} />

      {isLoadingDegradation && !degradation && <Spinner label="reading the latest run" />}

      {!isLoadingDegradation && !degradation && !detectionError && (
        <Card>
          <EmptyState
            title="Degradation has not been detected for this system"
            body="Detection reads every release of this system that has been validated, finds the anti-patterns in each, and tests whether they are getting worse. Validate the releases first, then detect."
            action={
              <Button variant="primary" disabled={isDetecting} onClick={() => void detectDegradation()}>
                Detect degradation
              </Button>
            }
          />
        </Card>
      )}

      {degradation && <Run report={degradation} />}
    </>
  )
}

/** Which published graphs went in, and what refused the rest. */
function Intake({ outcomes }: { outcomes: IngestOutcome[] }) {
  const refused = outcomes.filter((outcome) => !outcome.accepted)
  if (refused.length === 0) return null

  return (
    <Card title="Not every validated release could be read" action={<Pill tone="warn">{refused.length} refused</Pill>}>
      <ul className="flex flex-col gap-3">
        {refused.map((outcome) => (
          <li key={outcome.source} className="flex flex-wrap items-baseline gap-3 text-sm">
            <span className="font-mono text-ink">{outcome.release_id ?? outcome.source}</span>
            <span className="font-mono text-xs text-warn">{outcome.reason}</span>
            <span className="text-xs text-ink-3">{outcome.detail}</span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Run({ report }: { report: DegradationReport }) {
  const timeline = report.releases.filter((release) => release.on_timeline)
  const layout = useMemo(() => runLayout(report), [report])

  const [chosen, setChosen] = useState<string | null>(null)
  const [compare, setCompare] = useState(true)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  const { focusedRelease } = useWorkspace()

  // A local choice, then the release a link from the pipeline pointed at, then
  // the newest - which is what somebody arriving here almost always means.
  const at = (releaseId: string | null) =>
    timeline.findIndex((item) => item.release_id === releaseId)
  const position = [at(chosen), at(focusedRelease), timeline.length - 1].find(
    (candidate) => candidate >= 0,
  ) ?? 0
  const release = timeline[position] ?? null
  const previous = position > 0 ? timeline[position - 1] : null

  const focus = release?.instances.find((instance) => instance.local_instance_id === focusId) ?? null

  const drawing = useMemo(
    () =>
      release
        ? releaseGraph(release, layout, { previous: compare ? previous : null, focus })
        : null,
    [release, previous, layout, compare, focus],
  )

  const select = (releaseId: string) => {
    setChosen(releaseId)
    setFocusId(null)
    setSelected(null)
  }

  const step = (by: number) => {
    const next = timeline[position + by]
    if (next) select(next.release_id)
  }

  const degrading = report.trends.filter((trend) => trend.is_worsening && trend.is_significant)
  const last = timeline[timeline.length - 1]

  return (
    <>
      <StatRow>
        <Stat
          label="releases"
          value={timeline.length}
          note={`on the timeline · trends need ${report.run.trend.min_releases}`}
          tone={timeline.length >= report.run.trend.min_releases ? 'neutral' : 'warn'}
        />
        <Stat
          label="anti-patterns"
          value={last?.instances.length ?? 0}
          note={last ? `in ${last.release_id}, the latest` : undefined}
          tone={last?.instances.length ? 'bad' : 'ok'}
        />
        <Stat
          label="getting worse"
          value={degrading.length}
          note={`of ${report.trends.length} series tested · ${report.untested.length} not tested`}
          tone={degrading.length ? 'bad' : 'neutral'}
        />
        <Stat
          label="events handed on"
          value={report.events.length}
          note="to the scoring phase"
          tone={report.events.length ? 'ai' : 'neutral'}
        />
      </StatRow>

      <Card
        title="Releases"
        action={<span className="font-mono text-xs text-ink-4">in release order · choose one to draw it</span>}
      >
        <ReleaseStrip releases={report.releases} selected={release?.release_id ?? null} onSelect={select} />
      </Card>

      {release && drawing && (
        <Card
          title={
            <div className="flex flex-wrap items-center gap-4">
              <h2 className="text-sm font-semibold">{release.release_id}</h2>
              <span className="font-mono text-xs text-ink-4">
                {position + 1} of {timeline.length}
              </span>
            </div>
          }
          action={
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-ink-3">
                <input
                  type="checkbox"
                  checked={compare}
                  onChange={(event) => setCompare(event.target.checked)}
                  disabled={!previous}
                  className="accent-ai"
                />
                {previous ? `compare with ${previous.release_id}` : 'first release'}
              </label>
              <Button size="sm" disabled={position === 0} onClick={() => step(-1)}>
                ← Earlier
              </Button>
              <Button size="sm" disabled={position >= timeline.length - 1} onClick={() => step(1)}>
                Later →
              </Button>
            </div>
          }
        >
          <p className="mb-6 max-w-prose text-sm leading-relaxed text-ink-3">
            The graph the validation phase published for {release.release_id}, with every
            element that takes part in an anti-pattern marked.
            {compare && previous
              ? ` Against ${previous.release_id}: ${drawing.added} element${drawing.added === 1 ? '' : 's'} new, ${drawing.removed} gone.`
              : ''}{' '}
            Every release is drawn in the same positions, so what moves is what changed.
          </p>
          <GraphCanvas
            nodes={drawing.nodes}
            edges={drawing.edges}
            layout={layout}
            selected={selected}
            onSelect={setSelected}
            legend={
              <>
                <GraphKey tone="bad">in an anti-pattern · edge inside a cycle</GraphKey>
                {compare && previous && <GraphKey tone="ai">new since {previous.release_id}</GraphKey>}
                {compare && previous && (
                  <GraphKey tone="faint" dashed>
                    gone since {previous.release_id}
                  </GraphKey>
                )}
              </>
            }
          />
        </Card>
      )}

      {release && (
        <Card
          title={`Anti-patterns in ${release.release_id}`}
          action={
            focus ? (
              <Button size="sm" variant="quiet" onClick={() => setFocusId(null)}>
                Show every element
              </Button>
            ) : (
              <span className="font-mono text-xs text-ink-4">choose a row to find it on the graph</span>
            )
          }
        >
          <AntiPatternTable release={release} focus={focusId} onFocus={setFocusId} />
        </Card>
      )}

      <Card title="Drift over time">
        <TrendCharts report={report} />
      </Card>

      <EventsHandover report={report} />

      <RunStamp report={report} />
    </>
  )
}

/** What produced every number on this screen, so any of them can be traced back. */
function RunStamp({ report }: { report: DegradationReport }) {
  const { run } = report
  const timings = Object.entries(run.timings)

  return (
    <Card title="This run" action={<Pill tone={run.status === 'COMPLETED' ? 'ok' : 'bad'}>{run.status.toLowerCase()}</Pill>}>
      <dl className="grid gap-7 sm:grid-cols-2 lg:grid-cols-4">
        <Term term="run" value={run.run_id} />
        <Term term="finished" value={run.finished_at?.replace('T', ' ').slice(0, 19) ?? '—'} />
        <Term term="configuration" value={run.config_hash.replace('sha256:', '').slice(0, 12)} note={`trends need ${run.trend.min_releases} releases · gate ${run.gate.exclude}–${run.gate.accept}`} />
        <Term term="code" value={run.code_version} />
      </dl>
      {timings.length > 0 && (
        <p className="mt-6 border-t border-line pt-5 font-mono text-xs text-ink-4">
          {timings.map(([stage, seconds]) => `${stage} ${(seconds * 1000).toFixed(0)}ms`).join(' · ')}
        </p>
      )}
    </Card>
  )
}

function Term({ term, value, note }: { term: string; value: string; note?: string }) {
  return (
    <div className="flex flex-col gap-2">
      <dt className="text-xs tracking-wide text-ink-4">{term}</dt>
      <dd className="font-mono text-sm break-all text-ink-2">{value}</dd>
      {note && <dd className="text-xs text-ink-4">{note}</dd>}
    </div>
  )
}
