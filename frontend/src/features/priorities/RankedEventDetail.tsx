/**
 * One ranked event, opened in place under its row.
 *
 * Description:
 *   How its score was built, part by part: the part's value on a 0-1 scale,
 *   the weight it carried and the share of the score it produced, with the raw
 *   measurements behind it. A part switched off for the run says so instead
 *   of showing 0, which would claim it was measured and found harmless.
 */

import { Pill } from '../../components/ui'
import type { SeverityRecord } from '../../lib/api'
import { DIMENSIONS, isActive, percent, plainType, reason } from './dimensions'

export default function RankedEventDetail({ record }: { record: SeverityRecord }) {
  return (
    <div className="flex flex-col gap-6 border-l-2 border-ink-4 bg-sunken px-6 py-5">
      <div className="flex flex-col gap-2">
        <p className="text-sm text-ink">{plainType(record.anti_pattern_type)}</p>
        <p className="text-sm text-ink-2">
          <span className="text-ink-4">Why it ranks #{record.rank}: </span>
          {reason(record)}
        </p>
        <div className="flex flex-wrap gap-2">
          <Pill>{record.scope === 'INSTANCE' ? 'a group of parts' : 'one part'}</Pill>
          <Pill>review {record.review_status.toLowerCase()}</Pill>
          {record.context_tag === 'UNCERTAIN' && <Pill tone="warn">context uncertain</Pill>}
          {record.resolution.status === 'prefix_fallback' && (
            <Pill tone="warn">
              matched by source path (confidence {record.resolution.confidence.toFixed(1)})
            </Pill>
          )}
          <Pill>{record.event_id}</Pill>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {DIMENSIONS.map((dimension) => {
          const part = record.dimensions[dimension.key]
          if (!part || !isActive(record, dimension.key)) {
            return (
              <div key={dimension.key} className="grid gap-1 sm:grid-cols-[12rem_1fr]">
                <span className="flex items-center gap-2 text-sm text-ink-4">
                  <span className="size-2 rounded-full bg-line-strong" />
                  {dimension.label}
                </span>
                <span className="text-sm text-ink-4">not used in this run</span>
              </div>
            )
          }
          const share = record.contributions[dimension.key] ?? 0
          return (
            <div key={dimension.key} className="grid gap-2 sm:grid-cols-[12rem_1fr]">
              <span className="flex items-center gap-2 text-sm text-ink">
                <span className={`size-2 rounded-full ${dimension.fill}`} />
                {dimension.label}
              </span>
              <div className="flex flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-xs text-ink-3">
                  <span>
                    value <span className="text-ink">{part.normalized.toFixed(2)}</span> of 1
                  </span>
                  <span>
                    × weight <span className="text-ink">{part.weight.toFixed(2)}</span>
                  </span>
                  <span>
                    → <span className="text-ink">{percent(share)}</span> of this score
                  </span>
                </div>
                <div className="h-1.5 w-full max-w-md overflow-hidden rounded-full bg-line">
                  <div
                    className={`h-full ${dimension.fill}`}
                    style={{ width: percent(share, 1) }}
                  />
                </div>
                <span className="font-mono text-xs text-ink-4">
                  {Object.entries(part.features ?? {})
                    .map(([name, value]) => `${name.replace(/_/g, ' ')} ${format(value)}`)
                    .join(' · ')}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function format(value: boolean | number | null): string {
  if (value === null) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return Number.isInteger(value) ? String(value) : value.toFixed(3)
}
