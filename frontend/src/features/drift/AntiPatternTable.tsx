/**
 * The anti-patterns found in one release.
 *
 * Description:
 *   One row per instance: what it is, which elements it is made of, what it
 *   measured, and what happened to it since the release before. Choosing a
 *   row narrows the graph above to its members.
 *
 *   **A detector that did not run is said, not implied.** A release in which
 *   a detector was skipped - shared persistence needs datastore access the
 *   release did not carry - has no instances of that type because nobody
 *   looked, which is a different statement from "there are none". The table
 *   names the detectors that ran so the two cannot be confused.
 */

import { EmptyState, Pill } from '../../components/ui'
import type { AntiPatternInstance, DriftRelease } from '../../lib/api'
import { antiPattern, figure, metricName, TRANSITION } from './labels'

export default function AntiPatternTable({
  release,
  focus,
  onFocus,
}: {
  release: DriftRelease
  focus: string | null
  onFocus: (instanceId: string | null) => void
}) {
  const names = new Map(release.elements.map((element) => [element.id, element.name]))

  return (
    <div className="flex flex-col gap-6">
      {release.instances.length === 0 ? (
        <EmptyState
          title="No anti-patterns in this release"
          body="None of the detectors that ran found an instance. The ones that ran are listed below; a detector that did not run found nothing because it did not look."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                {['anti-pattern', 'elements', 'measured', 'since the release before'].map(
                  (head) => (
                    <th
                      key={head}
                      className="border-b border-line px-4 py-3 text-left text-xs font-medium tracking-wide text-ink-3"
                    >
                      {head}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {release.instances.map((instance) => (
                <Row
                  key={instance.local_instance_id}
                  instance={instance}
                  names={names}
                  isFirst={release.ordinal === 0}
                  isFocused={instance.local_instance_id === focus}
                  onToggle={() =>
                    onFocus(
                      instance.local_instance_id === focus ? null : instance.local_instance_id,
                    )
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-baseline gap-3 border-t border-line pt-5">
        <span className="text-xs tracking-wide text-ink-4">detectors that ran</span>
        {release.detectors_run.map((type) => (
          <span
            key={type}
            title={antiPattern(type).means}
            className="rounded-[4px] border border-line bg-sunken px-2 py-1 font-mono text-[11px] text-ink-2"
          >
            {antiPattern(type).name}
          </span>
        ))}
      </div>
    </div>
  )
}

function Row({
  instance,
  names,
  isFirst,
  isFocused,
  onToggle,
}: {
  instance: AntiPatternInstance
  names: Map<string, string>
  /** The first release has no release before it, so nothing in it is "new". */
  isFirst: boolean
  isFocused: boolean
  onToggle: () => void
}) {
  const words = antiPattern(instance.anti_pattern_type)
  const measures = Object.entries(instance.measures)

  return (
    <tr
      onClick={onToggle}
      aria-selected={isFocused}
      className={`cursor-pointer transition ${isFocused ? 'bg-bad-wash' : 'hover:bg-raised/60'}`}
    >
      <td className="border-b border-line px-4 py-3.5 align-top">
        <span className="flex flex-col gap-1">
          <span className="text-ink">{words.name}</span>
          <span className="max-w-72 text-xs leading-relaxed text-ink-4">{words.means}</span>
        </span>
      </td>
      <td className="border-b border-line px-4 py-3.5 align-top font-mono text-xs text-ink-2">
        {instance.members.map((member) => names.get(member) ?? member).join(', ')}
      </td>
      <td className="border-b border-line px-4 py-3.5 align-top font-mono text-xs text-ink-3">
        {measures.length === 0
          ? '—'
          : measures.map(([name, value]) => (
              <span key={name} className="block">
                {metricName(name)} {figure(value)}
              </span>
            ))}
      </td>
      <td className="border-b border-line px-4 py-3.5 align-top">
        {isFirst ? (
          <span className="font-mono text-xs text-ink-4">first release</span>
        ) : instance.transition ? (
          <Pill
            tone={
              instance.transition === 'GREW' || instance.transition === 'INTRODUCED'
                ? 'bad'
                : instance.transition === 'SHRANK'
                  ? 'ok'
                  : 'neutral'
            }
          >
            {TRANSITION[instance.transition]}
          </Pill>
        ) : (
          <span className="font-mono text-xs text-ink-4">not tracked</span>
        )}
      </td>
    </tr>
  )
}
