/**
 * The detect phase, on the pipeline.
 *
 * Description:
 *   Start detection over every validated release, and see at a glance what
 *   it found release by release. The drawing, the trends and the events are
 *   the drift screen's; this card says enough to know whether to go there.
 *
 *   **Started by hand, like validation.** Detection reads whatever has been
 *   validated at the moment it runs, so running it automatically after each
 *   validation would store a run per release, each over a different stack.
 *   One button, pressed when the stack is the one somebody wants judged.
 */

import { Link } from 'react-router'
import { Button, Card, ErrorState, Pill, Spinner } from '../../components/ui'
import type { DegradationReport } from '../../lib/api'
import { GATE } from '../drift/labels'

export default function DetectionCard({
  report,
  isDetecting,
  error,
  canDetect,
  isStale,
  onDetect,
  onFocus,
}: {
  report: DegradationReport | null
  isDetecting: boolean
  error: string | null
  /** Whether anything has been validated that detection could read. */
  canDetect: boolean
  /** The stored run is from before this run's validations, so it may not describe this stack. */
  isStale: boolean
  onDetect: () => void
  onFocus: (releaseId: string) => void
}) {
  const timeline = report?.releases.filter((release) => release.on_timeline) ?? []
  const degrading = report?.trends.filter((trend) => trend.is_worsening && trend.is_significant) ?? []
  const minimum = report?.run.trend.min_releases ?? 0

  return (
    <Card
      title="What degraded across the releases"
      action={
        <div className="flex flex-wrap items-center gap-4">
          {isDetecting && <Spinner label="detecting" />}
          {report && (
            <Link
              to="/drift"
              className="font-mono text-xs text-ink-2 underline-offset-4 hover:text-ink hover:underline"
            >
              open drift →
            </Link>
          )}
          <Button
            size="sm"
            variant={report && !isStale ? undefined : 'primary'}
            disabled={isDetecting || !canDetect}
            onClick={onDetect}
          >
            {report && !isStale ? 'Detect again' : 'Detect degradation'}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-6">
        {error && <ErrorState message={error} />}

        {!report && (
          <p className="max-w-prose text-sm leading-relaxed text-ink-3">
            {canDetect
              ? 'Detection reads every release that has been validated, finds the anti-patterns in each, and tests across them whether they are getting worse.'
              : 'Nothing has been recovered yet. Detection reads the graphs validation publishes, so it waits for at least one validated release.'}
          </p>
        )}

        {report && isStale && (
          <p className="max-w-prose border-l-2 border-warn/60 pl-4 text-sm leading-relaxed text-ink-2">
            This is the last stored run, made before the releases on this screen were
            validated. Validate them, then detect again so the result describes this stack.
          </p>
        )}

        {report && (
          <>
            <ol className="flex gap-px overflow-x-auto rounded-card border border-line bg-line">
              {timeline.map((release) => (
                <li key={release.release_id} className="min-w-32 flex-1">
                  <Link
                    to="/drift"
                    onClick={() => onFocus(release.release_id)}
                    className="flex h-full flex-col gap-2 bg-panel px-4 py-3.5 transition hover:bg-raised"
                  >
                    <span className="font-mono text-xs text-ink-2">{release.release_id}</span>
                    <span
                      className={`font-mono text-lg leading-none ${
                        release.instances.length ? 'text-bad' : 'text-ink-3'
                      }`}
                    >
                      {release.instances.length}
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="text-[11px] text-ink-4">anti-patterns</span>
                      {release.gate_status !== 'ACCEPTED' && (
                        <Pill tone={GATE[release.gate_status].tone}>
                          {GATE[release.gate_status].label}
                        </Pill>
                      )}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>

            <p className="max-w-prose text-sm leading-relaxed text-ink-2">
              {timeline.length < minimum
                ? `${timeline.length} release${timeline.length === 1 ? '' : 's'} on the timeline; trends need ${minimum}, so nothing can be called a trend yet.`
                : degrading.length === 0
                  ? `Nothing is getting worse with statistical support across ${timeline.length} releases.`
                  : `${degrading.length} measure${degrading.length === 1 ? ' is' : 's are'} getting worse with statistical support; ${report.events.length} event${report.events.length === 1 ? '' : 's'} handed on.`}
            </p>
          </>
        )}
      </div>
    </Card>
  )
}
