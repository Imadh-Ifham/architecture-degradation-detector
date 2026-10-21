/**
 * The score phase, on the pipeline.
 *
 * Description:
 *   Rank what the detect phase just handed on, and see at a glance what came
 *   of it. The ranking itself, with a reason for every row, is the scoring
 *   screen's; this card says enough to know whether to go there.
 *
 *   **Started by hand, after detection.** A ranking belongs to one detection
 *   run (it is named after it), so it is made once per run: pressing the
 *   button for a run already scored opens the saved ranking instead.
 */

import { Link } from 'react-router'
import { Button, Card, ErrorState, Spinner } from '../../components/ui'
import type { ScoringRunSummary } from '../../lib/api'

export default function ScoringCard({
  events,
  ranking,
  isScoring,
  error,
  canScore,
  onScore,
}: {
  /** Events the current detection run handed on; null without a current run. */
  events: number | null
  /** The ranking of the current detection run, once it exists. */
  ranking: ScoringRunSummary | null
  isScoring: boolean
  error: string | null
  canScore: boolean
  onScore: () => void
}) {
  const link = ranking ? `/scoring?run=${encodeURIComponent(ranking.run_id)}` : null

  return (
    <Card
      title="Which problems matter most"
      action={
        <div className="flex flex-wrap items-center gap-4">
          {isScoring && <Spinner label="scoring" />}
          {link && (
            <Link
              to={link}
              className="font-mono text-xs text-ink-2 underline-offset-4 hover:text-ink hover:underline"
            >
              open scoring →
            </Link>
          )}
          {!ranking && (
            <Button size="sm" variant="primary" disabled={isScoring || !canScore} onClick={onScore}>
              Score
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-6">
        {error && <ErrorState message={error} />}

        {!ranking && (
          <p className="max-w-prose text-sm leading-relaxed text-ink-3">
            {canScore
              ? `Scoring reads the ${events} event${events === 1 ? '' : 's'} detection handed on and ranks them on four questions: how much of the system depends on it, how actively its code is changing, whether it breaks a recorded decision, and how long it has lasted. Every row gets a reason.`
              : 'Scoring ranks what the detect phase finds, so it waits for a detection run over the releases on this screen.'}
          </p>
        )}

        {ranking && ranking.counts.payloads === 0 && (
          <p className="max-w-prose text-sm leading-relaxed text-ink-2">
            Detection found nothing getting worse across these releases, so there is nothing to
            rank. That is a result, not a fault: the system held its shape.
          </p>
        )}

        {ranking && ranking.counts.payloads > 0 && (
          <dl className="grid gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-4">
            <Count label="events in" value={ranking.counts.payloads} />
            <Count label="ranked" value={ranking.counts.ranked} />
            <Count label="set aside, with a reason" value={ranking.counts.skipped} />
            <Count label="unusable" value={ranking.counts.quarantined} />
          </dl>
        )}
      </div>
    </Card>
  )
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-1.5 bg-panel px-4 py-3.5">
      <dt className="text-[11px] text-ink-4">{label}</dt>
      <dd className="font-mono text-lg leading-none text-ink">{value}</dd>
    </div>
  )
}
