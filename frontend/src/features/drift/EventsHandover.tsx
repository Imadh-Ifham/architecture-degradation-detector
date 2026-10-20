/**
 * The degradation events, as the artifact the next phase reads.
 *
 * Description:
 *   The same card the canvas has for the validated graph, for the document
 *   this phase hands on: one event per anti-pattern that is getting worse
 *   with statistical support, and nothing else.
 *
 *   **No severity, on purpose.** An event says *that* something is getting
 *   worse and how strong the evidence is; how much it matters is the next
 *   phase's question. `trend strength` is the largest |tau| among the
 *   measures that moved - a strength of evidence, not of harm - and the
 *   screen says so next to it.
 *
 *   Field lists are read off the events themselves, as the canvas does, so
 *   the card cannot drift from the contract.
 */

import { Card, EmptyState, Pill } from '../../components/ui'
import type { DegradationReport } from '../../lib/api'
import { antiPattern, metricName } from './labels'

export default function EventsHandover({ report }: { report: DegradationReport }) {
  const events = report.events
  const first = events[0]
  const names = new Map(
    report.releases.flatMap((release) =>
      release.elements.map((element) => [element.id, element.name] as const),
    ),
  )

  return (
    <Card
      title="What is handed on"
      action={first ? <Pill>schema {first.schema_version}</Pill> : <Pill>no events</Pill>}
    >
      <div className="flex flex-col gap-8">
        <div className="flex flex-col gap-2">
          <span className="text-xs tracking-wide text-ink-4">the published artifact</span>
          {report.handover?.latest_events ? (
            <>
              <code className="font-mono text-xs leading-relaxed break-all text-ink-2">
                {report.handover.latest_events}
              </code>
              <code className="font-mono text-xs leading-relaxed break-all text-ink-3">
                {report.handover.latest_graph ?? 'no release package written'}
              </code>
              <span className="text-xs leading-relaxed text-ink-4">
                The events, and the release package their element ids refer to - written
                for every run and copied to <code className="font-mono">latest</code>. The
                scoring phase reads these files with{' '}
                <code className="font-mono">--events</code> and{' '}
                <code className="font-mono">--graph</code>, not this application.
              </span>
            </>
          ) : (
            <span className="text-xs leading-relaxed text-warn">
              No files were written for this run. Detect again from this screen to write
              them for the scoring phase.
            </span>
          )}
        </div>

        {events.length === 0 ? (
          <EmptyState
            title="Nothing is handed on from this run"
            body="An event is written only for an anti-pattern whose measures are getting worse with a q-value at or below the threshold. Anti-patterns that are present but not getting worse are found and shown, and are not events."
          />
        ) : (
          <ul className="flex flex-col gap-px overflow-hidden rounded-card border border-line bg-line">
            {events.map((event) => (
              <li key={event.event_id} className="flex flex-col gap-3 bg-panel px-6 py-5">
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <span className="text-sm text-ink">
                    {antiPattern(event.anti_pattern_type).name}
                    <span className="ml-3 font-mono text-xs text-ink-3">
                      {(event.members.length ? event.members : [event.element_id ?? ''])
                        .map((member) => names.get(member) ?? member)
                        .join(', ')}
                    </span>
                  </span>
                  <span className="font-mono text-xs text-ink-4">
                    {event.window.start_release} → {event.window.end_release} ·{' '}
                    {event.window.n_releases} releases
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  {event.lifecycle && <Pill tone="bad">{event.lifecycle}</Pill>}
                  <span className="font-mono text-xs text-ink-3">
                    evidence {event.trend_strength.toFixed(2)}
                  </span>
                  {event.affected_metrics.map((metric) => (
                    <span key={metric.metric} className="font-mono text-xs text-ink-4">
                      {metricName(metric.metric)} q {metric.q_value.toFixed(3)}
                    </span>
                  ))}
                  {event.window.low_confidence_releases.length > 0 && (
                    <Pill tone="warn">
                      {event.window.low_confidence_releases.length} low-confidence release
                      {event.window.low_confidence_releases.length === 1 ? '' : 's'}
                    </Pill>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="grid gap-7 lg:grid-cols-3">
          <Fields
            title="on every event"
            note="what is degrading, over which releases"
            keys={first ? Object.keys(first) : []}
          />
          <Fields
            title="on every measure"
            note="the test that supports it, and the series"
            keys={first?.affected_metrics[0] ? Object.keys(first.affected_metrics[0]) : []}
          />
          <Fields
            title="on the window"
            note="where it starts, and which releases were weak"
            keys={first ? Object.keys(first.window) : []}
          />
        </div>

        <p className="max-w-prose border-t border-line pt-6 text-sm leading-relaxed text-ink-3">
          <span className="text-ink">There is no severity on an event.</span>{' '}
          <code className="font-mono text-xs text-ink-2">trend_strength</code> is how strong
          the evidence is that it is getting worse, not how bad it is. Ranking what matters
          most is the next phase's work, and it reads this file — not this application.
        </p>
      </div>
    </Card>
  )
}

function Fields({ title, note, keys }: { title: string; note: string; keys: string[] }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium text-ink">{title}</span>
        <span className="text-xs leading-relaxed text-ink-4">{note}</span>
      </div>
      <ul className="flex flex-wrap gap-1.5">
        {keys.map((key) => (
          <li
            key={key}
            className="rounded-[4px] border border-line bg-sunken px-2 py-1 font-mono text-[11px] text-ink-2"
          >
            {key}
          </li>
        ))}
        {keys.length === 0 && (
          <li className="font-mono text-[11px] text-ink-4">nothing handed on yet</li>
        )}
      </ul>
    </div>
  )
}
