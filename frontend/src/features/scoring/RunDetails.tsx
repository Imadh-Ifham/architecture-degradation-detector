/**
 * How this ranking was made, from its run manifest.
 *
 * Description:
 *   Enough to make the same run again and to check that nothing was guessed:
 *   the code version, a fingerprint of every input, the weights and where
 *   they came from, how values were scaled, which parts were off and why.
 *   Closed by default; it is evidence, not the reading.
 */

import { Card, ErrorState, Spinner } from '../../components/ui'
import { readRunManifest } from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import { DIMENSIONS, percent } from './dimensions'

export default function RunDetails({ runId }: { runId: string }) {
  const manifest = useRequest((options) => readRunManifest(runId, options), [runId])
  const m = manifest.data

  return (
    <Card title="How this ranking was made">
      <details className="group">
        <summary className="cursor-pointer text-sm text-ink-2 hover:text-ink">
          <span className="group-open:hidden">Show the run record</span>
          <span className="hidden group-open:inline">Hide the run record</span>
          <span className="ml-3 text-xs text-ink-4">
            what a second run needs to give the same ranking
          </span>
        </summary>

        <div className="mt-6">
          {manifest.isLoading && <Spinner label="reading the run record" />}
          {manifest.error && <ErrorState message={manifest.error} onRetry={manifest.reload} />}
          {m && (
            <dl className="grid gap-x-10 gap-y-5 text-sm md:grid-cols-2">
              <Item term="made" value={new Date(m.created_at).toLocaleString('en-GB')} />
              <Item term="code version" value={m.code_commit ?? 'unknown'} mono />
              <Item
                term="weights"
                value={`${m.weights.version} · ${m.weights.provenance} · AHP consistency ${m.weights.ahp_cr.toFixed(3)} (≤ 0.10 is consistent)`}
              />
              <Item
                term="weights used"
                value={DIMENSIONS.filter((d) => m.weights.used[d.key] !== undefined)
                  .map((d) => `${d.label.toLowerCase()} ${percent(m.weights.used[d.key] ?? 0)}`)
                  .join(' · ')}
              />
              <Item
                term="ranking method"
                value={`TOPSIS, ${m.topsis_mode.replace('_', ' ')} · values scaled by ${m.normalization.mode.replace('_', ' ')} (${m.normalization.lower_percentile}th-${m.normalization.upper_percentile}th percentile)`}
              />
              <Item
                term="hotspot"
                value={
                  m.hotspot.active
                    ? `on · git history of ${m.inputs.repo_path ?? 'the repository'}${m.inputs.path_mapping ? ` · paths from ${m.inputs.path_mapping}` : ''}`
                    : `off · ${m.hotspot.inactive_reason ?? 'no history'}`
                }
              />
              <Item
                term="decision violation"
                value={m.adr.active ? 'on' : `off · ${m.adr.inactive_reason ?? 'no decisions linked'}`}
              />
              <Item term="seed" value={String(m.seeds.seed)} mono />
              <Item term="events (fingerprint)" value={short(m.inputs.events_hash)} mono />
              <Item term="architecture (fingerprint)" value={short(m.inputs.graph_hash)} mono />
              <Item
                term="software"
                value={`python ${m.python} · ${Object.entries(m.packages)
                  .map(([name, version]) => `${name} ${version}`)
                  .join(' · ')}`}
              />
              <Item term="report format" value={`SeverityReportV1 ${m.report_schema_version}`} />
            </dl>
          )}
        </div>
      </details>
    </Card>
  )
}

function Item({ term, value, mono }: { term: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-xs text-ink-4">{term}</dt>
      <dd className={`break-all text-ink-2 ${mono ? 'font-mono text-xs' : ''}`}>{value}</dd>
    </div>
  )
}

function short(hash: string): string {
  return hash.length > 23 ? `${hash.slice(0, 23)}…` : hash
}
