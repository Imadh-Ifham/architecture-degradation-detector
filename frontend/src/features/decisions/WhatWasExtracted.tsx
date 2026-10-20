/**
 * What a mode actually extracted, by kind.
 *
 * Description:
 *   The record count on its own is the number most likely to be misread. A
 *   configuration scan over this corpus reports eighty-four rules, and
 *   sixty-six of them declare an operation a service exposes. No observed
 *   dependency carries an operation, so those sixty-six are held in the
 *   decision log, reported in every count, and govern nothing. The number
 *   that bears on the architecture is the other eighteen.
 *
 *   **So the headline here is the governing count, with the total beside
 *   it** — not instead of it. The total is what was extracted and is the
 *   honest measure of the scan; the governing count is what can be judged
 *   against and is the honest measure of the coverage. Reporting either one
 *   alone invites a question the screen cannot answer.
 *
 *   Each kind gets a sentence saying what it is and whether it governs. The
 *   sentences are written here because they explain a vocabulary rather than
 *   a measurement — nothing in them is a number, so nothing in them can go
 *   stale against the backend. The counts are entirely the backend's, and
 *   `governing` is computed there from the same table the resolver uses, so
 *   a constraint that stops governing a relationship stops being counted on
 *   the same day.
 */

import { Pill } from '../../components/ui'
import type { ModeAvailability } from '../../lib/api'

/** What each constraint is, and whether an observed dependency can meet it. */
const KIND: Record<string, { label: string; body: string; governs: boolean }> = {
  may_call: {
    label: 'may call',
    body: 'A policy names this pair and permits it. These are what confirm a dependency.',
    governs: true,
  },
  must_not_call: {
    label: 'must not call',
    body: 'A refusal. One of these selects every element and is the default deny — it is what makes the absence of a permission mean something rather than nothing.',
    governs: true,
  },
  must_call_via: {
    label: 'must call via',
    body: 'A required intermediary, or where a workload declares its identity. It governs a pair when it names one.',
    governs: true,
  },
  declared_rpc: {
    label: 'declared operation',
    body: 'An operation a service contract exposes. It governs nothing today: an observed dependency carries no operation, so there is nothing to compare it with. It is kept because the day a fact names an operation, the rule is already in the log and dated.',
    governs: false,
  },
}

export default function WhatWasExtracted({ mode }: { mode: ModeAvailability }) {
  const kinds = Object.entries(mode.by_constraint).sort((a, b) => b[1] - a[1])

  if (kinds.length === 0) return null

  const inert = mode.records - mode.governing

  return (
    <div className="flex flex-col gap-6 rounded-card border border-line bg-sunken px-6 py-5">
      <div className="flex flex-wrap items-baseline gap-4">
        <span className="text-xs tracking-wide text-ink-4">what it extracted</span>
        <span className="font-mono text-sm text-ink">
          {mode.records} record{mode.records === 1 ? '' : 's'}
        </span>
        <Pill tone={mode.governing > 0 ? 'ok' : 'warn'}>
          {mode.governing} can govern a dependency
        </Pill>
      </div>

      <ul className="flex flex-col gap-4">
        {kinds.map(([kind, count]) => {
          const described = KIND[kind]

          return (
            <li key={kind} className="flex gap-4">
              <span
                className={`w-10 shrink-0 text-right font-mono text-sm ${
                  described?.governs === false ? 'text-ink-4' : 'text-ink'
                }`}
              >
                {count}
              </span>
              <span className="flex min-w-0 flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2.5">
                  <span className="font-mono text-xs text-ink-2">
                    {described?.label ?? kind.replace(/_/g, ' ')}
                  </span>
                  {described?.governs === false && (
                    <Pill>governs nothing yet</Pill>
                  )}
                </span>
                {described && (
                  <span className="max-w-prose text-xs leading-relaxed text-ink-4">
                    {described.body}
                  </span>
                )}
              </span>
            </li>
          )
        })}
      </ul>

      {inert > 0 && (
        <p className="max-w-prose border-t border-line pt-4 text-xs leading-relaxed text-ink-3">
          <span className="text-ink">Read the two numbers together.</span> The{' '}
          {mode.records} is what the sources found and is the measure of the
          extraction. The {mode.governing} is what a dependency can be judged
          against and is the measure of the coverage. The remaining {inert}{' '}
          {inert === 1 ? 'record is' : 'records are'} real and dated and in the
          log — they simply describe something no observed fact carries yet, so
          quoting the total as the number of rules governing this architecture
          would overstate it by {(mode.records / Math.max(mode.governing, 1)).toFixed(1)}×.
        </p>
      )}
    </div>
  )
}
