/**
 * Architecture screen.
 *
 * Description:
 *   One release of one system, as the analysis stored it: the diagram, the
 *   elements, the dependencies, and — for whatever is selected — the evidence
 *   that put it there.
 *
 *   **The drawing stays the primary view.** Selecting a node or an edge opens
 *   a detail panel underneath it rather than navigating anywhere, so the
 *   picture stays on screen while its evidence is read. That is the whole
 *   interaction: click a box to ask what it is, click a line to ask why it
 *   exists.
 *
 *   **Evidence, not just conclusions.** The snapshot says what the analysis
 *   concluded; the artifacts beside the clone say why. They are joined by a
 *   second request, and every panel says which artifacts it could read — so a
 *   clone that has been removed shows less rather than lying.
 *
 *   **What the analysis could not resolve is shown.** An address naming
 *   something that is not in the architecture is a true statement about the
 *   repository, and this is the only screen where a person sees it.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeading,
  Pill,
  Spinner,
  Stat,
  StatRow,
  Tabs,
} from '../../components/ui'
import ReleasePicker from '../../components/ReleasePicker'
import { readSnapshot, readSnapshotDetails, type ArchitectureDetails } from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { useReleases } from '../../workspace/useReleases'
import { useWorkspace } from '../../workspace/useWorkspace'
import GraphCanvas, { GraphKey } from '../../components/graph/GraphCanvas'
import { recoveredGraph } from '../canvas/graphs'
import ComponentDetail, { type ElementGraphStats } from './ComponentDetail'
import RelationshipDetail from './RelationshipDetail'

type View = 'diagram' | 'elements' | 'dependencies'

/** What is being inspected, and which kind of thing it is. */
type Selection =
  | { kind: 'element'; id: string }
  | { kind: 'relationship'; id: string }
  | null

export default function ArchitecturePage() {
  const { repository, repositoryKey: key } = useWorkspace()
  const {
    snapshots,
    releases,
    release,
    selectRelease,
    error: releasesError,
    reload: reloadReleases,
  } = useReleases()

  const [view, setView] = useState<View>('diagram')
  // undefined until somebody selects or clears something; until then a linked
  // element (below) is what is selected
  const [chosen, setSelection] = useState<Selection | undefined>(undefined)
  const detailAnchor = useRef<HTMLDivElement>(null)

  // Another screen can link to one element of one release
  // (?release=v0.10.7&element=frontend, by name). The release is chosen once,
  // when the list of releases is there; the element is selected until somebody
  // selects or clears something themselves.
  const [params] = useSearchParams()
  const linkedRelease = params.get('release')
  const linkedElement = params.get('element')
  const releaseLinked = useRef(false)

  useEffect(() => {
    if (releaseLinked.current || !linkedRelease || !releases.includes(linkedRelease)) return
    releaseLinked.current = true
    selectRelease(linkedRelease)
  }, [linkedRelease, releases, selectRelease])

  const snapshotId =
    snapshots.find((item) => item.release_id === release)?.snapshot_id ?? null

  const snapshot = useRequest(
    (options) => readSnapshot(key, snapshotId ?? '', options),
    [key, snapshotId],
    Boolean(key && snapshotId),
  )

  // The evidence is a second request because it is a second question: the
  // snapshot is what was concluded, the details are why. Neither blocks the
  // other, and a missing details document degrades the panels rather than the
  // page.
  const details = useRequest(
    (options) => readSnapshotDetails(key, snapshotId ?? '', options),
    [key, snapshotId],
    Boolean(key && snapshotId),
  )

  const elements = useMemo(() => snapshot.data?.elements ?? [], [snapshot.data])

  const linkedId =
    linkedElement && (!linkedRelease || release === linkedRelease)
      ? elements.find((item) => item.name === linkedElement)?.id
      : undefined
  const selection: Selection =
    chosen !== undefined ? chosen : linkedId ? { kind: 'element', id: linkedId } : null

  // Selecting something opens a panel underneath the drawing, which on a full
  // page is below the fold - the click would otherwise look like it did
  // nothing. Scrolling the panel's top into view is what makes the response
  // legible; switching selection scrolls again so the new content is read from
  // its beginning rather than from wherever the last one was left.
  const selectedKey = selection ? `${selection.kind}:${selection.id}` : null

  useEffect(() => {
    if (!selectedKey) return

    const anchor = detailAnchor.current
    if (!anchor) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    anchor.scrollIntoView({
      behavior: reduced ? 'auto' : 'smooth',
      block: 'start',
    })
  }, [selectedKey])

  const relationships = useMemo(
    () => snapshot.data?.relationships ?? [],
    [snapshot.data],
  )

  const names = useMemo(
    () => new Map(elements.map((element) => [element.id, element.name])),
    [elements],
  )

  const detailById = useMemo(
    () => new Map((details.data?.elements ?? []).map((item) => [item.id, item])),
    [details.data],
  )

  const relationshipById = useMemo(
    () =>
      new Map((details.data?.relationships ?? []).map((item) => [item.id, item])),
    [details.data],
  )

  /** In, out and protocols per element, counted from the graph on screen. */
  const stats = useMemo(() => {
    const counted = new Map<string, ElementGraphStats>()

    const at = (id: string) => {
      const current = counted.get(id) ?? { incoming: 0, outgoing: 0, protocols: [] }
      counted.set(id, current)
      return current
    }

    for (const edge of relationships) {
      at(edge.source_id).outgoing += 1
      at(edge.target_id).incoming += 1

      const protocols = relationshipById.get(edge.id)?.protocols ?? []

      if (protocols.length > 0) {
        for (const end of [edge.source_id, edge.target_id]) {
          const entry = at(end)
          entry.protocols = [...new Set([...entry.protocols, ...protocols])].sort()
        }
      }
    }

    return counted
  }, [relationships, relationshipById])

  const graph = useMemo(
    () =>
      snapshot.data
        ? recoveredGraph(snapshot.data, details.data)
        : { nodes: [], edges: [] },
    [snapshot.data, details.data],
  )

  if (!repository || releases.length === 0) {
    return (
      <>
        <PageHeading eyebrow="recovered" title="Architecture" />
        <Card>
          <EmptyState
            title={repository ? 'Nothing analysed yet' : 'No system selected'}
            body="Recovery stores one architecture per release. Run the pipeline for a release and this screen reads what it stored."
            action={
              <Link to={repository ? '/' : '/repositories'}>
                <Button variant="primary">
                  {repository ? 'Run the pipeline' : 'Add a repository'}
                </Button>
              </Link>
            }
          />
        </Card>
      </>
    )
  }

  const chosenElement =
    selection?.kind === 'element' ? detailById.get(selection.id) ?? null : null

  const chosenRelationship =
    selection?.kind === 'relationship'
      ? relationshipById.get(selection.id) ?? null
      : null

  return (
    <>
      <PageHeading
        eyebrow="recovered"
        title="Architecture"
        description="The system as the analysis found it — every element, every dependency it could trace to evidence, and the evidence behind each one."
        action={
          <div className="flex flex-wrap items-center gap-5">
            <ReleasePicker
              releases={releases}
              value={release}
              onChange={(next) => {
                // Cleared because a selection is an id from the release that
                // was showing, and ids are not stable across releases: kept,
                // it either resolves to a different element or to nothing.
                setSelection(null)
                selectRelease(next)
              }}
            />
            <Link to="/">
              <Button size="sm" variant="quiet">
                Back to the pipeline
              </Button>
            </Link>
          </div>
        }
      />

      {releasesError && <ErrorState message={releasesError} onRetry={reloadReleases} />}
      {snapshot.isLoading && <Spinner label="reading the stored architecture" />}
      {snapshot.error && (
        <ErrorState message={snapshot.error} onRetry={snapshot.reload} />
      )}

      {snapshot.data && (
        <>
          <StatRow>
            <Stat label="elements" value={elements.length} note="in this release" />
            <Stat
              label="dependencies"
              value={relationships.length}
              note={`${relationships.filter((edge) => edge.confirmed_by_source).length} confirmed in source`}
            />
            <Stat
              label="unresolved"
              value={snapshot.data.unresolved.length}
              note="references naming nothing here"
              tone={snapshot.data.unresolved.length > 0 ? 'warn' : 'neutral'}
            />
            <Stat
              label="scan"
              value={snapshot.data.status}
              note={`ordered by ${snapshot.data.order_source.replace(/_/g, ' ')}`}
              tone={snapshot.data.status === 'complete' ? 'ok' : 'warn'}
            />
          </StatRow>

          <Card
            title={
              <Tabs
                tabs={[
                  { id: 'diagram', label: 'Diagram' },
                  { id: 'elements', label: 'Elements', count: elements.length },
                  {
                    id: 'dependencies',
                    label: 'Dependencies',
                    count: relationships.length,
                  },
                ]}
                active={view}
                onChange={setView}
              />
            }
            action={
              <span className="font-mono text-xs text-ink-4">
                {snapshot.data.snapshot_id}
              </span>
            }
          >
            {view === 'diagram' && (
              <>
                <GraphCanvas
                  nodes={graph.nodes}
                  edges={graph.edges}
                  selected={selection?.kind === 'element' ? selection.id : null}
                  onSelect={(id) =>
                    setSelection(id ? { kind: 'element', id } : null)
                  }
                  selectedEdge={
                    selection?.kind === 'relationship' ? selection.id : null
                  }
                  onSelectEdge={(id) =>
                    setSelection(id ? { kind: 'relationship', id } : null)
                  }
                  legend={
                    <>
                      <GraphKey tone="ok">confirmed in source</GraphKey>
                      <GraphKey>declared in configuration</GraphKey>
                      <GraphKey dashed>cache, database or broker</GraphKey>
                    </>
                  }
                />

                <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-xs text-ink-4">
                  <span>select an element or a dependency to read its evidence</span>
                  {details.isLoading && <span>reading the evidence…</span>}
                  {details.data && <ArtifactSummary details={details.data} />}
                </div>
              </>
            )}

            {view === 'elements' && (
              <Table
                head={['element', 'type', 'files', 'languages', 'in / out', 'size']}
                rows={elements.map((element) => {
                  const detail = detailById.get(element.id)
                  const counted = stats.get(element.id)
                  const isSelected =
                    selection?.kind === 'element' && selection.id === element.id

                  return {
                    key: element.id,
                    selected: isSelected,
                    onSelect: () =>
                      setSelection(
                        isSelected ? null : { kind: 'element', id: element.id },
                      ),
                    cells: [
                      element.name,
                      (detail?.detected.type ?? element.kind).replace(/_/g, ' '),
                      detail ? String(detail.detected.file_count ?? detail.files.length) : '—',
                      detail?.languages.join(', ') || '—',
                      counted ? `${counted.incoming} / ${counted.outgoing}` : '0 / 0',
                      element.size !== null
                        ? `${element.size} ${element.size_unit ?? ''}`.trim()
                        : '—',
                    ],
                  }
                })}
              />
            )}

            {view === 'dependencies' && (
              <Table
                head={['from', 'to', 'kind', 'protocol', 'evidence', '']}
                rows={relationships.map((edge) => {
                  const detail = relationshipById.get(edge.id)
                  const isSelected =
                    selection?.kind === 'relationship' && selection.id === edge.id

                  return {
                    key: edge.id,
                    selected: isSelected,
                    onSelect: () =>
                      setSelection(
                        isSelected ? null : { kind: 'relationship', id: edge.id },
                      ),
                    cells: [
                      names.get(edge.source_id) ?? edge.source_id,
                      names.get(edge.target_id) ?? edge.target_id,
                      edge.kind.replace(/_/g, ' '),
                      detail
                        ? detail.protocols.length > 0
                          ? detail.protocols.join(', ')
                          : 'unknown'
                        : '—',
                      edge.confirmed_by_source
                        ? 'source and configuration'
                        : 'configuration',
                      isSelected ? 'selected' : 'inspect',
                    ],
                  }
                })}
              />
            )}
          </Card>

          {/* The scroll target: mounted only while something is selected, and
              offset for the sticky instrument bar so the panel's own header is
              not hidden underneath it. */}
          {selection && (
            <div ref={detailAnchor} className="flex flex-col gap-12 scroll-mt-28">
              {chosenElement && (
                <Card
                  title={
                    <span className="flex items-center gap-3 text-sm">
                      <span className="text-ink-4">element</span>
                      <span className="font-mono text-ink">{chosenElement.name}</span>
                    </span>
                  }
                  action={
                    <div className="flex items-center gap-3">
                      {chosenElement.detected.confidence && (
                        <Pill
                          tone={
                            chosenElement.detected.confidence === 'direct' ? 'ok' : 'warn'
                          }
                        >
                          {chosenElement.detected.confidence}
                        </Pill>
                      )}
                      <Button size="sm" variant="quiet" onClick={() => setSelection(null)}>
                        Close
                      </Button>
                    </div>
                  }
                >
                  <ComponentDetail
                    element={chosenElement}
                    stats={
                      stats.get(chosenElement.id) ?? {
                        incoming: 0,
                        outgoing: 0,
                        protocols: [],
                      }
                    }
                    details={details.data}
                  />
                </Card>
              )}

              {chosenRelationship && (
                <Card
                  title={
                    <span className="flex flex-wrap items-center gap-3 text-sm">
                      <span className="text-ink-4">dependency</span>
                      <span className="font-mono text-ink">
                        {names.get(chosenRelationship.source_id) ??
                          chosenRelationship.source_id}
                        {' → '}
                        {names.get(chosenRelationship.target_id) ??
                          chosenRelationship.target_id}
                      </span>
                    </span>
                  }
                  action={
                    <Button size="sm" variant="quiet" onClick={() => setSelection(null)}>
                      Close
                    </Button>
                  }
                >
                  <RelationshipDetail relationship={chosenRelationship} names={names} />
                </Card>
              )}

              {selection.kind === 'relationship' && !chosenRelationship && (
                <Card
                  title="Dependency"
                  action={
                    <Button size="sm" variant="quiet" onClick={() => setSelection(null)}>
                      Close
                    </Button>
                  }
                >
                  <EmptyState
                    title="No evidence for this dependency"
                    body="The snapshot records the edge, but the recovery artifacts for this release could not be read. The dependency itself is still a fact the graph records."
                  />
                </Card>
              )}
            </div>
          )}

          {snapshot.data.unresolved.length > 0 && (
            <Card
              title="Could not be resolved"
              action={<Pill tone="warn">{snapshot.data.unresolved.length}</Pill>}
            >
              <ul className="flex flex-col gap-4">
                {snapshot.data.unresolved.map((item) => (
                  <li key={`${item.stage}-${item.reference}`} className="flex flex-col gap-1.5">
                    <div className="flex flex-wrap items-center gap-3">
                      <code className="font-mono text-sm text-ink">{item.reference}</code>
                      <Pill>{item.stage.replace(/_/g, ' ')}</Pill>
                      <Pill>{item.status}</Pill>
                    </div>
                    <span className="text-xs leading-relaxed text-ink-3">
                      {item.reason || 'nothing in the architecture matches it'}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </>
  )
}

/** Which artifacts the evidence came from, and which were missing. */
function ArtifactSummary({ details }: { details: ArchitectureDetails }) {
  const present = details.artifacts.filter((item) => item.present).length

  return (
    <span className={present === details.artifacts.length ? '' : 'text-warn'}>
      evidence from {present} of {details.artifacts.length} artifacts
    </span>
  )
}

function Table({
  head,
  rows,
}: {
  head: string[]
  rows: {
    key: string
    cells: string[]
    selected?: boolean
    onSelect?: () => void
  }[]
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {head.map((cell) => (
              <th
                key={cell}
                className="border-b border-line px-4 py-3 text-left text-xs font-medium tracking-wide text-ink-3"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.key}
              onClick={row.onSelect}
              className={`transition ${
                row.onSelect ? 'cursor-pointer' : ''
              } ${row.selected ? 'bg-raised' : 'hover:bg-raised/50'}`}
            >
              {row.cells.map((cell, index) => (
                <td
                  key={index}
                  className={`border-b border-line px-4 py-3 ${
                    index === 0 ? 'font-mono text-ink' : 'text-ink-2'
                  }`}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
