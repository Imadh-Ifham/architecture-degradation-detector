/**
 * How the architecture was recovered.
 *
 * Description:
 *   The pipeline screen says recovery ran. This says how: one block per stage
 *   in the order the backend executed them, with its purpose, what it read,
 *   what it counted, how long it took, which artifact it wrote, and - the part
 *   that matters most - whether it ran at all.
 *
 *   **A skipped stage must never look like a stage that found nothing.** The
 *   record distinguishes completed, skipped and failed, and carries the reason
 *   a stage did not run. A release with no record at all is reported as
 *   exactly that, rather than as six stages that happened to count nothing.
 *
 *   The layout follows the validation screen deliberately: same heading, same
 *   summary row, same one-block-per-stage rhythm, so the two read as two
 *   accounts of the same pipeline rather than two applications.
 */

import { useState } from 'react'
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
} from '../../components/ui'
import ReleasePicker from '../../components/ReleasePicker'
import {
  readRecoveryReport,
  type ArtifactAvailability,
  type RecoveredArchitectureSummary,
  type RecoveryReport,
  type RecoveryStageDescription,
  type RecoveryStageRecord,
  type RecoverySummary,
  type SnapshotUnresolved,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { useReleases } from '../../workspace/useReleases'
import { useWorkspace } from '../../workspace/useWorkspace'

export default function RecoveryPage() {
  const { repository, repositoryKey } = useWorkspace()
  const { snapshots, releases, release, selectRelease } = useReleases()

  const snapshotId =
    snapshots.find((item) => item.release_id === release)?.snapshot_id ?? null

  const report = useRequest(
    (options) => readRecoveryReport(repositoryKey, snapshotId ?? '', options),
    [repositoryKey, snapshotId],
    Boolean(repositoryKey && snapshotId),
  )

  if (!repository || releases.length === 0) {
    return (
      <>
        <PageHeading eyebrow="recovered" title="Recovery" />
        <Card>
          <EmptyState
            title={repository ? 'No recovered release yet' : 'No system selected'}
            body="Recovery stores one architecture per release. Run the pipeline for a release and this screen explains what each stage did."
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
        title="Recovery"
        description={`How ${release} was recovered: what each stage read, what it found, which artifact it wrote, and where it stopped.`}
        action={
          <div className="flex flex-wrap items-center gap-5">
            <ReleasePicker releases={releases} value={release} onChange={selectRelease} />
            <Link to="/">
              <Button variant="primary">Open the pipeline</Button>
            </Link>
          </div>
        }
      />

      {report.isLoading && <Spinner label="reading the recovery record" />}

      {report.error && !report.isLoading && (
        <Card>
          <EmptyState
            title="No recovery recorded for this release"
            body={report.error}
            action={
              <Link to="/">
                <Button variant="primary">Run recovery</Button>
              </Link>
            }
          />
        </Card>
      )}

      {report.data && (
        <>
          <Outcome report={report.data} />

          {report.data.recorded ? (
            <Stages report={report.data} />
          ) : (
            <Card title="What each stage did">
              <EmptyState
                title="No run record for this release"
                body={
                  'This release has an architecture, but no record of the run that produced ' +
                  'it: it was analysed before records were kept, or its clone has been ' +
                  'removed. Re-running recovery for it will record the stages; until then ' +
                  'their statuses are unknown rather than successful.'
                }
                action={
                  <Link to="/repositories">
                    <Button>Open repositories</Button>
                  </Link>
                }
              />
            </Card>
          )}

          {report.data.recorded && <Flow report={report.data} />}

          <Architecture report={report.data} />
          <Elsewhere />
        </>
      )}
    </>
  )
}

/** The result, before any of the machinery that produced it. */
function Outcome({ report }: { report: RecoveryReport }) {
  const summary: RecoverySummary = report.summary

  return (
    <StatRow>
      <Stat
        label="stages"
        value={
          summary.stage_count === null
            ? 'not recorded'
            : `${summary.completed} / ${summary.stage_count}`
        }
        note={
          summary.stage_count === null
            ? 'no run record for this release'
            : `${summary.completed} completed, ${summary.skipped} skipped, ${summary.failed} failed`
        }
        tone={
          summary.failed
            ? 'bad'
            : summary.skipped
              ? 'warn'
              : summary.stage_count === null
                ? 'neutral'
                : 'ok'
        }
      />
      <Stat
        label="duration"
        value={
          summary.duration_ms === null
            ? '—'
            : `${(summary.duration_ms / 1000).toFixed(1)}s`
        }
        note="wall-clock across every stage"
      />
      <Stat
        label="components"
        value={summary.element_count}
        note="elements the recovered architecture contains"
      />
      <Stat
        label="dependencies"
        value={summary.relationship_count}
        note={
          summary.warning_count
            ? `${summary.warning_count} stage warning${summary.warning_count === 1 ? '' : 's'}`
            : `${summary.artifact_count} artifacts on disk`
        }
        tone={summary.warning_count ? 'warn' : 'neutral'}
      />
    </StatRow>
  )
}

/**
 * Every stage, with what it is for, what it counted and why it did not run.
 *
 * One block per stage rather than a table, because the interesting part is
 * never the status: it is the counts, the artifact, and a skipped stage's
 * reason. Those read as sentences at this size and as noise in a grid.
 */
function Stages({ report }: { report: RecoveryReport }) {
  const described = new Map(report.pipeline.map((stage) => [stage.name, stage]))
  const run = report.run

  return (
    <Card
      title="What each stage did"
      action={
        <span className="font-mono text-xs text-ink-4">
          {run ? `${timestamp(run.started_at)} · ${run.status}` : ''}
        </span>
      }
    >
      <ol className="flex flex-col gap-px bg-line">
        {(run?.stages ?? []).map((record) => (
          <Stage
            key={record.name}
            record={record}
            describedBy={described.get(record.name)}
            artifacts={report.artifacts}
          />
        ))}
      </ol>
    </Card>
  )
}

function Stage({
  record,
  describedBy,
  artifacts,
}: {
  record: RecoveryStageRecord
  describedBy?: RecoveryStageDescription
  artifacts: ArtifactAvailability[]
}) {
  const counts = Object.entries(record.counts)

  return (
    <li className="flex flex-col gap-5 bg-panel px-1 py-7 first:pt-1 last:pb-1">
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div className="flex min-w-0 items-start gap-4">
          <span className="mt-0.5 font-mono text-xs text-ink-4">
            {String(record.order).padStart(2, '0')}
          </span>
          <div className="flex min-w-0 flex-col gap-1.5">
            <span className="text-sm font-medium text-ink">
              {record.name.replace(/_/g, ' ')}
            </span>
            {describedBy && (
              <span className="max-w-prose text-xs leading-relaxed text-ink-3">
                {describedBy.role}
              </span>
            )}
            {describedBy && (
              <span className="font-mono text-[11px] text-ink-4">
                reads {describedBy.reads}
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2.5">
          <StageStatus status={record.status} />
          <span className="font-mono text-[11px] text-ink-4">
            {record.status === 'skipped' ? '—' : `${record.duration_ms} ms`}
          </span>
        </div>
      </div>

      {counts.length > 0 && (
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-3 lg:grid-cols-4">
          {counts.map(([key, value]) => (
            <div key={key} className="flex flex-col gap-1 bg-panel px-4 py-3">
              <dt className="text-[11px] leading-tight text-ink-4">
                {key.replace(/_/g, ' ')}
              </dt>
              <dd className="font-mono text-lg leading-none text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {counts.length === 0 && record.status === 'completed' && (
        <p className="font-mono text-xs text-ink-4">
          ran and counted nothing, which is a result rather than a gap
        </p>
      )}

      {record.note && (
        <p
          className={`max-w-prose border-l-2 pl-4 text-xs leading-relaxed ${
            record.status === 'failed'
              ? 'border-bad/60 text-bad'
              : 'border-warn/60 text-warn'
          }`}
        >
          {record.status === 'skipped' ? 'Not run: ' : ''}
          {record.note}
        </p>
      )}

      {record.warnings.length > 0 && <Warnings warnings={record.warnings} />}

      {describedBy?.artifact && (
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2 border-t border-line pt-4">
          <code className="font-mono text-xs text-ink">{describedBy.artifact}</code>
          {record.artifact_present ? (
            <Pill tone="ok">written</Pill>
          ) : (
            <Pill tone={record.status === 'completed' ? 'warn' : 'neutral'}>
              {record.status === 'completed' ? 'missing on disk' : 'not written'}
            </Pill>
          )}
          {describedBy.artifact_role && (
            <span className="max-w-prose text-xs leading-relaxed text-ink-3">
              {describedBy.artifact_role}
            </span>
          )}
          {!record.artifact_present && artifacts.length > 0 && (
            <span className="font-mono text-[11px] text-ink-4">
              the clone may have been removed since
            </span>
          )}
        </div>
      )}
    </li>
  )
}

/** Warnings are about the repository, not about the stage, so they are listed. */
function Warnings({ warnings }: { warnings: string[] }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? warnings : warnings.slice(0, 3)

  return (
    <div className="flex flex-col gap-2">
      <span className="font-mono text-[11px] tracking-wide text-ink-4 uppercase">
        warnings
      </span>
      <ul className="flex flex-col gap-2">
        {shown.map((warning) => (
          <li
            key={warning}
            className="max-w-prose border-l-2 border-line-strong pl-4 text-xs leading-relaxed text-ink-3"
          >
            {warning}
          </li>
        ))}
      </ul>
      {warnings.length > 3 && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="self-start font-mono text-xs text-ink-2 underline-offset-4 hover:text-ink hover:underline"
        >
          {expanded ? 'show fewer' : `show all ${warnings.length}`}
        </button>
      )}
    </div>
  )
}

/**
 * The order, in one glance.
 *
 * The stage blocks above are the detailed account; this is the sequence they
 * add up to, with each stage's primary output - so a reader can see where a
 * pipeline stopped without reading six blocks.
 */
function Flow({ report }: { report: RecoveryReport }) {
  const records = new Map((report.run?.stages ?? []).map((stage) => [stage.name, stage]))

  return (
    <Card
      title="The order it ran in"
      action={
        <span className="font-mono text-xs text-ink-4">
          each stage reads what the one before it wrote
        </span>
      }
    >
      <ol className="grid gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
        {report.pipeline.map((stage) => {
          const record = records.get(stage.name)

          return (
            <li
              key={stage.name}
              className="flex flex-col gap-2 border-l-2 border-line-strong bg-panel px-5 py-4"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono text-[11px] text-ink-4">
                  {String(stage.order).padStart(2, '0')}
                </span>
                {record ? <StageStatus status={record.status} /> : <Pill>unrecorded</Pill>}
              </div>
              <span className="text-sm text-ink">{stage.name.replace(/_/g, ' ')}</span>
              <span className="font-mono text-[11px] text-ink-4">
                → {stage.artifact ?? 'no artifact'}
              </span>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

/** What recovery produced, and where to look at it. */
function Architecture({ report }: { report: RecoveryReport }) {
  const architecture: RecoveredArchitectureSummary = report.architecture
  const absent = report.artifacts.filter((item) => !item.present)

  return (
    <Card title="What recovery produced" action={<Pill>{report.snapshot_status}</Pill>}>
      <div className="flex flex-col gap-8">
        <StatRow>
          <Stat
            label="components"
            value={architecture.element_count}
            note="identified by recovery"
          />
          <Stat
            label="dependencies"
            value={architecture.relationship_count}
            note={`${architecture.confirmed_by_source} confirmed in source`}
          />
          <Stat
            label="unresolved"
            value={architecture.unresolved_dependencies}
            note="references naming nothing discovered"
            tone={architecture.unresolved_dependencies > 0 ? 'warn' : 'neutral'}
          />
          <Stat
            label="ambiguous"
            value={architecture.ambiguous_dependencies}
            note="a reference with more than one candidate"
            tone={architecture.ambiguous_dependencies > 0 ? 'warn' : 'neutral'}
          />
        </StatRow>

        <div className="grid gap-9 lg:grid-cols-3">
          <Breakdown
            title="component types"
            values={architecture.by_component_type}
            fallback="none recorded"
          />
          <Breakdown
            title="languages"
            values={architecture.by_language}
            fallback="none detected"
          />
          <Breakdown
            title="relationship types"
            values={architecture.by_relationship_type}
            fallback="none resolved"
          />
        </div>

        {architecture.unresolved_references.length > 0 && (
          <Unresolved items={architecture.unresolved_references} />
        )}

        {architecture.diagnostics.length > 0 && (
          <div className="flex flex-col gap-2">
            <span className="font-mono text-[11px] tracking-wide text-ink-4 uppercase">
              diagnostics
            </span>
            <ul className="flex flex-col gap-1.5">
              {architecture.diagnostics.slice(0, 5).map((item) => (
                <li key={item} className="font-mono text-xs leading-relaxed text-ink-3">
                  {item}
                </li>
              ))}
            </ul>
            {architecture.diagnostics.length > 5 && (
              <span className="font-mono text-xs text-ink-4">
                and {architecture.diagnostics.length - 5} more in the artifact
              </span>
            )}
          </div>
        )}

        {absent.length > 0 && (
          <p className="max-w-prose border-l-2 border-warn/60 pl-4 text-xs leading-relaxed text-warn">
            {absent.map((item) => item.file).join(', ')} could not be read for this
            release, so part of this summary is unavailable. The clone is removed with
            the repository; re-run recovery to rebuild the artifacts.
          </p>
        )}
      </div>
    </Card>
  )
}

function Breakdown({
  title,
  values,
  fallback,
}: {
  title: string
  values: Record<string, number>
  fallback: string
}) {
  const entries = Object.entries(values)

  return (
    <div className="flex flex-col gap-3">
      <span className="text-xs tracking-wide text-ink-4">{title}</span>
      {entries.length === 0 ? (
        <span className="font-mono text-xs text-ink-4">{fallback}</span>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {entries.map(([key, count]) => (
            <li key={key} className="flex items-baseline justify-between gap-4">
              <span className="font-mono text-xs text-ink-2">
                {key.replace(/_/g, ' ')}
              </span>
              <span className="font-mono text-xs text-ink">{count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Unresolved({ items }: { items: SnapshotUnresolved[] }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? items : items.slice(0, 5)

  return (
    <div className="flex flex-col gap-3">
      <span className="font-mono text-[11px] tracking-wide text-ink-4 uppercase">
        could not be resolved
      </span>
      <ul className="flex flex-col gap-2">
        {shown.map((item) => (
          <li
            key={`${item.stage}-${item.reference}`}
            className="flex flex-col gap-1 border-l-2 border-warn/50 pl-4"
          >
            <span className="flex flex-wrap items-center gap-3">
              <code className="font-mono text-xs text-ink">{item.reference}</code>
              <Pill>{item.stage.replace(/_/g, ' ')}</Pill>
            </span>
            {item.reason && (
              <span className="text-xs leading-relaxed text-ink-3">{item.reason}</span>
            )}
          </li>
        ))}
      </ul>
      {items.length > 5 && (
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

function Elsewhere() {
  return (
    <Card title="The rest of this result">
      <div className="grid gap-5 sm:grid-cols-2">
        <Link
          to="/"
          className="flex flex-col gap-2 rounded-control border border-line px-6 py-5 transition hover:border-line-strong"
        >
          <span className="text-sm font-medium text-ink">Pipeline →</span>
          <span className="text-xs leading-relaxed text-ink-3">
            The four phases, and what the last run did to each snapshot.
          </span>
        </Link>
        <Link
          to="/architecture"
          className="flex flex-col gap-2 rounded-control border border-line px-6 py-5 transition hover:border-line-strong"
        >
          <span className="text-sm font-medium text-ink">Architecture →</span>
          <span className="text-xs leading-relaxed text-ink-3">
            The system as recovery found it, as a diagram and as a table.
          </span>
        </Link>
        <Link
          to="/canvas"
          className="flex flex-col gap-2 rounded-control border border-line px-6 py-5 transition hover:border-line-strong"
        >
          <span className="text-sm font-medium text-ink">Canvas →</span>
          <span className="text-xs leading-relaxed text-ink-3">
            The recovered graph drawn, beside the version validation judged.
          </span>
        </Link>
        <Link
          to="/validation"
          className="flex flex-col gap-2 rounded-control border border-line px-6 py-5 transition hover:border-line-strong"
        >
          <span className="text-sm font-medium text-ink">Validation →</span>
          <span className="text-xs leading-relaxed text-ink-3">
            What was concluded about this architecture, and what checked it.
          </span>
        </Link>
      </div>
    </Card>
  )
}

function StageStatus({ status }: { status: RecoveryStageRecord['status'] }) {
  const tone = {
    completed: 'ok',
    skipped: 'warn',
    failed: 'bad',
  }[status] as 'ok' | 'warn' | 'bad'

  return <Pill tone={tone}>{status}</Pill>
}

function timestamp(value: string): string {
  const parsed = new Date(value)

  return Number.isNaN(parsed.getTime())
    ? value
    : `${parsed.toISOString().slice(0, 16).replace('T', ' ')}Z`
}
