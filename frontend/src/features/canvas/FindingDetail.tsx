/**
 * One dependency on the canvas, opened up.
 *
 * Description:
 *   The validated graph draws a contradiction as a red line, which says
 *   *where* one is and nothing about *what* it is. This is what a reader gets
 *   when they click it: the pair, the rule it was judged against, what each
 *   of the three judges said, and — the part a bucket name cannot carry — the
 *   sentences the models actually wrote about this dependency.
 *
 *   **The reasoning is read out of the run transcript, not out of the
 *   graph.** The published document is the contract the next phase reads and
 *   a paragraph of prose has no business in it; the transcript is the record
 *   kept for a person. The two are joined on `evidence_hash`, which is the
 *   sealed evidence package the verdict was reached from and the key the
 *   model request was cached on. So what is shown here is not a summary of
 *   the verdict — it is the response that produced it.
 *
 *   **A release with no transcript still opens.** Everything from the
 *   document is shown and the model's words are reported as not kept, which
 *   is a different statement from a verdict reached without a model and must
 *   not read like one.
 */

import { useState } from 'react'
import { Pill } from '../../components/ui'
import type { ModelCall, ModelTranscript, PublishedGraph, ValidatedEdge } from '../../lib/api'
import Confidence from '../validation/Confidence'

export default function FindingDetail({
  edge,
  document,
  transcript,
  onClose,
}: {
  edge: ValidatedEdge
  document: PublishedGraph
  transcript: ModelTranscript | null
  onClose: () => void
}) {
  const names = new Map(document.nodes.map((node) => [node.id, node.name]))
  const calls = callsFor(transcript, edge)

  return (
    <div className="flex flex-col gap-7 rounded-card border border-line bg-panel px-7 py-6">
      <header className="flex flex-wrap items-start justify-between gap-5">
        <div className="flex min-w-0 flex-col gap-2">
          <span className="font-mono text-sm text-ink">
            {names.get(edge.source) ?? edge.source}
            <span className="px-2 text-ink-4">→</span>
            {names.get(edge.target) ?? edge.target}
          </span>
          <span className="font-mono text-[11px] text-ink-4">
            {String(edge.attributes.observed_as ?? edge.relationship)} · {edge.fact_id}
          </span>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <Pill tone={bucketTone(edge.bucket)}>{edge.bucket.replace(/_/g, ' ')}</Pill>
          {edge.route === 'review' && <Pill tone="warn">held for a person</Pill>}
          <button
            onClick={onClose}
            className="font-mono text-xs text-ink-4 transition hover:text-ink"
          >
            close
          </button>
        </div>
      </header>

      <Verdict edge={edge} />

      {/* Before the judges, because the number is the first thing a reader
          looks at and the one they cannot interpret unaided. */}
      <div className="flex flex-col gap-4">
        <span className="text-xs tracking-wide text-ink-4">
          how confident, and why
        </span>
        <Confidence edge={edge} />
      </div>

      <Judges edge={edge} />

      <WhatTheModelsSaid calls={calls} transcript={transcript} edge={edge} />
    </div>
  )
}

/** The claim and the rule behind it, before any machinery. */
function Verdict({ edge }: { edge: ValidatedEdge }) {
  return (
    <dl className="grid gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
      <Figure
        term="judged against"
        value={edge.governing_decision ?? 'nothing covers this pair'}
      />
      <Figure term="evidence strength" value={tier(edge.source_tier)} />
      <Figure
        term="how sure of this verdict"
        value={
          edge.confidence > 0
            ? `${edge.confidence.toFixed(2)} of ${(edge.confidence_maximum || 0.85).toFixed(2)}`
            : 'none'
        }
        note={edge.confidence === 0 ? 'no claim was established' : 'what it is made of, below'}
      />
      <Figure
        term="model calls"
        value={String(edge.model_calls)}
        note={edge.model_calls === 0 ? 'replayed, or none were made' : 'on the last run'}
      />
    </dl>
  )
}

/**
 * What each of the three said, with the one that is not a model marked.
 *
 * Spelled out in sentences rather than shown as three pills, because the
 * combination is the finding: two models agreeing where the table disagreed
 * is a different situation from all three agreeing, and a row of coloured
 * words does not say which one this is.
 */
function Judges({ edge }: { edge: ValidatedEdge }) {
  if (edge.produced_by !== 'model') {
    return (
      <p className="max-w-prose border-l-2 border-line-strong pl-4 text-sm leading-relaxed text-ink-3">
        No model was asked about this dependency. Nothing in the recorded
        decisions speaks to this pair, so there was no rule to judge it
        against — which is a finding about the decision record rather than
        about the architecture.
      </p>
    )
  }

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Judge
        role="reached the verdict"
        tone="ai"
        said={edge.bucket.replace(/_/g, ' ')}
      />
      <Judge
        role="asked what is wrong with it"
        tone="ai"
        said={
          {
            agree: 'found no fault in the argument',
            disagree: 'objected to the argument',
            uncertain: 'could not say',
          }[edge.verification_outcome ?? ''] ?? 'was not reached'
        }
      />
      <Judge
        role="decides whether they are believed"
        tone="neutral"
        said={
          {
            agreed: 'the rule agrees',
            disagreed: 'the rule disagrees',
            not_comparable: 'nothing to compare — the verdict is not a conclusion',
            not_checked: 'the table abstained on this pair',
          }[edge.arbiter_agreement ?? ''] ?? 'not recorded'
        }
      />
    </div>
  )
}

function Judge({
  role,
  tone,
  said,
}: {
  role: string
  tone: 'ai' | 'neutral'
  said: string
}) {
  return (
    <div
      className={`flex flex-col gap-2 rounded-control border px-5 py-4 ${
        tone === 'ai' ? 'border-ai/40' : 'border-line'
      }`}
    >
      <span className="text-[11px] tracking-wide text-ink-4">{role}</span>
      <span className="text-sm leading-relaxed text-ink-2">{said}</span>
      {tone === 'neutral' && (
        <span className="font-mono text-[10.5px] text-ink-4">a table · no model</span>
      )}
    </div>
  )
}

/**
 * The sentences the models wrote, which is the whole reason this panel exists.
 *
 * Shown as the response that was returned rather than as a retold version of
 * it. A screen that paraphrased a verdict would be a fourth opinion nobody
 * counted, and the citations in particular have to be the model's own: the
 * grounding guarantee is that every reference it names was in the package it
 * was shown, and that is only checkable against what it actually said.
 */
function WhatTheModelsSaid({
  calls,
  transcript,
  edge,
}: {
  calls: ModelCall[]
  transcript: ModelTranscript | null
  edge: ValidatedEdge
}) {
  if (edge.produced_by !== 'model') return null

  if (!transcript) {
    return (
      <Absent>
        No transcript was kept for the run that published this release, so the
        models&rsquo; own words are not available for it. Run the validation
        again and every call it makes is recorded. This is not the same as a
        verdict reached without a model — that would say so above.
      </Absent>
    )
  }

  if (!edge.evidence_hash) {
    return (
      <Absent>
        This document was published before the edge carried the evidence hash,
        which is what joins a dependency to the calls made about it. Re-run the
        release and the calls appear here.
      </Absent>
    )
  }

  if (calls.length === 0) {
    return (
      <Absent>
        The run transcript holds no call against this dependency&rsquo;s
        evidence. It was published by an earlier run than the transcript on
        file.
      </Absent>
    )
  }

  return (
    <div className="flex flex-col gap-5">
      <span className="text-xs tracking-wide text-ink-4">
        what the models said about this dependency
      </span>
      {calls.map((call) => (
        <Said key={call.sequence} call={call} />
      ))}
    </div>
  )
}

function Said({ call }: { call: ModelCall }) {
  const [showPrompt, setShowPrompt] = useState(false)
  const answer = (call.response ?? {}) as {
    reasoning?: string
    verdict?: string
    outcome?: string
    cited_evidence_refs?: string[]
    objections?: { kind?: string; ref?: string | null; statement?: string }[]
  }

  return (
    <div className="flex flex-col gap-3 rounded-control border border-line bg-sunken px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="flex items-center gap-3">
          <span className="font-mono text-[11px] text-ink-3">
            {call.task.replace(/_/g, ' ')}
          </span>
          <span className="font-mono text-[11px] text-ai">{call.answered_model}</span>
        </span>
        <span className="flex items-center gap-3">
          {(answer.verdict || answer.outcome) && (
            <Pill tone="ai">{(answer.verdict ?? answer.outcome)!.replace(/_/g, ' ')}</Pill>
          )}
          <span className="font-mono text-[10.5px] text-ink-4">
            {call.outcome === 'answered' ? 'answered live' : call.outcome}
          </span>
        </span>
      </div>

      {answer.reasoning ? (
        <p className="max-w-prose text-sm leading-relaxed text-ink-2">
          {answer.reasoning}
        </p>
      ) : (
        <p className="text-sm leading-relaxed text-ink-4">
          {call.error ?? 'the answer carried no reasoning'}
        </p>
      )}

      {answer.cited_evidence_refs && answer.cited_evidence_refs.length > 0 && (
        <p className="font-mono text-[11px] leading-relaxed text-ink-4">
          cited {answer.cited_evidence_refs.join(', ')} — every one of these was
          in the package it was shown, checked in code rather than trusted
        </p>
      )}

      {answer.objections && answer.objections.length > 0 && (
        <ul className="flex flex-col gap-2">
          {answer.objections.map((objection, index) => (
            <li
              key={index}
              className="max-w-prose border-l-2 border-warn/60 pl-4 text-xs leading-relaxed text-warn"
            >
              <span className="font-mono">{objection.kind?.replace(/_/g, ' ')}</span>
              {objection.ref ? ` · ${objection.ref}` : ''} — {objection.statement}
            </li>
          ))}
        </ul>
      )}

      <button
        onClick={() => setShowPrompt(!showPrompt)}
        className="self-start font-mono text-[11px] text-ink-4 transition hover:text-ink"
      >
        {showPrompt ? 'hide' : 'show'} what it was sent →
      </button>

      {showPrompt && (
        <pre className="max-h-80 overflow-auto rounded-control border border-line bg-panel px-4 py-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-ink-3">
          {call.prompt}
        </pre>
      )}
    </div>
  )
}

function Absent({ children }: { children: React.ReactNode }) {
  return (
    <p className="max-w-prose border-l-2 border-line-strong pl-4 text-xs leading-relaxed text-ink-4">
      {children}
    </p>
  )
}

function Figure({
  term,
  value,
  note,
}: {
  term: string
  value: string
  note?: string
}) {
  return (
    <div className="flex flex-col gap-1 bg-panel px-4 py-3">
      <dt className="text-[11px] leading-tight text-ink-4">{term}</dt>
      <dd className="font-mono text-xs leading-relaxed break-words text-ink-2">{value}</dd>
      {note && <dd className="text-[10.5px] leading-tight text-ink-4">{note}</dd>}
    </div>
  )
}

/**
 * The calls made about one dependency, in the order they were made.
 *
 * Joined on the evidence hash rather than on the fact id, because the hash is
 * what the model request was keyed on and the fact id never reaches the AI
 * layer at all — a component names a task and hands over sealed evidence, and
 * it is deliberately not told which model answers.
 */
function callsFor(transcript: ModelTranscript | null, edge: ValidatedEdge): ModelCall[] {
  if (!transcript || !edge.evidence_hash) return []

  return transcript.calls.filter((call) => call.evidence_hash === edge.evidence_hash)
}

function bucketTone(bucket: string) {
  const value = bucket.toLowerCase()

  if (value.includes('contradict')) return 'bad' as const
  if (value.includes('review') || value.includes('insufficient')) return 'warn' as const
  if (value.includes('confirm')) return 'ok' as const
  return 'neutral' as const
}

function tier(value: string | null): string {
  return value ? value.replace(/_/g, ' ') : 'no source'
}
