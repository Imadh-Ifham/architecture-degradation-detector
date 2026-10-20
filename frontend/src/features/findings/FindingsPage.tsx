/**
 * Findings screen.
 *
 * Description:
 *   Every dependency with a verdict on it, read from the document the run
 *   published — the same bytes the next phase reads, rather than a second
 *   account assembled here.
 *
 *   **The verdict and the confidence are separate columns on purpose.** They
 *   answer different questions: what was concluded, and how much that rests
 *   on. Collapsing them into one coloured score is the most common way this
 *   kind of screen lies.
 *
 *   **How a verdict was produced is on the row.** A verdict a model
 *   produced, one a deterministic rule decided alone, and one nothing
 *   independent checked are three different things, and a screen that renders
 *   them identically makes the absence of a check look like a passed check.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import {
  Button,
  Card,
  EmptyState,

  PageHeading,
  Pill,
  Spinner,
  Stat,
  StatRow,
  Tabs,
} from '../../components/ui'
import {
  listReviews,
  readPublishedGraph,
  type ValidatedEdge,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { runKey } from '../../workspace/context'
import { useReleases } from '../../workspace/useReleases'
import { useWorkspace } from '../../workspace/useWorkspace'
import ReleasePicker from '../../components/ReleasePicker'
import ReviewQueue from './ReviewQueue'

type Bucket = 'all' | 'confirmed' | 'contradicted' | 'needs_review' | 'uncovered'

export default function FindingsPage() {
  const { repository, repositoryKey, runs } = useWorkspace()
  const { releases, release, selectRelease } = useReleases()
  const run = runs[runKey(repositoryKey, release)] ?? null

  const [bucket, setBucket] = useState<Bucket>('all')
  const [selected, setSelected] = useState<string | null>(null)

  const graph = useRequest(
    (options) => readPublishedGraph(repositoryKey, release ?? '', options),
    [repositoryKey, release, run?.run_id],
    Boolean(repository && release),
  )

  const reviews = useRequest(
    (options) => listReviews(repositoryKey, release ?? undefined, options),
    [repositoryKey, release, run?.run_id],
    Boolean(repositoryKey && release),
  )

  const edges = useMemo(() => graph.data?.links ?? [], [graph.data])
  const names = useMemo(
    () => new Map((graph.data?.nodes ?? []).map((node) => [node.id, node.name])),
    [graph.data],
  )

  const counts = useMemo(() => tally(edges), [edges])
  const rows = useMemo(
    () => (bucket === 'all' ? edges : edges.filter((edge) => normalise(edge.bucket) === bucket)),
    [edges, bucket],
  )

  const detail = edges.find((edge) => edge.fact_id === selected) ?? null

  if (!repository) {
    return (
      <>
        <PageHeading eyebrow="judged" title="Findings" />
        <Card>
          <EmptyState
            title="No system selected"
            body="Findings are the result of validating one release, so there has to be one first."
            action={
              <Link to="/repositories">
                <Button variant="primary">Add a repository</Button>
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
        eyebrow="judged"
        title="Findings"
        description={`Every dependency in ${release ?? 'this release'}, with what was concluded about it and the evidence that conclusion rests on.`}
        action={
          <ReleasePicker releases={releases} value={release} onChange={selectRelease} />
        }
      />

      {releases.length === 0 && (
        <Card>
          <EmptyState
            title="No recovered release yet"
            body="Findings are what a validation run produced, so a release has to be recovered and validated first."
            action={
              <Link to="/">
                <Button variant="primary">Run the pipeline</Button>
              </Link>
            }
          />
        </Card>
      )}

      {graph.isLoading && <Spinner label="reading the published result" />}

      {graph.error && !graph.isLoading && (
        <Card>
          <EmptyState
            title="This release has not been validated yet"
            body={graph.error}
            action={
              <Link to="/decisions">
                <Button variant="primary">Choose what to validate it against</Button>
              </Link>
            }
          />
        </Card>
      )}

      {graph.data && (
        <>
          <StatRow>
            <Stat
              label="confirmed"
              value={counts.confirmed}
              note="reality matches the decision"
              tone="ok"
            />
            <Stat
              label="contradicted"
              value={counts.contradicted}
              note="reality diverges from it"
              tone={counts.contradicted > 0 ? 'bad' : 'neutral'}
            />
            <Stat
              label="needs a person"
              value={counts.needs_review}
              note="held back, not failed"
              tone={counts.needs_review > 0 ? 'warn' : 'neutral'}
            />
            <Stat
              label="uncovered"
              value={counts.uncovered}
              note="no decision governs it"
            />
          </StatRow>

          <Card
            title={
              <Tabs
                tabs={[
                  { id: 'all', label: 'All', count: edges.length },
                  { id: 'confirmed', label: 'Confirmed', count: counts.confirmed },
                  { id: 'contradicted', label: 'Contradicted', count: counts.contradicted },
                  { id: 'needs_review', label: 'Needs a person', count: counts.needs_review },
                  { id: 'uncovered', label: 'Uncovered', count: counts.uncovered },
                ]}
                active={bucket}
                onChange={setBucket}
              />
            }
            action={
              <span className="font-mono text-xs text-ink-4">
                confidence {graph.data.graph.validation_confidence.toFixed(2)}
              </span>
            }
          >
            {rows.length === 0 ? (
              <EmptyState
                title="Nothing in this bucket"
                body="That is a result about this repository rather than a gap in the screen: no dependency in this release reached that conclusion."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr>
                      {['dependency', 'verdict', 'confidence', 'judged against', 'produced by'].map(
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
                    {rows.map((edge) => (
                      <tr
                        key={edge.fact_id}
                        onClick={() =>
                          setSelected(selected === edge.fact_id ? null : edge.fact_id)
                        }
                        className={`cursor-pointer transition ${
                          selected === edge.fact_id ? 'bg-raised' : 'hover:bg-raised/50'
                        }`}
                      >
                        <td className="border-b border-line px-4 py-3.5 font-mono text-ink">
                          {names.get(edge.source) ?? edge.source} →{' '}
                          {names.get(edge.target) ?? edge.target}
                        </td>
                        <td className="border-b border-line px-4 py-3.5">
                          <Verdict bucket={edge.bucket} />
                        </td>
                        <td className="border-b border-line px-4 py-3.5 font-mono text-ink-2">
                          {edge.confidence > 0 ? edge.confidence.toFixed(2) : '—'}
                        </td>
                        <td className="border-b border-line px-4 py-3.5 text-ink-3">
                          {edge.source_tier ? `tier ${edge.source_tier}` : 'nothing'}
                        </td>
                        <td className="border-b border-line px-4 py-3.5">
                          <Provenance edge={edge} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {detail && <FindingDetail edge={detail} names={names} />}

          <ReviewQueue
            items={reviews.data ?? []}
            isLoading={reviews.isLoading}
            error={reviews.error}
            onDecided={reviews.reload}
          />
        </>
      )}
    </>
  )
}

function FindingDetail({
  edge,
  names,
}: {
  edge: ValidatedEdge
  names: Map<string, string>
}) {
  return (
    <Card
      title={
        <span className="font-mono text-sm">
          {names.get(edge.source) ?? edge.source} → {names.get(edge.target) ?? edge.target}
        </span>
      }
      action={<Verdict bucket={edge.bucket} />}
    >
      <div className="grid gap-9 lg:grid-cols-3">
        <Detail term="governing decision" value={edge.governing_decision ?? 'none found'} />
        <Detail
          term="evidence"
          value={
            edge.evidence_refs.length > 0
              ? edge.evidence_refs.join(', ')
              : 'nothing was quoted for this'
          }
        />
        <Detail term="relationship" value={edge.relationship.replace(/_/g, ' ')} />
        <Detail
          term="model calls"
          value={
            edge.model_calls === 0
              ? 'none — decided without a model'
              : `${edge.model_calls}`
          }
        />
        <Detail
          term="second opinion"
          value={edge.verification_outcome ?? 'nothing independent checked this'}
        />
        <Detail
          term="rule agreed"
          value={(edge.arbiter_agreement ?? 'not checked').replace(/_/g, ' ')}
        />
      </div>
    </Card>
  )
}

function Detail({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs tracking-wide text-ink-4">{term}</span>
      <span className="font-mono text-sm leading-relaxed break-words text-ink-2">
        {value}
      </span>
    </div>
  )
}

function Verdict({ bucket }: { bucket: string }) {
  const kind = normalise(bucket)
  const tone = {
    confirmed: 'ok',
    contradicted: 'bad',
    needs_review: 'warn',
    uncovered: 'neutral',
    other: 'neutral',
  }[kind] as 'ok' | 'bad' | 'warn' | 'neutral'

  return <Pill tone={tone}>{bucket.replace(/_/g, ' ').toLowerCase()}</Pill>
}

/**
 * How a verdict was reached, which is not the same question as what it was.
 *
 * Purple means a model was involved. A verdict the deterministic rule decided
 * alone is marked as such rather than left to look like any other, because
 * that difference is the one a reader most needs and the one easiest to lose.
 */
function Provenance({ edge }: { edge: ValidatedEdge }) {
  if (edge.model_calls === 0) {
    return <Pill>no model</Pill>
  }

  return <Pill tone="ai">{edge.produced_by.replace(/_/g, ' ') || 'model'}</Pill>
}

function normalise(bucket: string) {
  const value = bucket.toLowerCase()

  if (value.includes('confirm')) return 'confirmed'
  if (value.includes('contradict')) return 'contradicted'
  if (value.includes('review')) return 'needs_review'
  if (value.includes('uncovered')) return 'uncovered'
  return 'other'
}

function tally(edges: ValidatedEdge[]) {
  return edges.reduce(
    (totals, edge) => {
      const kind = normalise(edge.bucket)
      if (kind !== 'other') totals[kind] += 1
      return totals
    },
    { confirmed: 0, contradicted: 0, needs_review: 0, uncovered: 0 },
  )
}
