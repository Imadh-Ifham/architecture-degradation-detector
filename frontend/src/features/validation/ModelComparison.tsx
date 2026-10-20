/**
 * What each judge said about each dependency, side by side.
 *
 * Description:
 *   One row per dependency, one column per judge. The point of the table is
 *   the **disagreements**: a row where all three columns say the same thing
 *   is unremarkable, and a row where they do not is the only thing in the
 *   system worth arguing about.
 *
 *   **Three judges, two of them models.** The first model reaches a verdict,
 *   a different model is asked what is wrong with that verdict, and a table
 *   with no model in it decides whether they are believed. The third column
 *   says "no model" in every row on purpose.
 *
 *   **Nothing here is inferred where the document does not say it.** A
 *   verifier column reading "no answer" means the document carries no
 *   verification outcome for a fact that did get a verdict - the verifier was
 *   not reached. That is a different fact from "nobody asked", which is what
 *   a dependency no rule governs gets, and the two never share a cell.
 *
 *   The counts above the table are the three-way combination: it is the one
 *   number a single-model pipeline cannot report, and it is what the second
 *   model exists to produce.
 */

import { Fragment, useState } from 'react'
import { Card, Pill } from '../../components/ui'
import type { PublishedGraph, ValidatedEdge } from '../../lib/api'

type Judgement = {
  label: string
  tone: 'ok' | 'warn' | 'bad' | 'ai' | 'neutral'
}

export default function ModelComparison({ document }: { document: PublishedGraph }) {
  const [opened, setOpened] = useState<string | null>(null)

  const names = new Map(document.nodes.map((node) => [node.id, node.name]))
  const stamp = document.graph.run
  const edges = document.links

  return (
    <Card
      title="What each judge said"
      action={
        <span className="font-mono text-xs text-ink-4">
          {edges.length} dependencies · click a row for the evidence
        </span>
      }
    >
      <div className="flex flex-col gap-8">
        <Agreement edges={edges} />

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <Head>dependency</Head>
                <Head>judged against</Head>
                <Head>
                  reaches the verdict
                  <Model name={stamp?.reasoner_model} />
                </Head>
                <Head>
                  challenges it
                  <Model name={stamp?.verifier_model} />
                </Head>
                <Head>
                  decides who is believed
                  <span className="mt-1 block font-mono text-[10.5px] text-ink-4">
                    a table · no model
                  </span>
                </Head>
                <Head align="right">outcome</Head>
              </tr>
            </thead>

            <tbody>
              {edges.map((edge) => {
                const isOpen = opened === edge.fact_id
                const reasoner = reasonerSaid(edge)
                const verifier = verifierSaid(edge)
                const rule = ruleSaid(edge)

                return (
                  <Fragment key={edge.fact_id}>
                    <tr
                      onClick={() => setOpened(isOpen ? null : edge.fact_id)}
                      className={`cursor-pointer transition ${
                        isOpen ? 'bg-raised' : 'hover:bg-raised/50'
                      }`}
                    >
                      <Cell>
                        <span className="font-mono whitespace-nowrap text-ink">
                          {names.get(edge.source) ?? edge.source}
                          <span className="px-1.5 text-ink-4">→</span>
                          {names.get(edge.target) ?? edge.target}
                        </span>
                        <span className="mt-1 block font-mono text-[11px] text-ink-4">
                          {String(edge.attributes.observed_as ?? edge.relationship)}
                        </span>
                      </Cell>

                      <Cell>
                        {edge.governing_decision ? (
                          <>
                            <span className="font-mono text-xs text-ink-2">
                              {edge.governing_decision}
                            </span>
                            <span className="mt-1 block font-mono text-[11px] text-ink-4">
                              {tier(edge.source_tier)}
                            </span>
                          </>
                        ) : (
                          <span className="text-xs text-ink-4">no rule covers it</span>
                        )}
                      </Cell>

                      <Cell>
                        <Pill tone={reasoner.tone}>{reasoner.label}</Pill>
                        <span className="mt-1.5 block font-mono text-[11px] text-ink-4">
                          {howProduced(edge)}
                        </span>
                      </Cell>

                      <Cell>
                        <Pill tone={verifier.tone}>{verifier.label}</Pill>
                      </Cell>

                      <Cell>
                        <Pill tone={rule.tone}>{rule.label}</Pill>
                      </Cell>

                      <Cell align="right">
                        <Pill tone={bucketTone(edge.bucket)}>
                          {edge.bucket.replace(/_/g, ' ')}
                        </Pill>
                        <span className="mt-1.5 block font-mono text-xs text-ink-2">
                          {edge.confidence > 0 ? edge.confidence.toFixed(2) : '—'}
                        </span>
                      </Cell>
                    </tr>

                    {isOpen && (
                      <tr>
                        <td colSpan={6} className="border-b border-line bg-sunken px-4 py-6">
                          <Detail edge={edge} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  )
}

/**
 * The three-way combination, counted.
 *
 * Row three is the one that is easy to leave out and the one that matters:
 * a fact nothing independent checked is neither a pass nor a failure, and a
 * screen that files it with the agreements is the absence of a check looking
 * like a passed check.
 */
function Agreement({ edges }: { edges: ValidatedEdge[] }) {
  // Every edge lands in exactly one row. The rows used to be independent
  // filters that happened to look like a breakdown, and a fact the second
  // model agreed with while the table could not compare matched none of
  // them - so seventeen dependencies were reported as sixteen and the
  // missing one was the only inconclusive fact in the run. On a panel whose
  // whole claim is that an absent check never looks like a passed one, a
  // fact that vanishes is the same failure wearing a different hat.
  const counts = {
    agreed: 0,
    objected: 0,
    uncertain: 0,
    unchecked: 0,
    correlated: 0,
    inconclusive: 0,
    notAsked: 0,
  }

  for (const edge of edges) {
    if (edge.produced_by !== 'model') counts.notAsked += 1
    else if (edge.verification_outcome === 'disagree') counts.objected += 1
    else if (edge.verification_outcome === 'uncertain') counts.uncertain += 1
    else if (!edge.verification_outcome) counts.unchecked += 1
    else if (edge.arbiter_agreement === 'disagreed') counts.correlated += 1
    else if (edge.arbiter_agreement === 'agreed') counts.agreed += 1
    else counts.inconclusive += 1
  }

  const rows = [
    {
      label: 'all three agreed',
      count: counts.agreed,
      tone: 'ok' as const,
      note: 'published',
    },
    {
      label: 'the second model objected',
      count: counts.objected,
      tone: 'warn' as const,
      note: 'held for a person',
    },
    {
      label: 'the second model was uncertain',
      count: counts.uncertain,
      tone: 'warn' as const,
      note: 'confidence capped',
    },
    {
      label: 'nothing independent checked it',
      count: counts.unchecked,
      tone: 'warn' as const,
      note: 'not agreement — capped and queued',
    },
    {
      label: 'both models agreed, the rule did not',
      count: counts.correlated,
      tone: 'bad' as const,
      note: 'correlated model failure, measured',
    },
    {
      label: 'nothing was concluded, so the rule had nothing to compare',
      count: counts.inconclusive,
      tone: 'warn' as const,
      note: 'no claim was established about this dependency',
    },
    {
      label: 'nobody was asked',
      count: counts.notAsked,
      tone: 'neutral' as const,
      note: 'no rule governs it, so no model was called',
    },
  ]

  const total = edges.length

  return (
    <div className="flex flex-col gap-3">
      {rows.map((row) => (
        <div key={row.label} className="flex items-center gap-5">
          <span className="w-64 shrink-0 text-sm text-ink-2">{row.label}</span>
          <span className="w-8 shrink-0 text-right font-mono text-sm text-ink">
            {row.count}
          </span>
          <span className="h-2 w-40 shrink-0 overflow-hidden rounded-full bg-raised">
            <span
              className={`block h-full ${
                { ok: 'bg-ok', warn: 'bg-warn', bad: 'bg-bad', neutral: 'bg-ink-4' }[row.tone]
              }`}
              style={{ width: `${total ? (row.count / total) * 100 : 0}%` }}
            />
          </span>
          <span className="text-xs text-ink-4">{row.note}</span>
        </div>
      ))}
    </div>
  )
}

function Detail({ edge }: { edge: ValidatedEdge }) {
  const types = (edge.attributes.evidence_types as string[] | undefined) ?? []

  return (
    <div className="grid gap-7 lg:grid-cols-3">
      <Field term="the rule it was judged against">
        {edge.governing_decision ?? 'none — nothing in the configuration speaks to this pair'}
      </Field>
      <Field term="evidence the models were given">
        {edge.evidence_refs.length > 0 ? edge.evidence_refs.join(', ') : 'none assembled'}
      </Field>
      <Field term="how the dependency was observed">
        {types.length > 0 ? types.join(', ').replace(/_/g, ' ') : 'declared in configuration'}
        {edge.attributes.confirmed_by_source ? ' · confirmed in source code' : ''}
      </Field>
      <Field term="model calls on this run">
        {edge.model_calls === 0
          ? 'none — replayed from the cache of an identical question'
          : `${edge.model_calls}`}
      </Field>
      <Field term="fact">{edge.fact_id}</Field>
      <Field term="evidence strength">{tier(edge.source_tier)}</Field>
    </div>
  )
}

function Field({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs tracking-wide text-ink-4">{term}</span>
      <span className="font-mono text-xs leading-relaxed break-words text-ink-2">
        {children}
      </span>
    </div>
  )
}

/**
 * What the reasoning model concluded.
 *
 * The document publishes the classified bucket rather than the model's raw
 * word, so this is the model's conclusion as it survived classification. A
 * fact no rule governs never reached a model at all, and says so.
 */
function reasonerSaid(edge: ValidatedEdge): Judgement {
  if (edge.produced_by !== 'model') {
    return { label: 'not asked', tone: 'neutral' }
  }

  return { label: edge.bucket.replace(/_/g, ' '), tone: bucketTone(edge.bucket) }
}

function verifierSaid(edge: ValidatedEdge): Judgement {
  if (edge.produced_by !== 'model') {
    return { label: 'nothing to check', tone: 'neutral' }
  }

  switch (edge.verification_outcome) {
    case 'agree':
      return { label: 'found no fault', tone: 'ok' }
    case 'disagree':
      return { label: 'objected', tone: 'warn' }
    case 'uncertain':
      return { label: 'uncertain', tone: 'warn' }
    default:
      return { label: 'no answer', tone: 'warn' }
  }
}

function ruleSaid(edge: ValidatedEdge): Judgement {
  switch (edge.arbiter_agreement) {
    case 'agreed':
      return { label: 'agreed', tone: 'ok' }
    case 'disagreed':
      return { label: 'disagreed', tone: 'bad' }
    case 'not_comparable':
      return { label: 'could not compare', tone: 'neutral' }
    case 'not_checked':
      return { label: 'not checked', tone: 'warn' }
    default:
      return { label: '—', tone: 'neutral' }
  }
}

function howProduced(edge: ValidatedEdge): string {
  if (edge.produced_by !== 'model') return 'no model was called'
  if (edge.model_calls === 0) return 'replayed from cache'
  return `${edge.model_calls} live call${edge.model_calls === 1 ? '' : 's'}`
}

function bucketTone(bucket: string): Judgement['tone'] {
  const value = bucket.toLowerCase()

  if (value.includes('contradict')) return 'bad'
  if (value.includes('review')) return 'warn'
  if (value.includes('confirm')) return 'ok'
  return 'neutral'
}

function tier(value: string | null): string {
  return value ? value.replace(/_/g, ' ') : 'no source'
}

function Model({ name }: { name: string | null | undefined }) {
  return (
    <span className="mt-1 block font-mono text-[10.5px] text-ai">
      {name ?? 'no model recorded'}
    </span>
  )
}

function Head({
  children,
  align = 'left',
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
}) {
  return (
    <th
      className={`border-b border-line px-4 py-3 align-top text-xs font-medium tracking-wide text-ink-3 ${
        align === 'right' ? 'text-right' : 'text-left'
      }`}
    >
      {children}
    </th>
  )
}

function Cell({
  children,
  align = 'left',
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
}) {
  return (
    <td
      className={`border-b border-line px-4 py-4 align-top ${
        align === 'right' ? 'text-right' : ''
      }`}
    >
      {children}
    </td>
  )
}
