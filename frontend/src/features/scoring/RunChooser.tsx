/**
 * Which ranking the screen shows, and which one it is compared with.
 *
 * Description:
 *   The rankings are split by where their events came from, because that is
 *   the first thing a reader needs to know about one: **from the pipeline**
 *   (detection's own output for a repository) or **example data** (hand-made
 *   events, shown to explain how scoring works). Each is named in words, with
 *   the release, how many events it read and when it was made beside it.
 *   A pipeline ranking is made per detection run, so only the newest is shown
 *   until somebody asks for the earlier ones.
 */

import { useState } from 'react'
import { Card } from '../../components/ui'
import type { ScoringRunSummary } from '../../lib/api'
import { runMeta, runTitle } from './dimensions'

export default function RunChooser({
  runs,
  value,
  comparable,
  compareValue,
  onChange,
  onCompare,
}: {
  runs: ScoringRunSummary[]
  value: string
  comparable: ScoringRunSummary[]
  compareValue: string
  onChange: (runId: string) => void
  onCompare: (runId: string) => void
}) {
  const pipeline = runs.filter((run) => run.data_provenance === 'live')
  const examples = runs.filter((run) => run.data_provenance !== 'live')

  return (
    <Card
      title="Which ranking"
      action={
        comparable.length > 0 && (
          <label className="flex items-center gap-2.5 text-xs text-ink-4">
            compare with
            <select
              value={compareValue}
              onChange={(event) => onCompare(event.target.value)}
              className="rounded-control border border-line-strong bg-raised px-2 py-1 text-xs text-ink focus:border-ai focus:outline-none"
            >
              <option value="">nothing</option>
              {comparable.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {runTitle(run)}
                </option>
              ))}
            </select>
          </label>
        )
      }
    >
      <div className="grid gap-7 lg:grid-cols-2">
        <Group
          title="From the pipeline"
          note="Detection's own output for a repository, scored with its real history."
          empty="None yet: press Score on the pipeline after detection has run."
          runs={pipeline}
          value={value}
          onChange={onChange}
          newestOnly
        />
        <Group
          title="Example data"
          note="Hand-made events, to show how scoring works. Each says so on its banner."
          empty="No example rankings on this machine."
          runs={examples}
          value={value}
          onChange={onChange}
        />
      </div>
    </Card>
  )
}

function Group({
  title,
  note,
  empty,
  runs,
  value,
  onChange,
  newestOnly = false,
}: {
  title: string
  note: string
  empty: string
  runs: ScoringRunSummary[]
  value: string
  onChange: (runId: string) => void
  /** Show the newest only (and the selected one), with the rest behind a toggle. */
  newestOnly?: boolean
}) {
  const [showAll, setShowAll] = useState(false)
  const folded = newestOnly && !showAll
  const visible = folded ? runs.filter((run, index) => index === 0 || run.run_id === value) : runs
  const hidden = runs.length - visible.length

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h3 className="text-sm text-ink">{title}</h3>
        <p className="text-xs leading-relaxed text-ink-4">{note}</p>
      </div>
      {runs.length === 0 ? (
        <p className="text-xs text-ink-4">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {visible.map((run) => {
            const isSelected = run.run_id === value
            return (
              <li key={run.run_id}>
                <button
                  type="button"
                  aria-pressed={isSelected}
                  onClick={() => onChange(run.run_id)}
                  className={`flex w-full flex-col gap-1 rounded-control border px-3.5 py-2.5 text-left transition ${
                    isSelected
                      ? 'border-ai bg-ai-wash'
                      : 'border-line bg-panel hover:border-line-strong hover:bg-raised'
                  }`}
                >
                  <span className="text-sm text-ink">{runTitle(run)}</span>
                  <span className="font-mono text-[11px] text-ink-4">{runMeta(run)}</span>
                </button>
              </li>
            )
          })}
          {(hidden > 0 || (newestOnly && showAll && runs.length > 1)) && (
            <li>
              <button
                type="button"
                onClick={() => setShowAll(!showAll)}
                className="font-mono text-[11px] text-ink-3 underline-offset-4 hover:text-ink hover:underline"
              >
                {showAll ? 'show the newest only' : `${hidden} earlier run${hidden === 1 ? '' : 's'}`}
              </button>
            </li>
          )}
        </ul>
      )}
    </section>
  )
}
