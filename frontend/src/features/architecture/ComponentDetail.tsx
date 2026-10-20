/**
 * One component, as the artifacts describe it.
 *
 * Description:
 *   Everything recovery recorded about a single element, in the order a
 *   reader needs it: what it is, how it was found, the files that identify it,
 *   and the files inside it.
 *
 *   **Two kinds of number, kept apart.** `files`, `languages` and `file_count`
 *   were extracted by the inventory and discovery stages. Incoming, outgoing
 *   and total are counted here from the graph that is on screen, which is the
 *   only place they can be counted consistently with what is drawn.
 *
 *   Long lists are collapsed rather than truncating silently: a component with
 *   four hundred files is a real fact about a repository, and hiding the
 *   four hundredth while claiming to show them is the thing to avoid.
 */

import { useState } from 'react'
import { Pill } from '../../components/ui'
import type {
  ArchitectureDetails,
  DiscoveryEvidence,
  ElementDetails,
  ElementFile,
  SnapshotEvidenceEntry,
} from '../../lib/api'

const COLLAPSED = 8

export interface ElementGraphStats {
  incoming: number
  outgoing: number
  protocols: string[]
}

export default function ComponentDetail({
  element,
  stats,
  details,
}: {
  element: ElementDetails
  stats: ElementGraphStats
  details: ArchitectureDetails | null
}) {
  const detected = element.detected

  return (
    <div className="flex flex-col gap-9">
      <div className="grid gap-7 sm:grid-cols-2 lg:grid-cols-4">
        <Fact label="identifier" value={element.id} mono />
        <Fact label="type" value={detected.type ?? element.kind} />
        <Fact label="root path" value={detected.root_path ?? 'not recorded'} mono />
        <Fact
          label="identity"
          value={
            element.logical_id
              ? `${element.logical_id} (${element.identity_basis})`
              : 'no cross-release identity'
          }
          mono
        />
      </div>

      <Section title="How it was identified">
        <div className="grid gap-7 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="method" value={detected.method ?? 'not recorded'} mono />
          <Fact label="confidence" value={detected.confidence ?? 'not recorded'} />
          <Fact
            label="size"
            value={
              element.size !== null
                ? `${element.size} ${element.size_unit ?? ''}`.trim()
                : 'not measured'
            }
          />
          <Fact
            label="inventory kind"
            value={detected.inventory_kind ?? 'not recorded'}
          />
        </div>

        {element.discovery_evidence.length > 0 && (
          <Evidence
            title="discovery rules that fired"
            items={element.discovery_evidence.map(evidenceLine)}
          />
        )}

        {element.artifacts.length > 0 && (
          <div className="flex flex-col gap-3">
            <span className="text-xs tracking-wide text-ink-4">
              artifacts that named it
            </span>
            <ul className="flex flex-col gap-2">
              {element.artifacts.map((artifact) => (
                <li
                  key={artifact.id}
                  className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-l-2 border-line-strong pl-4"
                >
                  <code className="font-mono text-xs text-ink">{artifact.path}</code>
                  <span className="text-xs text-ink-3">
                    {[artifact.kind?.replace(/_/g, ' '), artifact.role?.replace(/_/g, ' ')]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  {artifact.confidence && <Pill>{artifact.confidence}</Pill>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      <Section title="Files">
        <div className="grid gap-7 sm:grid-cols-2 lg:grid-cols-4">
          <Fact
            label="files"
            value={detected.file_count ?? element.files.length}
            note="extracted by the inventory"
          />
          <Fact
            label="source files"
            value={element.source_file_count}
            note="extracted by the inventory"
          />
          <Fact
            label="languages"
            value={element.languages.length > 0 ? element.languages.join(', ') : 'none detected'}
            note="extracted from source files"
          />
          <Fact
            label="incoming / outgoing"
            value={`${stats.incoming} / ${stats.outgoing}`}
            note="counted from this graph"
          />
        </div>

        {stats.protocols.length > 0 && (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs tracking-wide text-ink-4">
              protocols on its dependencies
            </span>
            {stats.protocols.map((protocol) => (
              <Pill key={protocol} tone="ai">
                {protocol}
              </Pill>
            ))}
          </div>
        )}

        {element.files.length > 0 ? (
          <FileList files={element.files} />
        ) : (
          <p className="text-sm text-ink-3">
            No files were attributed to this component. The inventory attributes a
            file to a component only when the manifest owning it is known, so a
            component discovered from a deployment declaration has none.
          </p>
        )}
      </Section>

      <Section title="Stage evidence">
        <p className="max-w-prose text-xs leading-relaxed text-ink-4">
          What each recovery stage contributed to this element's presence in the
          graph. Declared means a file says so; the references are the artifact
          records behind the count.
        </p>
        <ul className="flex flex-col gap-2">
          {element.snapshot_evidence.map((entry) => (
            <li
              key={`${entry.stage}-${entry.type}`}
              className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-ink-2"
            >
              <span className="text-ink">{entry.stage.replace(/_/g, ' ')}</span>
              <span>{entry.type.replace(/_/g, ' ')}</span>
              <Pill tone={entry.declared ? 'ok' : 'neutral'}>
                {entry.declared ? 'declared' : 'inferred'}
              </Pill>
              <span className="text-ink-4">
                {entry.count} record{entry.count === 1 ? '' : 's'}
              </span>
            </li>
          ))}
        </ul>
      </Section>

      {details && details.artifacts.some((item) => !item.present) && (
        <MissingArtifacts details={details} />
      )}
    </div>
  )
}

/** The files, with the overflow behind one control rather than cut off. */
function FileList({ files }: { files: ElementFile[] }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? files : files.slice(0, COLLAPSED)

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-px overflow-hidden rounded-control border border-line bg-line">
        {shown.map((file) => (
          <li
            key={file.path}
            className="flex flex-wrap items-baseline justify-between gap-3 bg-panel px-4 py-2.5"
          >
            <code className="font-mono text-xs break-all text-ink">{file.path}</code>
            <span className="flex shrink-0 items-center gap-3 font-mono text-[11px] text-ink-4">
              {file.category && <span>{file.category.replace(/_/g, ' ')}</span>}
              {file.language && <span className="text-ink-3">{file.language}</span>}
              {file.size_bytes !== null && <span>{file.size_bytes} B</span>}
            </span>
          </li>
        ))}
      </ul>

      {files.length > COLLAPSED && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="self-start font-mono text-xs text-ink-2 underline-offset-4 hover:text-ink hover:underline"
        >
          {expanded ? 'show fewer' : `show all ${files.length} files`}
        </button>
      )}
    </div>
  )
}

export function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="flex flex-col gap-5 border-t border-line pt-7">
      <h3 className="font-mono text-[11px] tracking-wide text-ink-4 uppercase">
        {title}
      </h3>
      {children}
    </section>
  )
}

export function Fact({
  label,
  value,
  note,
  mono,
}: {
  label: string
  value: React.ReactNode
  note?: string
  mono?: boolean
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs tracking-wide text-ink-4">{label}</span>
      <span
        className={`text-sm leading-relaxed break-words ${
          mono ? 'font-mono text-ink-2' : 'text-ink-2'
        }`}
      >
        {value}
      </span>
      {note && <span className="text-[11px] text-ink-4">{note}</span>}
    </div>
  )
}

export function Evidence({ title, items }: { title: string; items: string[] }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? items : items.slice(0, COLLAPSED)

  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs tracking-wide text-ink-4">{title}</span>
      <ul className="flex flex-col gap-2">
        {shown.map((item, index) => (
          <li
            key={`${item}-${index}`}
            className="border-l-2 border-line-strong pl-4 font-mono text-xs leading-relaxed break-words text-ink-2"
          >
            {item}
          </li>
        ))}
      </ul>
      {items.length > COLLAPSED && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="self-start font-mono text-xs text-ink-2 underline-offset-4 hover:text-ink hover:underline"
        >
          {expanded ? 'show fewer' : `show all ${items.length}`}
        </button>
      )}
    </div>
  )
}

function evidenceLine(evidence: DiscoveryEvidence): string {
  const where = evidence.path
    ? `${evidence.path}${evidence.line ? `:${evidence.line}` : ''}`
    : 'no location recorded'

  return [where, evidence.rule, evidence.detail].filter(Boolean).join(' — ')
}

export function MissingArtifacts({ details }: { details: ArchitectureDetails }) {
  const absent = details.artifacts.filter((item) => !item.present)

  return (
    <p className="max-w-prose border-l-2 border-warn/60 pl-4 text-xs leading-relaxed text-warn">
      {absent.map((item) => item.file).join(', ')} could not be read for this
      release, so part of its evidence is unavailable. The clone is removed with
      the repository, and the snapshot outlives it — re-run recovery for this
      release to rebuild the artifacts.
    </p>
  )
}

export type { SnapshotEvidenceEntry }
