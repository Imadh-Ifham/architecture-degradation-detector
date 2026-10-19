/**
 * The validated architecture graph, as an artifact.
 *
 * Description:
 *   The canvas above it is a picture of this document; this is the document.
 *   It is the one thing that crosses the boundary to the next phase, so what
 *   it carries is worth showing rather than describing: a consumer that
 *   ignores a field is not wrong, but a consumer that never knew the field
 *   existed is working with less than it was given.
 *
 *   **The field lists are read off the document itself**, not written here.
 *   A list typed into a screen goes stale the first time the document gains
 *   a field, and then the screen is quietly lying about the contract. Reading
 *   the keys means this panel is correct by construction.
 *
 *   It says what is published and nothing about what the next phase does
 *   with it. That screen belongs to whoever builds that phase.
 */

import { Card, Pill } from '../../components/ui'
import type { PublishedGraph } from '../../lib/api'

export default function Handover({
  document,
  publishedRef,
}: {
  document: PublishedGraph
  publishedRef?: string | null
}) {
  const node = document.nodes[0]
  const edge = document.links[0]

  return (
    <Card
      title="What is handed on"
      action={<Pill>schema {document.graph.schema_version}</Pill>}
    >
      <div className="flex flex-col gap-8">
        <div className="flex flex-col gap-2">
          <span className="text-xs tracking-wide text-ink-4">the published artifact</span>
          <code className="font-mono text-xs leading-relaxed break-all text-ink-2">
            {publishedRef ?? `${document.graph.repository_id} · ${document.graph.release_id} · latest.graph.json`}
          </code>
          <span className="text-xs leading-relaxed text-ink-4">
            A node-link document, written once per run, with a pointer moved to
            the newest completed one. The next phase reads this file — not this
            application.
          </span>
        </div>

        <div className="grid gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-3">
          <Count label="elements" value={document.nodes.length} />
          <Count label="dependencies" value={document.links.length} />
          <Count
            label="confidence"
            value={document.graph.validation_confidence.toFixed(2)}
            note="below a threshold, a consumer drops the release"
          />
        </div>

        <div className="grid gap-7 lg:grid-cols-3">
          <Fields
            title="on the graph"
            note="which release this is, and how far it can be trusted"
            keys={Object.keys(document.graph)}
          />
          <Fields
            title="on every element"
            note="identity, size, and the verdicts about it"
            keys={node ? Object.keys(node) : []}
          />
          <Fields
            title="on every dependency"
            note="the verdict, and how it was produced"
            keys={edge ? Object.keys(edge) : []}
          />
        </div>

        <p className="max-w-prose border-t border-line pt-6 text-sm leading-relaxed text-ink-3">
          <span className="text-ink">Two fields decide how the rest should be read.</span>{' '}
          <code className="font-mono text-xs text-ink-2">produced_by</code> says whether a
          model reached the verdict or a deterministic rule decided it alone, and{' '}
          <code className="font-mono text-xs text-ink-2">verification_outcome</code> says
          whether anything independent checked it. A dependency decided without a
          model and one nothing audited are both capped before they get here, so
          averaging them with a fully judged one averages two different things.
        </p>
      </div>
    </Card>
  )
}

function Count({
  label,
  value,
  note,
}: {
  label: string
  value: string | number
  note?: string
}) {
  return (
    <div className="flex flex-col gap-1.5 bg-panel px-6 py-5">
      <span className="text-xs tracking-wide text-ink-4">{label}</span>
      <span className="font-mono text-2xl leading-none text-ink">{value}</span>
      {note && <span className="text-[11px] leading-relaxed text-ink-4">{note}</span>}
    </div>
  )
}

function Fields({
  title,
  note,
  keys,
}: {
  title: string
  note: string
  keys: string[]
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium text-ink">{title}</span>
        <span className="text-xs leading-relaxed text-ink-4">{note}</span>
      </div>
      <ul className="flex flex-wrap gap-1.5">
        {keys.map((key) => (
          <li
            key={key}
            className="rounded-[4px] border border-line bg-sunken px-2 py-1 font-mono text-[11px] text-ink-2"
          >
            {key}
          </li>
        ))}
        {keys.length === 0 && (
          <li className="font-mono text-[11px] text-ink-4">nothing published yet</li>
        )}
      </ul>
    </div>
  )
}
