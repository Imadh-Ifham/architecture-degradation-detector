/**
 * The rules behind the count.
 *
 * Description:
 *   A number of decisions is an assertion until somebody can see them. That
 *   matters more here than anywhere else in the application, because most of
 *   these rules were **not written by a person** — they were reconstructed
 *   from configuration, and the only thing that makes a reconstructed rule
 *   trustworthy is the file and the line it was read from.
 *
 *   **So every row names its source.** Not "76 decisions" but this rule, this
 *   constraint, this path, these lines. A reader who doubts one can open it.
 *
 *   **Written and reconstructed rules are not mixed silently.** They are
 *   grouped, because a decision somebody ratified and a rule inferred from a
 *   policy file are different kinds of evidence, and the strength of the kind
 *   is what caps the conclusion later. A flat list of both would be the one
 *   place in the application that hides a tier.
 *
 *   It is read-only and asks for nothing: the same sources the picker reads,
 *   read the same way, so the list and the count cannot disagree.
 */

import { useState } from 'react'
import { Button, Card, ErrorState, Pill, Spinner } from '../../components/ui'
import {
  readDecisionRecords,
  type DecisionMode,
  type DecisionRecord,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'

/** What each constraint requires, in a person's words rather than the enum's. */
const CONSTRAINT: Record<string, string> = {
  may_call: 'may call',
  must_not_call: 'must not call',
  must_call_via: 'must reach it through',
  declared_rpc: 'declares the operation',
}

/** How strong the kind of evidence is, shortest first. */
const TIER: Record<string, { label: string; tone: 'ok' | 'warn' | 'neutral' }> = {
  tier_1_decision_record: { label: 'written decision', tone: 'ok' },
  tier_2_executable_config: { label: 'enforced configuration', tone: 'ok' },
  tier_3_documentation: { label: 'documentation', tone: 'warn' },
  tier_4_history: { label: 'commit history', tone: 'warn' },
  tier_5_convention: { label: 'convention', tone: 'warn' },
}

export default function RuleList({
  repositoryId,
  release,
  mode,
}: {
  repositoryId: string
  release: string
  mode: DecisionMode
}) {
  const [isOpen, setIsOpen] = useState(false)

  const rules = useRequest(
    (options) => readDecisionRecords(repositoryId, release, mode, options),
    [repositoryId, release, mode],
    isOpen,
  )

  const records = rules.data?.records ?? []
  const declared = records.filter((rule) => rule.extraction_method === 'declared')
  const reconstructed = records.filter((rule) => rule.extraction_method !== 'declared')

  return (
    <Card
      title="What these rules actually are"
      action={
        <Button onClick={() => setIsOpen(!isOpen)}>
          {isOpen ? 'Hide' : 'Show every rule'}
        </Button>
      }
    >
      <div className="flex flex-col gap-6">
        <p className="max-w-prose text-sm leading-relaxed text-ink-3">
          Most of these were not written by anybody — they were read out of
          configuration the system already enforces. Every one names the file
          and the lines it came from, so any of them can be checked by opening
          it.
        </p>

        {isOpen && (
          <>
            {rules.isLoading && <Spinner label="reading the rules" />}
            {rules.error && (
              <ErrorState message={rules.error} onRetry={rules.reload} />
            )}

            {rules.data && records.length === 0 && (
              <p className="text-sm text-ink-4">
                This mode supplies no rules, so there is nothing to list.
              </p>
            )}

            {declared.length > 0 && (
              <Group
                heading="Written down by a person"
                body="Decision records found in a repository. The strongest kind of evidence, because somebody committed to it deliberately."
                rules={declared}
              />
            )}

            {reconstructed.length > 0 && (
              <Group
                heading="Reconstructed from configuration"
                body="Nobody wrote these as decisions. They were read out of files that are enforced at runtime, which is why each one carries a line you can open."
                rules={reconstructed}
              />
            )}
          </>
        )}
      </div>
    </Card>
  )
}

function Group({
  heading,
  body,
  rules,
}: {
  heading: string
  body: string
  rules: DecisionRecord[]
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-baseline gap-3">
          <span className="text-sm font-medium text-ink">{heading}</span>
          <span className="font-mono text-xs text-ink-4">{rules.length}</span>
        </div>
        <p className="max-w-prose text-xs leading-relaxed text-ink-4">{body}</p>
      </div>

      <ul className="flex flex-col gap-2">
        {rules.map((rule) => (
          <Rule key={rule.decision_id} rule={rule} />
        ))}
      </ul>
    </div>
  )
}

function Rule({ rule }: { rule: DecisionRecord }) {
  const tier = TIER[rule.source_tier] ?? {
    label: rule.source_tier.replace(/_/g, ' '),
    tone: 'neutral' as const,
  }

  // A rule about every element rather than a pair. It reads as nonsense as a
  // subject and an object, so it gets its own sentence.
  const isAboutEverything = rule.subject === '*' && rule.object === '*'

  const lines =
    rule.start_line === null
      ? null
      : rule.end_line && rule.end_line !== rule.start_line
        ? `${rule.start_line}-${rule.end_line}`
        : `${rule.start_line}`

  return (
    <li className="flex flex-col gap-2 rounded-card border border-line bg-field p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <span className="text-sm leading-snug text-ink">
          {isAboutEverything ? (
            <>
              Nothing may call anything unless a rule permits it
              <span className="text-ink-4"> — the default refusal</span>
            </>
          ) : (
            <>
              <span className="font-mono">{rule.subject}</span>{' '}
              <span className="text-ink-3">
                {CONSTRAINT[rule.constraint] ?? rule.constraint.replace(/_/g, ' ')}
              </span>{' '}
              <span className="font-mono">{rule.object}</span>
            </>
          )}
        </span>
        <Pill tone={tier.tone}>{tier.label}</Pill>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-ink-4">
        <span className="break-all">
          {rule.source_ref}
          {lines && <span className="text-ink-3">:{lines}</span>}
        </span>
        <span>from {rule.valid_from}</span>
        {rule.valid_to && <span>until {rule.valid_to}</span>}
        {!rule.valid_to && <span>still in force</span>}
      </div>

      {rule.rationale && (
        <p className="max-w-prose text-xs leading-relaxed text-ink-3">
          {rule.rationale}
        </p>
      )}
    </li>
  )
}
