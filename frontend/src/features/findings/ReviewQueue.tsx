/**
 * The findings held back for a person.
 *
 * Description:
 *   The one place in the application where somebody changes what the system
 *   is allowed to claim. Every other screen reports.
 *
 *   **The question is "is this your team's rule", never "do you agree with
 *   the computer".** An architect cannot usefully audit a confidence number —
 *   that is rubber-stamping arithmetic. Whether a rule read out of a
 *   repository is really theirs is a question they can answer in ten seconds
 *   from knowledge the system does not have.
 *
 *   **Confirming does not re-run anything, and the screen says so.** Verdicts
 *   are never rewritten; the next run resolves the rule as ratified and the
 *   ceiling lifts. Without that sentence the screen looks broken: the badge
 *   does not move and the obvious conclusion is that the button did nothing.
 */

import { useState } from 'react'
import { Link } from 'react-router'
import { Button, Card, EmptyState, ErrorState, Pill, Spinner } from '../../components/ui'
import { decideReview, messageOf, type ReviewItem } from '../../lib/api'

export default function ReviewQueue({
  items,
  isLoading,
  error,
  onDecided,
}: {
  items: ReviewItem[]
  isLoading: boolean
  error: string | null
  onDecided: () => void
}) {
  const [deciding, setDeciding] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  const decide = async (itemId: string, accepted: boolean) => {
    setDeciding(itemId)
    setFailure(null)

    try {
      const result = await decideReview(itemId, accepted, 'architect')
      setOutcome(result.note)
      onDecided()
    } catch (cause) {
      setFailure(messageOf(cause))
    } finally {
      setDeciding(null)
    }
  }

  return (
    <Card
      title="Waiting on a person"
      action={
        items.length > 0 ? (
          <Pill tone="warn">{items.length}</Pill>
        ) : (
          <Pill tone="ok">none</Pill>
        )
      }
    >
      {isLoading && <Spinner label="reading the queue" />}
      {error && <ErrorState message={error} />}
      {failure && <ErrorState message={failure} />}

      {!isLoading && !error && items.length === 0 && (
        <EmptyState
          title="Nothing needs a person"
          body="Every dependency in this release rests on a source strong enough to stand on its own. That is a property of this repository rather than of the system — a repository whose decisions live in prose would fill this list."
        />
      )}

      <ul className="flex flex-col">
        {items.map((item) => (
          <li
            key={item.item_id}
            className="flex flex-col gap-5 border-b border-line py-7 first:pt-0 last:border-b-0 last:pb-0"
          >
            <div className="flex flex-wrap items-center justify-between gap-4">
              <span className="font-mono text-sm text-ink">{item.fact_id}</span>
              <div className="flex items-center gap-3">
                <Pill tone="warn">{item.bucket.replace(/_/g, ' ').toLowerCase()}</Pill>
                <span className="font-mono text-sm text-ink-2">
                  {item.confidence.toFixed(2)}
                </span>
              </div>
            </div>

            {item.source_tier && (
              <p className="text-xs text-ink-3">
                held back because the rule came from a{' '}
                {item.source_tier.replace(/_/g, ' ')} source
              </p>
            )}

            {item.evidence_refs.length > 0 && (
              <p className="font-mono text-xs leading-relaxed text-ink-3">
                {item.evidence_refs.join(' · ')}
              </p>
            )}

            <div className="flex flex-wrap items-center justify-between gap-5 border-t border-line pt-5">
              <span className="text-sm font-medium">Is this your team's rule?</span>
              <div className="flex items-center gap-3">
                <Button
                  variant="primary"
                  size="sm"
                  disabled={deciding === item.item_id}
                  onClick={() => decide(item.item_id, true)}
                >
                  Confirm
                </Button>
                <Button
                  size="sm"
                  disabled={deciding === item.item_id}
                  onClick={() => decide(item.item_id, false)}
                >
                  Not our rule
                </Button>
              </div>
            </div>
          </li>
        ))}
      </ul>

      {outcome && (
        <div className="mt-7 flex flex-col gap-4 border-t border-line pt-7">
          <p className="max-w-prose text-sm leading-relaxed text-ink-2">{outcome}</p>
          <Link to="/decisions">
            <Button size="sm">Run this release again</Button>
          </Link>
        </div>
      )}
    </Card>
  )
}
