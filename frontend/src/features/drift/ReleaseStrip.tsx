/**
 * The releases of a run, in order, as one row of steps.
 *
 * Description:
 *   Each release the validation phase published, labelled with its tag, its
 *   date, how far its validation can be trusted and how many anti-patterns
 *   were found in it. Choosing one draws it below; the arrows step through
 *   them in order.
 *
 *   **The order is the timeline's, not the tags'.** Releases are ordered by
 *   date, because `v1.10.0` sorts before `v1.9.0` as text, and a series in the
 *   wrong order is a trend that is not there.
 *
 *   **Every validated release is in the row, in date order** - including the
 *   ones the run left off its timeline, drawn dimmed and dashed with the
 *   reason on them. "I validated sixteen and it shows eight" is a question
 *   this row should answer before somebody asks it, and a list under it was
 *   too easy to miss. Those cells cannot be chosen: nothing was detected in
 *   them, so there is no graph of anti-patterns to draw.
 */

import { useEffect, useRef } from 'react'
import { Pill } from '../../components/ui'
import type { DriftRelease } from '../../lib/api'
import { GATE } from './labels'

export default function ReleaseStrip({
  releases,
  selected,
  onSelect,
}: {
  releases: DriftRelease[]
  selected: string | null
  onSelect: (releaseId: string) => void
}) {
  const timeline = releases.filter((release) => release.on_timeline)
  const most = Math.max(1, ...timeline.map((release) => release.instances.length))
  // Scrolled to the chosen release: with early releases left off the timeline
  // in front of it, the one being drawn would otherwise sit out of view.
  const strip = useRef<HTMLOListElement>(null)
  useEffect(() => {
    const row = strip.current
    const cell = row?.querySelector<HTMLElement>('[aria-pressed="true"]')?.parentElement
    if (!row || !cell) return
    row.scrollLeft = cell.offsetLeft - row.clientWidth / 2 + cell.clientWidth / 2
  }, [selected, releases])

  const ordered = [...releases].sort(
    (a, b) => a.released_at.localeCompare(b.released_at) || a.release_id.localeCompare(b.release_id),
  )

  return (
    <div className="flex flex-col gap-5">
      <ol ref={strip} className="relative flex gap-px overflow-x-auto rounded-card border border-line bg-line">
        {ordered.map((release) => {
          if (!release.on_timeline) return <Excluded key={release.release_id} release={release} />

          const index = timeline.indexOf(release)
          const isSelected = release.release_id === selected
          const gate = GATE[release.gate_status]
          const count = release.instances.length

          return (
            <li key={release.release_id} className="min-w-40 flex-1">
              <button
                type="button"
                onClick={() => onSelect(release.release_id)}
                aria-pressed={isSelected}
                className={`flex h-full w-full flex-col gap-3 px-5 py-4 text-left transition ${
                  isSelected ? 'bg-raised' : 'bg-panel hover:bg-raised/60'
                }`}
              >
                <span className="flex items-baseline justify-between gap-3">
                  <span className="font-mono text-[11px] text-ink-4">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span className="font-mono text-[11px] text-ink-4">
                    {release.released_at.slice(0, 10)}
                  </span>
                </span>

                <span
                  className={`font-mono text-sm ${isSelected ? 'text-ink' : 'text-ink-2'}`}
                >
                  {release.release_id}
                </span>

                {/* How many anti-patterns, as a bar against the release with
                    the most - so the strip itself reads as a trend. */}
                <span className="flex flex-col gap-1.5">
                  <span className="h-1 w-full overflow-hidden rounded-full bg-line">
                    <span
                      className={`block h-full rounded-full ${count ? 'bg-bad/70' : ''}`}
                      style={{ width: `${(count / most) * 100}%` }}
                    />
                  </span>
                  <span className="font-mono text-[11px] text-ink-3">
                    {count} anti-pattern{count === 1 ? '' : 's'}
                  </span>
                </span>

                <span className="flex flex-wrap gap-2">
                  <Pill tone={gate.tone}>{gate.label}</Pill>
                  <span className="font-mono text-[11px] text-ink-4">
                    {release.validation_confidence.toFixed(2)}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>

    </div>
  )
}

/** A validated release the run did not use, with why - so it is seen, not searched for. */
function Excluded({ release }: { release: DriftRelease }) {
  const gate = GATE[release.gate_status]

  return (
    <li className="min-w-40 flex-1">
      <div
        title={release.absent_because ?? undefined}
        className="flex h-full flex-col gap-3 bg-sunken px-5 py-4 opacity-60 outline-1 -outline-offset-4 outline-line-strong outline-dashed"
      >
        <span className="flex items-baseline justify-between gap-3">
          <span className="font-mono text-[11px] text-ink-4">—</span>
          <span className="font-mono text-[11px] text-ink-4">
            {release.released_at.slice(0, 10)}
          </span>
        </span>
        <span className="font-mono text-sm text-ink-3 line-through decoration-ink-4">
          {release.release_id}
        </span>
        <span className="text-[11px] leading-snug text-ink-4">{release.absent_because}</span>
        <span className="flex flex-wrap gap-2">
          <Pill tone={release.gate_status === 'EXCLUDED' ? gate.tone : 'neutral'}>
            {release.gate_status === 'EXCLUDED' ? gate.label : 'not used'}
          </Pill>
          <span className="font-mono text-[11px] text-ink-4">
            {release.validation_confidence.toFixed(2)}
          </span>
        </span>
      </div>
    </li>
  )
}
