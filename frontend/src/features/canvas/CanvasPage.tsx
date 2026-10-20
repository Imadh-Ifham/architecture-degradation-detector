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
import {
  readPublishedGraph,
  readSnapshot,
  readTranscript,
  type ValidatedEdge,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { runKey } from '../../workspace/context'
import { useReleases } from '../../workspace/useReleases'
import { useWorkspace } from '../../workspace/useWorkspace'
import ReleasePicker from '../../components/ReleasePicker'
import FindingDetail from './FindingDetail'
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
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null)

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

  // The models' own sentences about each dependency. Read here rather than
  // inside the panel so opening one finding after another costs nothing, and
  // so a release with no transcript is a state the panel is handed rather
  // than a request it has to make and fail.
  const transcript = useRequest(
    (options) => readTranscript(repositoryKey, release ?? '', options),
    [repositoryKey, release, run?.run_id],
    Boolean(repository && release),
  )

  // The release as detection saw it, if detection has run over it.
  const detected = useMemo(
    () => degradation?.releases.find((item) => item.release_id === release) ?? null,
    [degradation, release],
  )

  const openEdge = useMemo(
    () =>
      view === 'validated' && published.data
        ? (published.data.links.find((edge) => edge.fact_id === selectedEdge) ?? null)
        : null,
    [view, published.data, selectedEdge],
  )

  const contradicted = useMemo(
    () =>
      published.data?.links.filter((edge) =>
        edge.bucket.toLowerCase().includes('contradict'),
      ) ?? [],
    [published.data],
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
            onChange={(next) => {
              setView(next)
              // An edge id identifies a fact, and only the validated graph
              // draws facts. Carrying a selection across a tab would leave a
              // panel open about a line the picture no longer contains.
              setSelectedEdge(null)
            }}
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
            {view === 'validated' && contradicted.length > 0 && (
              <Contradictions
                edges={contradicted}
                names={new Map(
                  (published.data?.nodes ?? []).map((node) => [node.id, node.name]),
                )}
                selected={selectedEdge}
                onSelect={setSelectedEdge}
              />
            )}

            <GraphCanvas
              nodes={drawing.nodes}
              edges={drawing.edges}
              selected={selected}
              onSelect={setSelected}
              selectedEdge={view === 'validated' ? selectedEdge : null}
              onSelectEdge={view === 'validated' ? setSelectedEdge : undefined}
              legend={<Legend view={view} />}
              footer={
                view === 'validated' && published.data ? (
                  openEdge ? (
                    <FindingDetail
                      edge={openEdge}
                      document={published.data}
                      transcript={transcript.data}
                      onClose={() => setSelectedEdge(null)}
                    />
                  ) : (
                    <p className="text-sm leading-relaxed text-ink-4">
                      Click a dependency to see what was concluded about it, what
                      it was judged against, and what each model wrote.
                    </p>
                  )
                ) : undefined
              }
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

/**
 * The contradictions, as a row of buttons above the drawing.
 *
 * A red line says where one is; finding it in a graph of seventeen
 * dependencies still means hunting for it. These are the findings the whole
 * component exists to produce, so they get named rather than left to be
 * discovered — and clicking one opens it below the picture.
 */
function Contradictions({
  edges,
  names,
  selected,
  onSelect,
}: {
  edges: ValidatedEdge[]
  names: Map<string, string>
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  return (
    <div className="mb-6 flex flex-wrap items-center gap-3">
      <span className="text-xs tracking-wide text-ink-4">
        {edges.length} contradicted —
      </span>
      {edges.map((edge) => {
        const isOpen = edge.fact_id === selected

        return (
          <button
            key={edge.fact_id}
            onClick={() => onSelect(isOpen ? null : edge.fact_id)}
            className={`rounded-full border px-3 py-1 font-mono text-xs transition ${
              isOpen
                ? 'border-bad bg-bad-wash text-bad'
                : 'border-bad/50 text-bad hover:border-bad'
            }`}
          >
            {names.get(edge.source) ?? edge.source} → {names.get(edge.target) ?? edge.target}
          </button>
        )
      })}
    </div>
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
