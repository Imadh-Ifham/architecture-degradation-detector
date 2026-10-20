/**
 * Canvas screen.
 *
 * Description:
 *   Every graph the analysis produces, one tab each, drawn the same way so
 *   they can be compared by eye. The architecture as it was found, the same
 *   architecture with the verdicts on it, and which of those verdicts a model
 *   was involved in.
 *
 *   **Positions are shared across the tabs** because the layout is a function
 *   of the graph rather than a simulation: an element sits in the same place
 *   whichever tab is open, so switching between them reads as one picture
 *   gaining information instead of three unrelated drawings.
 *
 *   A phase that publishes its own graph later gets a tab here and a function
 *   in `graphs.ts`. The drawing does not change.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import GraphCanvas, { GraphKey } from '../../components/graph/GraphCanvas'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeading,
  Pill,
  Spinner,
  Tabs,
} from '../../components/ui'
import { readPublishedGraph, readSnapshot } from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { runKey } from '../../workspace/context'
import { useReleases } from '../../workspace/useReleases'
import { useWorkspace } from '../../workspace/useWorkspace'
import ReleasePicker from '../../components/ReleasePicker'
import Handover from './Handover'
import { antiPatternGraph, provenanceGraph, recoveredGraph, validatedGraph } from './graphs'

type View = 'recovered' | 'validated' | 'provenance' | 'antipatterns'

/** What each graph is, in one line, above the drawing it describes. */
const CAPTION: Record<View, string> = {
  recovered:
    'The system as recovery found it. No verdict has been reached about anything here yet.',
  validated:
    'The same system with a verdict on every dependency. This is the artifact the next phase reads.',
  provenance:
    'The same graph again, showing which verdicts a language model was involved in reaching.',
  antipatterns:
    'The same graph with the anti-patterns detection found in this release. Whether they are getting worse is on the drift screen.',
}

export default function CanvasPage() {
  const { repository, repositoryKey, runs, degradation } = useWorkspace()
  const { snapshots, releases, release, selectRelease } = useReleases()
  const run = runs[runKey(repositoryKey, release)] ?? null

  const [view, setView] = useState<View>('recovered')
  const [selected, setSelected] = useState<string | null>(null)

  const snapshotId = useMemo(
    () => snapshots.find((item) => item.release_id === release)?.snapshot_id ?? null,
    [snapshots, release],
  )

  const snapshot = useRequest(
    (options) => readSnapshot(repositoryKey, snapshotId ?? '', options),
    [repositoryKey, snapshotId],
    Boolean(repositoryKey && snapshotId),
  )

  const published = useRequest(
    (options) => readPublishedGraph(repositoryKey, release ?? '', options),
    [repositoryKey, release, run?.run_id],
    Boolean(repository && release),
  )

  // The release as detection saw it, if detection has run over it.
  const detected = useMemo(
    () => degradation?.releases.find((item) => item.release_id === release) ?? null,
    [degradation, release],
  )

  const drawing = useMemo(() => {
    if (view === 'recovered') {
      return snapshot.data ? recoveredGraph(snapshot.data) : null
    }

    if (!published.data) return null
    if (view === 'antipatterns') {
      return detected ? antiPatternGraph(published.data, detected) : null
    }
    return view === 'validated'
      ? validatedGraph(published.data)
      : provenanceGraph(published.data)
  }, [view, snapshot.data, published.data, detected])

  if (!repository || releases.length === 0) {
    return (
      <>
        <PageHeading eyebrow="graphs" title="Canvas" />
        <Card>
          <EmptyState
            title={repository ? 'No recovered release yet' : 'No system selected'}
            body="Every graph here is one release of one system, so a release has to have been recovered first."
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

  const isLoading = view === 'recovered' ? snapshot.isLoading : published.isLoading
  const error = view === 'recovered' ? snapshot.error : published.error

  return (
    <>
      <PageHeading
        eyebrow="graphs"
        title="Canvas"
        description={`Every graph produced for ${release ?? 'this release'}, drawn the same way and in the same positions, so switching between them reads as one picture gaining information.`}
        action={
          <div className="flex flex-wrap items-center gap-5">
            <ReleasePicker releases={releases} value={release} onChange={selectRelease} />
            <Link to="/">
              <Button size="sm" variant="quiet">
                Back to the pipeline
              </Button>
            </Link>
            {published.data ? (
              <Pill tone="ok">
                confidence {published.data.graph.validation_confidence.toFixed(2)}
              </Pill>
            ) : undefined}
          </div>
        }
      />

      <Card
        title={
          <Tabs
            tabs={[
              { id: 'recovered', label: 'Recovered architecture' },
              { id: 'validated', label: 'Validated architecture' },
              { id: 'provenance', label: 'Model involvement' },
              { id: 'antipatterns', label: 'Anti-patterns' },
            ]}
            active={view}
            onChange={setView}
          />
        }
        action={
          <span className="font-mono text-xs text-ink-4">
            {drawing ? `${drawing.nodes.length} elements · ${drawing.edges.length} dependencies` : ''}
          </span>
        }
      >
        {isLoading && <Spinner label="reading the stored graph" />}

        {!isLoading && error && view === 'recovered' && (
          <ErrorState message={error} onRetry={snapshot.reload} />
        )}

        {!isLoading && error && view !== 'recovered' && (
          <EmptyState
            title="This release has not been validated yet"
            body={error}
            action={
              <Link to="/decisions">
                <Button variant="primary">Choose what to validate it against</Button>
              </Link>
            }
          />
        )}

        {!isLoading && !error && view === 'antipatterns' && !detected && (
          <EmptyState
            title="Degradation has not been detected for this release"
            body="Detection reads every validated release at once. Run it from the pipeline or the drift screen, and this tab shows what it found here."
            action={
              <Link to="/drift">
                <Button variant="primary">Open drift</Button>
              </Link>
            }
          />
        )}

        {!isLoading && drawing && (
          <>
            <p className="mb-6 max-w-prose text-sm leading-relaxed text-ink-3">
              {CAPTION[view]}
            </p>
            <GraphCanvas
              nodes={drawing.nodes}
              edges={drawing.edges}
              selected={selected}
              onSelect={setSelected}
              legend={<Legend view={view} />}
            />
          </>
        )}
      </Card>

      {view === 'validated' && published.data && (
        <Handover document={published.data} publishedRef={run?.published_ref} />
      )}
    </>
  )
}

function Legend({ view }: { view: View }) {
  if (view === 'recovered') {
    return (
      <>
        <GraphKey tone="ok">confirmed in source</GraphKey>
        <GraphKey>declared in configuration</GraphKey>
        <GraphKey dashed>cache, database or broker</GraphKey>
      </>
    )
  }

  if (view === 'validated') {
    return (
      <>
        <GraphKey tone="ok">confirmed</GraphKey>
        <GraphKey tone="warn">needs a person</GraphKey>
        <GraphKey tone="bad">contradicted</GraphKey>
        <GraphKey tone="faint" dashed>
          no decision governs it
        </GraphKey>
      </>
    )
  }

  if (view === 'antipatterns') {
    return (
      <>
        <GraphKey tone="bad">in an anti-pattern · edge inside a cycle</GraphKey>
        <GraphKey>not part of one</GraphKey>
      </>
    )
  }

  return (
    <>
      <GraphKey tone="ai">a model was asked · the number is how many calls</GraphKey>
      <GraphKey dashed>decided without a model</GraphKey>
    </>
  )
}
