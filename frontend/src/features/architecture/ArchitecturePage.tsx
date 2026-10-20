/**
 * Architecture screen.
 *
 * Description:
 *   One release of one system, as the analysis stored it: the diagram, the
 *   elements, and the dependencies between them. Three tabs over one
 *   snapshot, because they are three views of the same thing and not three
 *   screens.
 *
 *   The release list comes from the stored history rather than from anything
 *   this screen remembers, so a release analysed a minute ago is in the list
 *   without a refresh of anything else.
 *
 *   **What the analysis could not resolve is shown.** An address naming
 *   something that is not in the architecture is a true statement about the
 *   repository, and this is the only screen where a person sees it.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router'
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
import { readSnapshot } from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { useReleases } from '../../workspace/useReleases'
import { useWorkspace } from '../../workspace/useWorkspace'
import ReleasePicker from '../../components/ReleasePicker'
import GraphCanvas, { GraphKey } from '../../components/graph/GraphCanvas'
import { recoveredGraph } from '../canvas/graphs'

type View = 'diagram' | 'elements' | 'dependencies'

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
  const [selected, setSelected] = useState<string | null>(null)

  const chosen =
    snapshots.find((item) => item.release_id === release)?.snapshot_id ?? null

  const snapshot = useRequest(
    (options) => readSnapshot(key, chosen ?? '', options),
    [key, chosen],
    Boolean(key && chosen),
  )

  const elements = useMemo(() => snapshot.data?.elements ?? [], [snapshot.data])
  const relationships = useMemo(
    () => snapshot.data?.relationships ?? [],
    [snapshot.data],
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

  return (
    <>
      <PageHeading
        eyebrow="recovered"
        title="Architecture"
        description="The system as the analysis found it — every element, and every dependency it could trace to evidence."
        action={
          <ReleasePicker releases={releases} value={release} onChange={selectRelease} />
        }
      />

      {releasesError && <ErrorState message={releasesError} onRetry={reloadReleases} />}

      {snapshot.isLoading && <Spinner label="reading the stored architecture" />}

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
            {!snapshot.isLoading && view === 'diagram' && (
              <GraphCanvas
                {...recoveredGraph(snapshot.data)}
                selected={selected}
                onSelect={setSelected}
                legend={
                  <>
                    <GraphKey tone="ok">confirmed in source</GraphKey>
                    <GraphKey>declared in configuration</GraphKey>
                    <GraphKey dashed>cache, database or broker</GraphKey>
                  </>
                }
              />
            )}

            {!snapshot.isLoading && view === 'elements' && (
              <Table
                head={['element', 'kind', 'identity', 'size']}
                rows={elements.map((element) => [
                  element.name,
                  element.kind.replace(/_/g, ' '),
                  element.logical_id ? element.identity_basis : 'not assigned',
                  element.size ? `${element.size} ${element.size_unit ?? ''}` : '—',
                ])}
              />
            )}

            {!snapshot.isLoading && view === 'dependencies' && (
              <Table
                head={['from', 'to', 'kind', 'evidence']}
                rows={relationships.map((edge) => [
                  name(elements, edge.source_id),
                  name(elements, edge.target_id),
                  edge.kind.replace(/_/g, ' '),
                  edge.confirmed_by_source ? 'source and configuration' : 'configuration',
                ])}
              />
            )}
          </Card>

          {snapshot.data.unresolved.length > 0 && (
            <Card
              title="Could not be resolved"
              action={<Pill tone="warn">{snapshot.data.unresolved.length}</Pill>}
            >
              <ul className="flex flex-col gap-4">
                {snapshot.data.unresolved.map((item) => (
                  <li key={item.reference} className="flex flex-col gap-1.5">
                    <code className="font-mono text-sm text-ink">{item.reference}</code>
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

function Table({ head, rows }: { head: string[]; rows: string[][] }) {
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
            <tr key={row.join('|')}>
              {row.map((cell, index) => (
                <td
                  key={index}
                  className={`border-b border-line px-4 py-3 last:border-b-0 ${
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

function name(elements: { id: string; name: string }[], id: string): string {
  return elements.find((element) => element.id === id)?.name ?? id
}
