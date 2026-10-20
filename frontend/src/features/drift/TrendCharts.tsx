/**
 * How each measure moved across the releases, and whether that is a trend.
 *
 * Description:
 *   One small chart per series the trend test looked at: the value at every
 *   release (a release with no value is a gap, never a zero), and the Sen's
 *   slope line through them. Beside it, the numbers that decide it - Kendall's
 *   tau, the p-value, the q-value after correcting for how many series were
 *   tested - and the verdict in words.
 *
 *   **Three verdicts, not two.** A series can be getting worse with the
 *   evidence to say so (significant), getting worse without it, or not getting
 *   worse. The middle one is the common case with few releases, and drawing it
 *   like the first would announce degradation the statistics do not support;
 *   drawing it like the last would hide a direction somebody should watch.
 *
 *   **What was not tested is listed, with the reason.** A series that is too
 *   short is not a healthy series, and a screen that only shows the tested ones
 *   reads as "everything else is fine".
 *
 *   Small multiples on one shape rather than one chart with many lines: the
 *   series have different units, and one y-axis across them would be a lie
 *   about all but one.
 */

import { useMemo, useState } from 'react'
import { EmptyState, Pill, Tabs } from '../../components/ui'
import type { DegradationReport, TrendResult, UntestedSeries } from '../../lib/api'
import { antiPattern, figure, metricName, untestedReason } from './labels'

type Filter = 'worsening' | 'tested' | 'untested'

const SCOPE_ORDER = { SYSTEM: 0, INSTANCE: 1, ELEMENT: 2 } as const

export default function TrendCharts({ report }: { report: DegradationReport }) {
  const subject = useSubjectNames(report)
  const timeline = report.releases.filter((release) => release.on_timeline)
  const minimum = report.run.trend.min_releases

  const tested = useMemo(
    () =>
      [...report.trends].sort(
        (a, b) =>
          verdictRank(a) - verdictRank(b) ||
          SCOPE_ORDER[a.scope] - SCOPE_ORDER[b.scope] ||
          a.q_value - b.q_value,
      ),
    [report.trends],
  )
  const worsening = tested.filter((trend) => trend.is_worsening)

  const [filter, setFilter] = useState<Filter>(worsening.length > 0 ? 'worsening' : 'tested')

  const shown = filter === 'worsening' ? worsening : tested

  return (
    <div className="flex flex-col gap-7">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <Tabs
          tabs={[
            { id: 'worsening', label: 'Getting worse', count: worsening.length },
            { id: 'tested', label: 'All tested', count: tested.length },
            { id: 'untested', label: 'Not tested', count: report.untested.length },
          ]}
          active={filter}
          onChange={setFilter}
        />
        <span className="font-mono text-xs text-ink-4">
          Mann-Kendall · Sen's slope · Benjamini-Hochberg q ≤ {report.run.trend.alpha}
        </span>
      </div>

      {timeline.length < minimum && (
        <p className="max-w-prose border-l-2 border-warn/60 pl-4 text-sm leading-relaxed text-ink-2">
          {timeline.length} release{timeline.length === 1 ? '' : 's'} on the timeline; a
          trend needs at least {minimum}. Every series is listed under{' '}
          <span className="text-ink">not tested</span> until there are enough. The
          anti-patterns in each release are still found and shown above.
        </p>
      )}

      {filter === 'untested' ? (
        <UntestedList untested={report.untested} subject={subject} minimum={minimum} />
      ) : shown.length === 0 ? (
        <EmptyState
          title={filter === 'worsening' ? 'Nothing is getting worse' : 'No series was tested'}
          body={
            filter === 'worsening'
              ? 'Every tested series is flat or improving across these releases.'
              : `A series is tested once it has a value in at least ${minimum} releases.`
          }
        />
      ) : (
        <ul className="grid gap-px overflow-hidden rounded-card border border-line bg-line md:grid-cols-2 xl:grid-cols-3">
          {shown.map((trend) => (
            <li key={`${trend.scope}:${trend.subject_id}:${trend.metric}`} className="bg-panel">
              <TrendCard
                trend={trend}
                subject={subject(trend.scope, trend.subject_id)}
                ordinals={timeline.length}
                alpha={report.run.trend.alpha}
              />
            </li>
          ))}
        </ul>
      )}

      {report.static_flags.length > 0 && filter !== 'untested' && (
        <p className="max-w-prose border-t border-line pt-5 text-xs leading-relaxed text-ink-4">
          <span className="text-ink-3">For comparison:</span> a fixed-threshold check
          would flag {report.static_flags.length} element
          {report.static_flags.length === 1 ? '' : 's'} in the last release (
          {report.static_flags
            .map((flag) => `${metricName(flag.metric)} ${figure(flag.value)} > ${flag.threshold}`)
            .join(', ')}
          ). It is shown, never used: a value above a line says nothing about whether it
          is getting worse.
        </p>
      )}
    </div>
  )
}

function verdictRank(trend: TrendResult): number {
  if (trend.is_worsening && trend.is_significant) return 0
  if (trend.is_worsening) return 1
  return 2
}

function verdict(trend: TrendResult): { tone: 'bad' | 'warn' | 'neutral'; label: string } {
  if (trend.is_worsening && trend.is_significant) return { tone: 'bad', label: 'degrading' }
  if (trend.is_worsening) return { tone: 'warn', label: 'worse, not significant' }
  return { tone: 'neutral', label: 'not getting worse' }
}

/* One chart ------------------------------------------------------------------ */

const WIDTH = 300
const HEIGHT = 96
const PAD_X = 10
const PAD_Y = 12

const LINE = { bad: 'stroke-bad', warn: 'stroke-warn', neutral: 'stroke-ink-3' } as const
const DOT = { bad: 'fill-bad', warn: 'fill-warn', neutral: 'fill-ink-3' } as const

function TrendCard({
  trend,
  subject,
  ordinals,
  alpha,
}: {
  trend: TrendResult
  subject: string
  ordinals: number
  alpha: number
}) {
  const [hovered, setHovered] = useState<number | null>(null)
  const [asTable, setAsTable] = useState(false)
  const { tone, label } = verdict(trend)

  const values = trend.points.flatMap((point) => (point.value === null ? [] : [point.value]))
  const span = Math.max(1, ordinals - 1)
  const fitted = [0, span].map((t) => trend.intercept + trend.sen_slope * t)
  const low = Math.min(...values, ...fitted)
  const high = Math.max(...values, ...fitted)
  const range = high - low || 1

  const x = (ordinal: number) => PAD_X + (ordinal / span) * (WIDTH - PAD_X * 2)
  const y = (value: number) => HEIGHT - PAD_Y - ((value - low) / range) * (HEIGHT - PAD_Y * 2)

  // Broken at every gap: a line drawn across a release with no value claims a
  // value that was never measured.
  const runs: string[] = []
  let current: string[] = []
  for (const point of trend.points) {
    if (point.value === null) {
      if (current.length) runs.push(current.join(' '))
      current = []
      continue
    }
    current.push(`${current.length ? 'L' : 'M'} ${x(point.ordinal)} ${y(point.value)}`)
  }
  if (current.length) runs.push(current.join(' '))

  const point = hovered === null ? null : trend.points[hovered]

  return (
    <div className="flex h-full flex-col gap-4 px-6 py-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-sm text-ink">{metricName(trend.metric)}</span>
          <span className="truncate font-mono text-[11px] text-ink-4" title={subject}>
            {subject}
          </span>
        </div>
        <Pill tone={tone === 'neutral' ? 'neutral' : tone}>{label}</Pill>
      </div>

      {asTable ? (
        <table className="w-full border-collapse font-mono text-xs">
          <tbody>
            {trend.points.map((item) => (
              <tr key={item.release_id}>
                <td className="border-b border-line py-1.5 text-ink-3">{item.release_id}</td>
                <td className="border-b border-line py-1.5 text-right text-ink-2">
                  {figure(item.value)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="relative">
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="h-24 w-full overflow-visible"
            role="img"
            aria-label={`${metricName(trend.metric)} across ${trend.points.length} releases, ${label}`}
            onMouseLeave={() => setHovered(null)}
          >
            <line
              x1={PAD_X}
              x2={WIDTH - PAD_X}
              y1={HEIGHT - PAD_Y}
              y2={HEIGHT - PAD_Y}
              className="stroke-line"
              strokeWidth="1"
            />
            <line
              x1={x(0)}
              x2={x(span)}
              y1={y(fitted[0])}
              y2={y(fitted[1])}
              className="stroke-ink-4"
              strokeWidth="1.5"
              strokeDasharray="4 4"
            />
            {runs.map((d) => (
              <path
                key={d}
                d={d}
                fill="none"
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
                className={LINE[tone]}
              />
            ))}
            {hovered !== null && point && (
              <line
                x1={x(point.ordinal)}
                x2={x(point.ordinal)}
                y1={PAD_Y / 2}
                y2={HEIGHT - PAD_Y}
                className="stroke-line-strong"
                strokeWidth="1"
              />
            )}
            {trend.points.map((item, index) =>
              item.value === null ? null : (
                <circle
                  key={item.release_id}
                  cx={x(item.ordinal)}
                  cy={y(item.value)}
                  r={index === hovered ? 5 : 4}
                  className={`${DOT[tone]} stroke-panel`}
                  strokeWidth="2"
                />
              ),
            )}
            {/* Hit targets wider than the marks: a column per release. */}
            {trend.points.map((item, index) => (
              <rect
                key={`hit-${item.release_id}`}
                x={x(item.ordinal) - (WIDTH - PAD_X * 2) / span / 2}
                y={0}
                width={(WIDTH - PAD_X * 2) / span}
                height={HEIGHT}
                className="fill-transparent"
                onMouseEnter={() => setHovered(index)}
              />
            ))}
          </svg>

          {point && (
            <span className="pointer-events-none absolute -top-2 right-0 rounded-control border border-line-strong bg-raised px-2.5 py-1 font-mono text-[11px] text-ink-2">
              {point.release_id} · {figure(point.value)} {trend.unit}
            </span>
          )}
        </div>
      )}

      <dl className="mt-auto grid grid-cols-4 gap-3 border-t border-line pt-4 font-mono text-[11px]">
        <Figure term="tau" value={trend.tau.toFixed(2)} />
        <Figure term="slope" value={`${signed(trend.sen_slope)}/rel`} />
        <Figure term="p" value={trend.p_value.toFixed(3)} />
        <Figure
          term="q"
          value={trend.q_value.toFixed(3)}
          strong={trend.q_value <= alpha}
        />
      </dl>

      <div className="flex items-center justify-between gap-3 font-mono text-[11px] text-ink-4">
        <span>
          n {trend.n} · {trend.method.toLowerCase()} · worse when it{' '}
          {trend.worsening === 'INCREASE' ? 'rises' : 'falls'}
        </span>
        <button
          type="button"
          onClick={() => setAsTable((value) => !value)}
          className="text-ink-3 underline-offset-4 hover:text-ink hover:underline"
        >
          {asTable ? 'chart' : 'values'}
        </button>
      </div>
    </div>
  )
}

function Figure({ term, value, strong }: { term: string; value: string; strong?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-ink-4">{term}</dt>
      <dd className={strong ? 'text-ink' : 'text-ink-2'}>{value}</dd>
    </div>
  )
}

function signed(value: number): string {
  const text = Math.abs(value) >= 10 ? value.toFixed(1) : value.toFixed(2)
  return value > 0 ? `+${text}` : text
}

/* What was not tested -------------------------------------------------------- */

function UntestedList({
  untested,
  subject,
  minimum,
}: {
  untested: UntestedSeries[]
  subject: (scope: UntestedSeries['scope'], id: string) => string
  minimum: number
}) {
  if (untested.length === 0) {
    return <EmptyState title="Every series was tested" body="Nothing was too short or skipped." />
  }

  // Grouped by reason: forty rows saying "too short" are one fact, not forty.
  const byReason = new Map<string, UntestedSeries[]>()
  for (const item of untested) {
    byReason.set(item.reason, [...(byReason.get(item.reason) ?? []), item])
  }

  return (
    <div className="flex flex-col gap-7">
      {[...byReason.entries()].map(([reason, items]) => (
        <div key={reason} className="flex flex-col gap-3">
          <span className="text-sm text-ink-2">
            {items.length} series · {untestedReason(reason, minimum)}
          </span>
          <ul className="flex flex-wrap gap-1.5">
            {items.map((item) => (
              <li
                key={`${item.scope}:${item.subject_id}:${item.metric}`}
                className="rounded-[4px] border border-line bg-sunken px-2 py-1 font-mono text-[11px] text-ink-3"
                title={`${item.n_points} release${item.n_points === 1 ? '' : 's'} with a value`}
              >
                {metricName(item.metric)} · {subject(item.scope, item.subject_id)}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

/* Names ---------------------------------------------------------------------- */

/**
 * What a series is about, in words: the system, an element by its latest
 * name, or an anti-pattern instance by its type and members.
 */
function useSubjectNames(report: DegradationReport) {
  return useMemo(() => {
    const names = new Map<string, string>()
    for (const release of report.releases) {
      for (const element of release.elements) names.set(element.id, element.name)
    }

    const lineage = new Map(
      report.lineages.map((item) => {
        const last = item.members[item.members.length - 1]
        return [item.lineage_id, names.get(last?.element_id ?? '') ?? last?.element_id ?? item.lineage_id]
      }),
    )

    const track = new Map(
      report.tracks.map((item) => {
        const last = item.occurrences[item.occurrences.length - 1]
        const members = (last?.members ?? []).map((member) => names.get(member) ?? member)
        return [
          item.track_id,
          `${antiPattern(item.anti_pattern_type).name}: ${members.slice(0, 3).join(', ')}${
            members.length > 3 ? ` +${members.length - 3}` : ''
          }`,
        ]
      }),
    )

    return (scope: TrendResult['scope'], id: string) =>
      scope === 'SYSTEM'
        ? 'the whole system'
        : scope === 'ELEMENT'
          ? (lineage.get(id) ?? id)
          : (track.get(id) ?? id)
  }, [report])
}
