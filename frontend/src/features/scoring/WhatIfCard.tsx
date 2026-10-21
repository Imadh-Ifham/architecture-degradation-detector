/**
 * Try other weights.
 *
 * Description:
 *   One slider per part in use, starting at the saved (AHP) weights. Moving
 *   one re-ranks the list here and now, exactly as the backend would, and
 *   each row says how far it moved from the saved ranking. It answers "would
 *   the top change if somebody judged it differently?" - and it is never
 *   saved: the ranking above stays the one the run produced.
 */

import { useMemo, useState } from 'react'
import { Button, Card } from '../../components/ui'
import type { Dimension, SeverityReportV1 } from '../../lib/api'
import { DIMENSIONS, percent, score, subject, weightsOf } from './dimensions'
import { normalised, rerank } from './reweight'

export default function WhatIfCard({ report }: { report: SeverityReportV1 }) {
  const records = useMemo(() => report.records ?? [], [report])
  const saved = useMemo(() => weightsOf(report), [report])
  const active = report.active_dimensions
  const parts = DIMENSIONS.filter((d) => active.includes(d.key))

  const [weights, setWeights] = useState<Partial<Record<Dimension, number>>>(saved)
  const scaled = normalised(weights, active)
  const rescored = useMemo(() => rerank(records, active, scaled), [records, active, scaled])
  const byId = new Map(records.map((record) => [record.event_id, record]))
  const changed = rescored.some((item) => byId.get(item.eventId)?.rank !== item.rank)
  const isSaved = parts.every((d) => Math.abs((scaled[d.key] ?? 0) - (saved[d.key] ?? 0)) < 1e-9)

  if (records.length < 2 || parts.length < 2) return null

  return (
    <Card
      title="Try other weights"
      action={
        <span className="text-xs text-ink-4">
          a what-if on this page only; the saved ranking above does not change
        </span>
      }
    >
      <div className="grid gap-8 lg:grid-cols-[minmax(0,20rem)_1fr]">
        <div className="flex flex-col gap-5">
          {parts.map((d) => (
            <label key={d.key} className="flex flex-col gap-2">
              <span className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2 text-ink">
                  <span className={`size-2 rounded-full ${d.fill}`} />
                  {d.label}
                </span>
                <span className="font-mono text-xs text-ink-2">
                  {percent(scaled[d.key] ?? 0)}
                  <span className="text-ink-4"> (saved {percent(saved[d.key] ?? 0)})</span>
                </span>
              </span>
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                value={Math.round((weights[d.key] ?? 0) * 100)}
                onChange={(event) =>
                  setWeights({ ...weights, [d.key]: Number(event.target.value) / 100 })
                }
                className="accent-ai"
              />
            </label>
          ))}
          <div className="flex items-center gap-3">
            <Button size="sm" variant="quiet" disabled={isSaved} onClick={() => setWeights(saved)}>
              Back to the saved weights
            </Button>
            <span className="text-xs text-ink-4">
              {isSaved
                ? 'saved weights: same ranking as above'
                : changed
                  ? 'the order changed'
                  : 'same order, different scores'}
            </span>
          </div>
        </div>

        <ol className="flex flex-col divide-y divide-line rounded-card border border-line">
          {rescored.map((item) => {
            const record = byId.get(item.eventId)
            const moved = (record?.rank ?? item.rank) - item.rank
            return (
              <li key={item.eventId} className="flex items-center gap-4 px-4 py-2.5 text-sm">
                <span className="w-6 font-mono text-ink-3">{item.rank}</span>
                <span className="min-w-0 flex-1 truncate text-ink">
                  {record ? subject(record) : item.eventId}
                </span>
                <span className="w-10 text-right font-mono text-ink-2">{score(item.severity)}</span>
                <span
                  className={`w-20 text-right font-mono text-xs ${
                    moved > 0 ? 'text-ink' : moved < 0 ? 'text-ink-3' : 'text-ink-4'
                  }`}
                >
                  {moved > 0 ? `↑${moved}` : moved < 0 ? `↓${-moved}` : 'same'}
                </span>
              </li>
            )
          })}
        </ol>
      </div>
    </Card>
  )
}
