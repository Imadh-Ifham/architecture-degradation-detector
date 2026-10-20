/**
 * What recovery found for one snapshot.
 *
 * Description:
 *   Recovery runs six stages, and each reports what it saw. The clone
 *   succeeding and the analysis succeeding are different events: a stage can
 *   fail with the clone intact, and the response says so per stage rather
 *   than failing the request.
 *
 *   So every stage is shown either way - its counts, or the reason it could
 *   not run. A stage that quietly reported nothing would be indistinguishable
 *   from a repository that genuinely has nothing in it, and the last stage is
 *   the one that decides whether validation has anything to read.
 */

import { Card, Pill } from '../../components/ui'
import type { RecoveryResult, StageSummary } from '../../lib/api'

/** The stages of recovery, in the order the backend runs them. */
const STAGES: { key: keyof RecoveryResult; label: string; headline: string[] }[] = [
  {
    key: 'inventory',
    label: 'Inventory',
    headline: ['file_count', 'component_count', 'relationship_count'],
  },
  {
    key: 'manifest_analysis',
    label: 'Manifests',
    headline: ['analyzed_count', 'resource_count', 'endpoint_count'],
  },
  {
    key: 'component_discovery',
    label: 'Components',
    headline: ['component_count', 'artifact_count', 'ambiguous_count'],
  },
  {
    key: 'dependency_resolution',
    label: 'Dependencies',
    headline: ['resolved_relationship_count', 'evidence_count', 'unresolved_count'],
  },
  {
    key: 'source_code_analysis',
    label: 'Source',
    headline: ['finding_count', 'corroborated_count', 'unresolved_count'],
  },
  {
    key: 'graph_construction',
    label: 'Graph',
    headline: ['element_count', 'relationship_count', 'unresolved_count'],
  },
]

export default function RecoveryReport({ recovery }: { recovery: RecoveryResult }) {
  return (
    <Card
      title="What recovery found"
      action={
        <span className="font-mono text-xs text-ink-4">
          {recovery.release_tag ?? recovery.branch} · {recovery.commit.slice(0, 7)}
        </span>
      }
    >
      <ol className="grid gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
        {STAGES.map((stage) => (
          <Stage
            key={stage.label}
            label={stage.label}
            headline={stage.headline}
            summary={recovery[stage.key] as StageSummary | null | undefined}
            error={
              recovery[`${String(stage.key)}_error` as keyof RecoveryResult] as
                | string
                | null
                | undefined
            }
          />
        ))}
      </ol>
    </Card>
  )
}

function Stage({
  label,
  headline,
  summary,
  error,
}: {
  label: string
  headline: string[]
  summary: StageSummary | null | undefined
  error: string | null | undefined
}) {
  return (
    <li className="flex flex-col gap-3 bg-panel px-6 py-5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium">{label}</span>
        {error ? <Pill tone="bad">failed</Pill> : summary ? null : <Pill>skipped</Pill>}
      </div>

      {error && <p className="text-xs leading-relaxed text-bad">{error}</p>}

      {summary && (
        <div className="flex flex-col gap-1.5">
          {headline.map((key) => {
            const value = summary[key]
            if (typeof value !== 'number') return null

            return (
              <span key={key} className="font-mono text-xs text-ink-2">
                <span className="text-ink">{value}</span>{' '}
                {key.replace(/_count$/, '').replace(/_/g, ' ')}
              </span>
            )
          })}
        </div>
      )}

      {!summary && !error && (
        <span className="font-mono text-xs text-ink-4">nothing reported</span>
      )}
    </li>
  )
}
