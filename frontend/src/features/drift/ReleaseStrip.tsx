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
 *   Releases that are stored but not on the timeline are drawn after it, set
 *   apart and with the reason, rather than left out: "why is v2.0.0-rc1
 *   missing" is a question this row should answer before somebody asks it.
 */

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
  const elsewhere = releases.filter((release) => !release.on_timeline)
  const most = Math.max(1, ...timeline.map((release) => release.instances.length))

  return (
    <div className="flex flex-col gap-5">
      <ol className="flex gap-px overflow-x-auto rounded-card border border-line bg-line">
        {timeline.map((release, index) => {
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

      {elsewhere.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-xs tracking-wide text-ink-4">
            validated, but not on the timeline
          </span>
          <ul className="flex flex-wrap gap-x-6 gap-y-2">
            {elsewhere.map((release) => (
              <li key={release.release_id} className="flex items-baseline gap-2.5">
                <span className="font-mono text-xs text-ink-2">{release.release_id}</span>
                <span className="text-xs text-ink-4">{release.absent_because}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
