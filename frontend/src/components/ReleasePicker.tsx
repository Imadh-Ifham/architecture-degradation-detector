/**
 * The release a screen is showing.
 *
 * Description:
 *   A screen-level control, not a global one: the header changes which
 *   repository is being looked at, and this changes which release of it this
 *   screen renders. Two screens can therefore compare two releases without
 *   fighting over one answer.
 *
 *   With one release there is nothing to choose, so it states the release
 *   rather than offering a list of one. With none it renders nothing - the
 *   screen's own empty state says why there is nothing to show.
 */

import { Pill } from './ui'

export default function ReleasePicker({
  releases,
  value,
  onChange,
  label = 'release',
  disabled,
}: {
  releases: string[]
  value: string | null
  onChange: (releaseId: string) => void
  label?: string
  disabled?: boolean
}) {
  if (releases.length === 0 || !value) return null

  if (releases.length === 1) {
    return <Pill>{value}</Pill>
  }

  return (
    <label className="flex items-center gap-2.5 text-sm">
      <span className="text-xs text-ink-4">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label={`${label} for this screen`}
        disabled={disabled}
        className="rounded-control border border-line-strong bg-raised px-2.5 py-1 font-mono text-sm text-ink focus:border-ai focus:outline-none"
      >
        {releases.map((release) => (
          <option key={release} value={release}>
            {release}
          </option>
        ))}
      </select>
    </label>
  )
}
