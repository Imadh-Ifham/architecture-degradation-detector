/**
 * A cold run: ask every question live instead of replaying the answers.
 *
 * Description:
 *   An ordinary run replays identical questions from the response cache, so
 *   a release that has been validated once validates again in about a
 *   second. That is the right default and it is not a shortcut — a replayed
 *   answer is the same model's answer to the same question, keyed on a hash
 *   of the evidence.
 *
 *   **This is for when the question has changed, or when you want to watch
 *   it being asked.** A release whose files moved, a prompt that was edited,
 *   a model that was swapped — or a demonstration where somebody wants to
 *   see the calls happen rather than be told they happened.
 *
 *   **It refreshes rather than empties.** The run pays for every answer and
 *   the cache keeps the new ones, so the next ordinary run is fast again.
 *   Deleting the cache directory by hand does not do that: it leaves every
 *   other release cold as well, and they then cost their minutes back one at
 *   a time.
 *
 *   The price is on the control, because it is the whole decision. A cold,
 *   fully verified release is minutes against a second — on a per-minute
 *   token tier that is the provider's limit, not this code's.
 */

import { Pill } from '../../components/ui'

export default function ColdRun({
  fresh,
  onChange,
  disabled,
}: {
  fresh: boolean
  onChange: (fresh: boolean) => void
  disabled: boolean
}) {
  return (
    <label
      className={`flex items-center gap-3 rounded-control border px-3.5 py-2 transition ${
        disabled
          ? 'cursor-not-allowed border-line opacity-50'
          : fresh
            ? 'cursor-pointer border-warn/60'
            : 'cursor-pointer border-line hover:border-line-strong'
      }`}
    >
      <input
        type="checkbox"
        checked={fresh}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="h-3.5 w-3.5 accent-warn"
      />
      <span className="flex flex-col gap-0.5">
        <span className="font-mono text-xs whitespace-nowrap text-ink-2">
          cold run — ask the models live
        </span>
        {/* "resets the cache" would be the wrong words and the wrong promise.
            Nothing is deleted: the run ignores what is stored, asks every
            question again, and writes the new answers over the old. Deleting
            the directory is a different and worse thing - it leaves every
            other release cold too. */}
        <span className="text-[10.5px] leading-tight whitespace-nowrap text-ink-4">
          {fresh
            ? 'ignores the cache, asks every question again — minutes'
            : 'warm — replays the models’ own answers in seconds'}
        </span>
      </span>
      {fresh && <Pill tone="warn">live</Pill>}
    </label>
  )
}
