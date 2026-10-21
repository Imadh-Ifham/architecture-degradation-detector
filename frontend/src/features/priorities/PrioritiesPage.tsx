/**
 * Priorities screen.
 *
 * Description:
 *   What degraded, ranked by how much it matters, read from a saved severity
 *   report - the same file the report page and the run manifest describe.
 *
 *   **Written for somebody seeing it for the first time.** The page says how
 *   to read itself before it shows anything: where the list came from, what a
 *   score means, and the recipe every score is made with. Each row then says,
 *   in a sentence, why it ranks where it does; opening it shows the arithmetic.
 *
 *   **Where the numbers came from is said first.** A ranking built from
 *   hand-made or synthetic events carries a banner above everything else.
 *
 *   **Nothing is dropped.** Events that could not be scored are listed with
 *   the reason, and the funnel at the top adds up to everything that came in.
 *
 *   **A ranking can be held against another** of the same release - with the
 *   decision check on and off, say - and each row shows where it stood there.
 *
 *   Rankings are produced in the backend, so this screen only reads them.
 */

import { Fragment, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeading,
  Pill,
  Spinner,
} from '../../components/ui'
import {
  listScoringRuns,
  readSeverityReport,
  type ScoringRunSummary,
  type SeverityRecord,
  type SeverityReportV1,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { useWorkspace } from '../../workspace/useWorkspace'
import RankedEventDetail from './RankedEventDetail'
import {
  DIMENSIONS,
  isActive,
  levelOf,
  percent,
  plainType,
  provenanceNote,
  reason,
  runLabel,
  sameSystem,
  score,
  subject,
  systemName,
  weightsOf,
} from './dimensions'

export default function PrioritiesPage() {
  const { repositoryKey } = useWorkspace()
  const runs = useRequest((options) => listScoringRuns(options), [])

  // The ranking, the one it is compared with and an opened row can all come
  // from the url, so a link opens exactly this view:
  // /priorities?run=<id>&compare=<id>&open=<event id>.
  const [params, setParams] = useSearchParams()
  const [selected, setSelected] = useState<string | null>(params.get('open'))

  const all = runs.data ?? []
  const runId = params.get('run') ?? defaultRun(all, repositoryKey)
  const current = all.find((run) => run.run_id === runId) ?? null
  const comparable = all.filter(
    (run) =>
      current !== null &&
      run.run_id !== current.run_id &&
      run.system_id === current.system_id &&
      run.release_id === current.release_id,
  )
  const requested = params.get('compare')
  const compareId = comparable.some((run) => run.run_id === requested) ? requested : null

  const report = useRequest(
    (options) => readSeverityReport(runId ?? '', options),
    [runId],
    Boolean(runId),
  )
  const other = useRequest(
    (options) => readSeverityReport(compareId ?? '', options),
    [compareId],
    Boolean(compareId),
  )

  const shown = report.data && report.data.run_id === runId ? report.data : null
  const against = other.data && other.data.run_id === compareId ? other.data : null

  const showRun = (id: string) => {
    setParams({ run: id })
    setSelected(null)
  }
  const compareWith = (id: string) => {
    setParams(runId ? (id ? { run: runId, compare: id } : { run: runId }) : {})
  }

  return (
    <>
      <PageHeading
        eyebrow="ranked"
        title="Priorities"
        description="What degraded between releases, ranked by how much it matters — and, for every item, why."
        action={
          <Link to="/">
            <Button size="sm" variant="quiet">
              Back to the pipeline
            </Button>
          </Link>
        }
      />

      {runs.isLoading && <Spinner label="reading the saved rankings" />}
      {runs.error && <ErrorState message={runs.error} onRetry={runs.reload} />}

      {runs.data && runs.data.length === 0 && (
        <Card>
          <EmptyState
            title="No ranking has been saved yet"
            body="Scoring runs in the backend after degradation has been detected, and writes its report to disk; this screen reads those reports. None exist on this machine yet."
          />
        </Card>
      )}

      {all.length > 0 && runId && (
        <div className="flex flex-wrap items-end gap-6">
          <Picker label="ranking" runs={all} value={runId} onChange={showRun} />
          {comparable.length > 0 && (
            <Picker
              label="compare with"
              runs={comparable}
              value={compareId ?? ''}
              empty="nothing"
              onChange={compareWith}
            />
          )}
        </div>
      )}

      {report.isLoading && <Spinner label="reading the severity report" />}
      {report.error && <ErrorState message={report.error} onRetry={report.reload} />}

      {shown && (
        <>
          <Provenance report={shown} />
          <ReadingGuide report={shown} />
          <Recipe report={shown} />
          <Ranked
            report={shown}
            against={against}
            againstRun={comparable.find((run) => run.run_id === compareId) ?? null}
            selected={selected}
            onSelect={(id) => setSelected(selected === id ? null : id)}
          />
          <SetAside report={shown} />
        </>
      )}
    </>
  )
}

function Provenance({ report }: { report: SeverityReportV1 }) {
  const note = provenanceNote(report.data_provenance)
  if (!note) return null
  return (
    <div className="flex flex-col gap-2 rounded-control border border-warn/40 bg-warn-wash px-5 py-4">
      <span className="font-mono text-xs tracking-wide text-warn">
        {report.data_provenance} data
      </span>
      <p className="text-sm leading-relaxed text-ink-2">{note}</p>
    </div>
  )
}

/** How to read the page, and where the list came from: a funnel that adds up. */
function ReadingGuide({ report }: { report: SeverityReportV1 }) {
  const ranked = report.records?.length ?? 0
  const skipped = report.skipped?.length ?? 0
  const unusable = report.quarantined?.length ?? 0
  const total = ranked + skipped + unusable

  return (
    <Card title="How to read this">
      <div className="flex flex-col gap-7">
        <div className="flex flex-wrap items-start gap-x-5 gap-y-3">
          <Funnel
            value={total}
            label="events in"
            note={`found by degradation detection in ${systemName(report.system_id)} ${report.release_id}`}
          />
          <span className="pt-1 font-mono text-ink-4">→</span>
          <Funnel value={ranked} label="ranked" note="the list below" />
          <span className="pt-1 font-mono text-ink-4">+</span>
          <Funnel value={skipped} label="skipped" note="by rule, e.g. rejected or intentional" />
          <span className="pt-1 font-mono text-ink-4">+</span>
          <Funnel value={unusable} label="unusable" note="malformed, or not in the architecture" />
        </div>
        <ul className="grid gap-5 text-sm leading-relaxed text-ink-2 md:grid-cols-3">
          <li>
            <span className="text-ink">Each row</span> is something degradation detection found
            getting worse across releases — a cycle, a hub, a part that keeps growing.
          </li>
          <li>
            <span className="text-ink">The score</span> runs from 0 to 100; 100 would mean as bad as
            possible on every part of the recipe below. The list is ordered by it.
          </li>
          <li>
            <span className="text-ink">The coloured bar</span> shows what each score is made of.
            Open a row to see the arithmetic behind it.
          </li>
        </ul>
      </div>
    </Card>
  )
}

function Funnel({ value, label, note }: { value: number; label: string; note: string }) {
  return (
    <span className="flex max-w-48 flex-col gap-1">
      <span className="font-mono">
        <span className="text-2xl text-ink">{value}</span>{' '}
        <span className="text-sm text-ink-3">{label}</span>
      </span>
      <span className="text-xs leading-snug text-ink-4">{note}</span>
    </span>
  )
}

/** The four questions every score answers, and how much each one counts. */
function Recipe({ report }: { report: SeverityReportV1 }) {
  const weights = weightsOf(report)
  const provisional = report.weights_provenance !== 'supervisor-elicited'

  return (
    <Card
      title="How a score is built"
      action={
        <span className="font-mono text-xs text-ink-4">
          weights {report.weights_version} · consistency ratio {report.ahp_cr.toFixed(2)} (at most
          0.10 counts as consistent)
        </span>
      }
    >
      <div className="flex flex-col gap-4">
        {DIMENSIONS.map((dimension) => {
          const weight = weights[dimension.key]
          const on = weight !== undefined
          return (
            <div
              key={dimension.key}
              className="grid items-center gap-2 sm:grid-cols-[11rem_1fr_15rem]"
            >
              <span className={`flex items-center gap-2 text-sm ${on ? 'text-ink' : 'text-ink-4'}`}>
                <span
                  className={`size-2.5 rounded-full ${on ? dimension.fill : 'bg-line-strong'}`}
                />
                {dimension.label}
              </span>
              <span className={`text-sm ${on ? 'text-ink-2' : 'text-ink-4'}`}>
                {dimension.question}
              </span>
              {on ? (
                <span className="flex items-center gap-3">
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
                    <span
                      className={`block h-full ${dimension.fill}`}
                      style={{ width: percent(weight, 1) }}
                    />
                  </span>
                  <span className="w-20 text-right font-mono text-xs text-ink-2">
                    counts {percent(weight)}
                  </span>
                </span>
              ) : (
                <span className="text-right font-mono text-xs text-ink-4">not used in this run</span>
              )}
            </div>
          )
        })}
        <p className="text-xs leading-relaxed text-ink-4">
          The weights come from pairwise comparisons (AHP)
          {provisional
            ? " made by the author; they are provisional until an expert session replaces them."
            : ' made in an expert session.'}{' '}
          A part that is not used has its weight shared out among the others in proportion.
        </p>
      </div>
    </Card>
  )
}

function Ranked({
  report,
  against,
  againstRun,
  selected,
  onSelect,
}: {
  report: SeverityReportV1
  against: SeverityReportV1 | null
  againstRun: ScoringRunSummary | null
  selected: string | null
  onSelect: (eventId: string) => void
}) {
  const records = report.records ?? []
  const otherRank = new Map((against?.records ?? []).map((r) => [r.event_id, r.rank]))
  const heads = [
    '#',
    'what degraded, and why it ranks here',
    'score',
    'made of',
    ...(against ? ['in the other ranking'] : []),
  ]

  return (
    <Card
      title="Ranked"
      action={
        <span className="text-xs text-ink-4">
          Open a row to see how its score was built.
          {againstRun && ` Compared with: ${runLabel(againstRun)}.`}
        </span>
      }
    >
      {records.length === 0 ? (
        (report.skipped?.length ?? 0) + (report.quarantined?.length ?? 0) === 0 ? (
          <EmptyState
            title="Nothing to rank"
            body="Detection found nothing getting worse across these releases, so no problem was handed on. That is a result, not a fault: the system held its shape over the releases analysed."
          />
        ) : (
          <EmptyState
            title="Nothing could be ranked"
            body="Every event in this run was skipped or could not be used; the list below says why."
          />
        )
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                {heads.map((head) => (
                  <th
                    key={head}
                    className="border-b border-line px-4 py-3 text-left text-xs font-medium tracking-wide text-ink-3"
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <Fragment key={record.event_id}>
                  <tr
                    onClick={() => onSelect(record.event_id)}
                    className={`cursor-pointer align-top transition ${
                      selected === record.event_id ? 'bg-raised' : 'hover:bg-raised/50'
                    }`}
                  >
                    <td className="border-b border-line px-4 py-4 font-mono text-lg text-ink">
                      {record.rank}
                    </td>
                    <td className="border-b border-line px-4 py-4">
                      <div className="flex flex-col gap-1">
                        <span className="font-mono text-ink">{subject(record)}</span>
                        <span className="text-xs text-ink-3">
                          {plainType(record.anti_pattern_type)}
                        </span>
                        <span className="text-xs text-ink-2">{reason(record)}</span>
                      </div>
                    </td>
                    <td className="border-b border-line px-4 py-4">
                      <Score record={record} total={records.length} />
                    </td>
                    <td className="border-b border-line px-4 py-4">
                      <MadeOf record={record} />
                    </td>
                    {against && (
                      <td className="border-b border-line px-4 py-4">
                        <Movement here={record.rank} there={otherRank.get(record.event_id)} />
                      </td>
                    )}
                  </tr>
                  {selected === record.event_id && (
                    <tr>
                      <td colSpan={heads.length} className="border-b border-line p-0">
                        <RankedEventDetail record={record} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function Score({ record, total }: { record: SeverityRecord; total: number }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-2xl leading-none text-ink">{score(record.severity)}</span>
        <span className="font-mono text-xs text-ink-4">{record.severity.toFixed(3)}</span>
      </div>
      <div className="h-1 w-24 overflow-hidden rounded-full bg-line">
        <div className="h-full bg-ink" style={{ width: percent(record.severity, 1) }} />
      </div>
      <span title="Position in this list, in thirds: relative, not an absolute threshold">
        <Pill>{levelOf(record.rank, total)} in this list</Pill>
      </span>
    </div>
  )
}

/** The score split into its parts, each in its own colour; an unused part takes no space. */
function MadeOf({ record }: { record: SeverityRecord }) {
  const parts = DIMENSIONS.filter((d) => isActive(record, d.key)).map((d) => ({
    ...d,
    share: record.contributions[d.key] ?? 0,
  }))
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-2.5 w-48 overflow-hidden rounded-full bg-line">
        {parts.map((part) =>
          part.share > 0 ? (
            <div
              key={part.key}
              className={part.fill}
              title={`${part.label}: ${percent(part.share)} of this score`}
              style={{ width: percent(part.share, 1) }}
            />
          ) : null,
        )}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {parts
          .filter((part) => part.share >= 0.05)
          .map((part) => (
            <span key={part.key} className="flex items-center gap-1.5 font-mono text-xs text-ink-3">
              <span className={`size-1.5 rounded-full ${part.fill}`} />
              {percent(part.share)}
            </span>
          ))}
      </div>
    </div>
  )
}

function Movement({ here, there }: { here: number; there: number | undefined }) {
  if (there === undefined) return <span className="text-xs text-ink-4">not ranked there</span>
  const moved = there - here
  return (
    <span className="flex flex-col gap-0.5 font-mono">
      <span className="text-ink-2">#{there} there</span>
      <span className="text-xs text-ink-4">
        {moved === 0 ? 'same place' : moved > 0 ? `↑ ${moved} here` : `↓ ${-moved} here`}
      </span>
    </span>
  )
}

function SetAside({ report }: { report: SeverityReportV1 }) {
  const skipped = report.skipped ?? []
  const quarantined = report.quarantined ?? []
  if (skipped.length + quarantined.length === 0) return null

  const rows = [
    ...skipped.map((item) => ({
      id: item.event_id,
      outcome: 'skipped',
      reason: item.reason,
      detail: '',
    })),
    ...quarantined.map((item) => ({
      id: item.event_id ?? '(no id)',
      outcome: 'unusable',
      reason: item.reason,
      detail: item.detail ?? '',
    })),
  ]

  return (
    <Card
      title="Set aside, with the reason"
      action={<span className="text-xs text-ink-4">listed rather than dropped</span>}
    >
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              {['event', 'outcome', 'reason', 'detail'].map((head) => (
                <th
                  key={head}
                  className="border-b border-line px-4 py-3 text-left text-xs font-medium tracking-wide text-ink-3"
                >
                  {head}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.id}-${index}`}>
                <td className="border-b border-line px-4 py-3.5 font-mono text-ink-2">{row.id}</td>
                <td className="border-b border-line px-4 py-3.5">
                  <Pill tone={row.outcome === 'unusable' ? 'bad' : 'neutral'}>{row.outcome}</Pill>
                </td>
                <td className="border-b border-line px-4 py-3.5 text-ink-2">
                  {row.reason.replace(/_/g, ' ')}
                </td>
                <td className="border-b border-line px-4 py-3.5 font-mono text-xs break-words text-ink-3">
                  {row.detail}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function Picker({
  label,
  runs,
  value,
  empty,
  onChange,
}: {
  label: string
  runs: ScoringRunSummary[]
  value: string
  empty?: string
  onChange: (runId: string) => void
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="text-xs text-ink-4">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="max-w-xl rounded-control border border-line-strong bg-raised px-2.5 py-1.5 text-sm text-ink focus:border-ai focus:outline-none"
      >
        {empty !== undefined && <option value="">{empty}</option>}
        {runs.map((run) => (
          <option key={run.run_id} value={run.run_id}>
            {runLabel(run)}
          </option>
        ))}
      </select>
    </label>
  )
}

/**
 * The newest run of the selected repository, else the newest run.
 *
 * Matched loosely: the workspace names a repository after its clone url
 * (`microservices-demo-<hash>`) while a ranking names the system it scored
 * (`online-boutique`), and the two are not yet one id across the application.
 */
// The selected repository's ranking, the one made from detection's own output first.
function defaultRun(runs: ScoringRunSummary[], repositoryKey: string): string | null {
  const own = runs.filter((run) => sameSystem(run.system_id, repositoryKey))
  const preferred = own.find((run) => run.data_provenance === 'live') ?? own[0] ?? runs[0]
  return preferred?.run_id ?? null
}
