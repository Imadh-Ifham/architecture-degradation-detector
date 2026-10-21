/**
 * What a confidence number is made of.
 *
 * Description:
 *   `0.85` on its own is unreadable. It is not a probability, it is not a
 *   percentage, and on a corpus of strong evidence every edge carries the
 *   same value — so a reader sees one number seventeen times and learns
 *   nothing from any of them.
 *
 *   **Three things make it legible, and all three come from the document.**
 *   The scale, because 0.85 *is* the maximum this method publishes and
 *   "0.85 out of 0.85" says something "0.85" does not. The named
 *   contributions, because the number is a sum of things a person can agree
 *   or disagree with rather than a model's opinion of itself. And the
 *   ceiling where one applied, because a number held down by a rule read out
 *   of prose is a different claim from the same number reached freely.
 *
 *   **The missing 0.15 is deliberate and worth saying out loud.** Nothing
 *   here ever publishes certainty: the remainder is what an uncalibrated
 *   score over an architecture nobody has labelled cannot establish. A scheme
 *   whose best case was 1.0 would be claiming something it has no way to
 *   reach.
 *
 *   Nothing is recomputed. Every figure is read off the published edge, so
 *   the explanation cannot drift from the number it explains.
 */

import { Pill } from '../../components/ui'
import type { ValidatedEdge } from '../../lib/api'
import { CEILING, TERM, band, ceilingOf } from './certainty'


export default function Confidence({ edge }: { edge: ValidatedEdge }) {
  const ceiling = ceilingOf(edge)
  const terms = Object.entries(edge.confidence_terms)
  const atCeiling = edge.confidence >= ceiling

  if (edge.confidence === 0 && terms.length === 0) {
    return (
      <p className="max-w-prose text-sm leading-relaxed text-ink-3">
        <span className="text-ink">No confidence, because nothing was claimed.</span>{' '}
        A number here would be confidence in an assertion that was never made.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-5">
      {/* The sentence first. "Confidence 0.85" beside "contradicted" reads
          as *we are 85% sure this is fine*, which is the opposite of what the
          row says - and that misreading is the whole problem with the
          number, not its value. */}
      <p className="max-w-prose text-sm leading-relaxed text-ink-2">
        How much <span className="text-ink">this verdict</span> can be relied
        on — not whether the dependency is healthy.{' '}
        <span className="text-ink-4">
          A contradiction can be entirely certain, and a confirmation can be
          weak.
        </span>
      </p>

      <div className="flex flex-wrap items-baseline gap-4">
        <span className="font-mono text-2xl leading-none text-ink">
          {edge.confidence.toFixed(2)}
        </span>
        <span className="font-mono text-sm text-ink-4">
          out of {ceiling.toFixed(2)}
        </span>
        <Pill tone={atCeiling ? 'ok' : 'warn'}>{band(edge)}</Pill>
        {edge.confidence_ceiling && <Pill tone="warn">held down</Pill>}
      </div>

      <span className="flex h-2 w-full max-w-sm overflow-hidden rounded-full bg-raised">
        <span
          className={`block h-full ${atCeiling ? 'bg-ok' : 'bg-warn'}`}
          style={{ width: `${Math.min(100, (edge.confidence / ceiling) * 100)}%` }}
        />
      </span>

      {terms.length > 0 && (
        <ul className="flex flex-col gap-2">
          {terms.map(([name, value]) => (
            <li key={name} className="flex gap-4">
              <span className="w-12 shrink-0 text-right font-mono text-xs text-ink-2">
                +{value.toFixed(2)}
              </span>
              <span className="max-w-prose text-xs leading-relaxed text-ink-3">
                {TERM[name] ?? name.replace(/_/g, ' ')}
              </span>
            </li>
          ))}
        </ul>
      )}

      {edge.confidence_ceiling && (
        <p className="max-w-prose border-l-2 border-warn/60 pl-4 text-xs leading-relaxed text-warn">
          Capped at {edge.confidence.toFixed(2)} because{' '}
          {CEILING[edge.confidence_ceiling] ??
            edge.confidence_ceiling.replace(/_/g, ' ')}
          .
        </p>
      )}

      <p className="max-w-prose border-t border-line pt-4 text-xs leading-relaxed text-ink-4">
        {ceiling.toFixed(2)} is the most this method publishes for anything. The
        remaining {(1 - ceiling).toFixed(2)} is what an uncalibrated score over an
        architecture nobody has labelled cannot establish — a scheme whose best
        case was 1.00 would be claiming certainty it has no way to reach.
      </p>
    </div>
  )
}
