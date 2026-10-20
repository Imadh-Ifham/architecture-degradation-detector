/**
 * One dependency, and why it is in the graph.
 *
 * Description:
 *   The edge exists because a stage said so. This shows which stages, on what
 *   evidence, in what file - and, separately, what the evidence establishes
 *   about *how* the two components communicate.
 *
 *   **A relationship type is not a protocol.** `service_dependency` says one
 *   element reaches another; `http` says how. They are reported in different
 *   places because collapsing them is how a dependency gets read as a call.
 *
 *   **Unknown is a result.** Where nothing declares a protocol and no source
 *   finding observed one, this says so. A port number is shown as a port
 *   number, never promoted to `http:`.
 */

import { Pill } from '../../components/ui'
import type { RelationshipDetails, DeclaredEvidence, SourceEvidenceEntry } from '../../lib/api'
import { Fact, Section } from './ComponentDetail'

const SOURCE_LABEL = {
  declared: 'declared in a file',
  source: 'observed in source code',
  unknown: 'no protocol established',
} as const

export default function RelationshipDetail({
  relationship,
  names,
}: {
  relationship: RelationshipDetails
  names: Map<string, string>
}) {
  const declared = relationship.declared_evidence
  const observed = relationship.source_evidence

  return (
    <div className="flex flex-col gap-9">
      <div className="grid gap-7 sm:grid-cols-2 lg:grid-cols-4">
        <Fact label="from" value={names.get(relationship.source_id) ?? relationship.source_id} />
        <Fact label="to" value={names.get(relationship.target_id) ?? relationship.target_id} />
        <Fact label="relationship" value={relationship.kind.replace(/_/g, ' ')} />
        <Fact
          label="confirmed in source"
          value={relationship.confirmed_by_source ? 'yes' : 'declared only'}
        />
      </div>

      <Section title="Communication">
        <div className="flex flex-wrap items-center gap-3">
          {relationship.protocols.length > 0 ? (
            relationship.protocols.map((protocol) => (
              <Pill key={protocol} tone="ai">
                {protocol}
              </Pill>
            ))
          ) : (
            <Pill>unknown</Pill>
          )}
          <span className="text-xs text-ink-3">
            {SOURCE_LABEL[relationship.protocol_source]}
          </span>
        </div>

        <div className="grid gap-7 sm:grid-cols-2 lg:grid-cols-4">
          <Fact
            label="endpoints"
            value={
              relationship.endpoints.length > 0
                ? relationship.endpoints.join(', ')
                : 'none recorded'
            }
            mono
          />
          <Fact
            label="ports"
            value={
              relationship.ports.length > 0 ? relationship.ports.join(', ') : 'none recorded'
            }
            mono
            note="a port does not establish what runs on it"
          />
          <Fact
            label="resolution"
            value={relationship.resolution?.method?.replace(/_/g, ' ') ?? 'not resolved'}
            mono
          />
          <Fact
            label="confidence"
            value={relationship.resolution?.confidence ?? 'not recorded'}
            note={
              relationship.resolution?.target_class
                ? `target: ${relationship.resolution.target_class}`
                : undefined
            }
          />
        </div>

        {relationship.protocol_source === 'unknown' && (
          <p className="max-w-prose text-xs leading-relaxed text-ink-4">
            Nothing in this release states how these two communicate. The edge
            records a dependency, which is a weaker claim than a call, and no
            protocol is shown rather than one inferred from the port.
          </p>
        )}
      </Section>

      <Section title="Declared evidence">
        {declared.length > 0 ? (
          <ul className="flex flex-col gap-3">
            {declared.map((item, index) => (
              <li key={`${item.path}-${item.line}-${index}`}>
                <DeclaredLine evidence={item} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-3">
            No manifest or configuration file contributed to this edge.
          </p>
        )}
      </Section>

      <Section title="Source evidence">
        {observed.length > 0 ? (
          <ul className="flex flex-col gap-3">
            {observed.map((item, index) => (
              <li key={`${item.path}-${item.line}-${index}`}>
                <SourceLine evidence={item} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="max-w-prose text-sm text-ink-3">
            No source-level call was observed. The edge rests on configuration
            alone, which is what the graph draws it as.
          </p>
        )}
      </Section>

      {relationship.source_findings.length > 0 && (
        <Section title="Findings behind it">
          <ul className="flex flex-col gap-2">
            {relationship.source_findings.map((finding) => (
              <li
                key={finding.id ?? `${finding.type}-${finding.target_reference}`}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-ink-2"
              >
                <span className="text-ink">{finding.type?.replace(/_/g, ' ')}</span>
                {finding.language && <span>{finding.language}</span>}
                {finding.strength && <Pill>{finding.strength.replace(/_/g, ' ')}</Pill>}
                {finding.target_reference && (
                  <span className="text-ink-4">{finding.target_reference}</span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Stage evidence">
        <ul className="flex flex-col gap-2">
          {relationship.snapshot_evidence.map((entry) => (
            <li
              key={`${entry.stage}-${entry.type}`}
              className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-ink-2"
            >
              <span className="text-ink">{entry.stage.replace(/_/g, ' ')}</span>
              <span>{entry.type.replace(/_/g, ' ')}</span>
              <Pill tone={entry.declared ? 'ok' : 'neutral'}>
                {entry.declared ? 'declared' : 'inferred'}
              </Pill>
              <span className="text-ink-4">{entry.count}</span>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  )
}

function DeclaredLine({ evidence }: { evidence: DeclaredEvidence }) {
  const where = evidence.path
    ? `${evidence.path}${evidence.line ? `:${evidence.line}` : ''}`
    : 'no location recorded'

  return (
    <div className="flex flex-col gap-1.5 border-l-2 border-ok/50 pl-4">
      <code className="font-mono text-xs break-all text-ink">{where}</code>
      <span className="text-sm leading-relaxed text-ink-2">{evidence.detail}</span>
      <span className="flex flex-wrap items-center gap-3 font-mono text-[11px] text-ink-4">
        {evidence.type && <span>{evidence.type.replace(/_/g, ' ')}</span>}
        {evidence.key && <span>key {evidence.key}</span>}
        {evidence.endpoint && <span>{evidence.endpoint}</span>}
        {evidence.declared ? (
          <Pill tone="ok">declared</Pill>
        ) : (
          <Pill>inferred</Pill>
        )}
      </span>
    </div>
  )
}

function SourceLine({ evidence }: { evidence: SourceEvidenceEntry }) {
  return (
    <div className="flex flex-col gap-1.5 border-l-2 border-ai/50 pl-4">
      <code className="font-mono text-xs break-all text-ink">
        {evidence.path}:{evidence.line}
      </code>
      <span className="text-sm leading-relaxed text-ink-2">{evidence.detail}</span>
      <span className="flex flex-wrap items-center gap-3 font-mono text-[11px] text-ink-4">
        {evidence.evidence_type && (
          <span>{evidence.evidence_type.replace(/_/g, ' ')}</span>
        )}
        {evidence.symbol && <span className="text-ink-3">{evidence.symbol}</span>}
        {evidence.language && <span>{evidence.language}</span>}
        <Pill tone="ai">{evidence.strength.replace(/_/g, ' ')}</Pill>
      </span>
    </div>
  )
}
