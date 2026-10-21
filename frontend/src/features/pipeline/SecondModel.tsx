/**
 * Whether this run asks the second model anything.
 *
 * Description:
 *   One switch, and the only reason it is worth having is speed. On a
 *   per-minute token tier the verifier is the expensive half of a run — it
 *   spends more per call than the reasoner and there is one of each per fact
 *   — so turning it off roughly halves a cold run.
 *
 *   **The cost is stated beside the switch, not buried.** Off, every fact is
 *   published unverified: its confidence is capped, and the run reports
 *   verification as *not requested* rather than as agreement. That is the
 *   distinction the whole component is built to preserve, and a toggle that
 *   said only "faster" would be quietly trading it away.
 *
 *   **It is disabled while a run is going**, because it is read at the moment
 *   each release is sent. Flipping it halfway through a stack would produce
 *   a set of releases where some were audited and some were not, with
 *   nothing on the screen saying which — and a mixed stack is worse than
 *   either choice made deliberately.
 */

import { Pill } from '../../components/ui'

export default function SecondModel({
  verify,
  onChange,
  disabled,
}: {
  verify: boolean
  onChange: (verify: boolean) => void
  disabled: boolean
}) {
  return (
    <label
      className={`flex items-center gap-3 rounded-control border px-3.5 py-2 transition ${
        disabled
          ? 'cursor-not-allowed border-line opacity-50'
          : 'cursor-pointer border-line hover:border-line-strong'
      }`}
    >
      <input
        type="checkbox"
        checked={verify}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="h-3.5 w-3.5 accent-ai"
      />
      <span className="flex flex-col gap-0.5">
        <span className="font-mono text-xs whitespace-nowrap text-ink-2">
          second model
        </span>
        <span className="text-[10.5px] leading-tight whitespace-nowrap text-ink-4">
          {verify ? 'challenges every verdict' : 'off — facts publish unverified'}
        </span>
      </span>
      {!verify && <Pill tone="warn">capped</Pill>}
    </label>
  )
}
