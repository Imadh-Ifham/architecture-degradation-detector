/**
 * Saying what a confidence number means, in one place.
 *
 * Description:
 *   **The word is what confuses people, not the number.** "Confidence 0.85"
 *   beside "contradicted" reads as *we are 85% sure this dependency is fine*,
 *   which is the opposite of what the row says. It is not about the
 *   dependency at all: it is how much the **verdict** can be relied on. A
 *   contradiction can be entirely certain, and this one is.
 *
 *   So every surface that shows the number uses the same words from here.
 *   Three screens inventing three phrasings is how one of them ends up
 *   saying something the scoring does not.
 *
 *   Nothing is recomputed. The terms, the ceiling and the maximum are read
 *   off the published edge, so a sentence cannot drift from the number it
 *   describes.
 */

import type { ValidatedEdge } from '../../lib/api'

/** What each scoring term means, in a sentence a person can argue with. */
export const TERM: Record<string, string> = {
  verdict_base: 'a model reached a verdict at all',
  source_strength_authoritative:
    'the rule is executable configuration — enforced, versioned, current',
  source_strength_supporting: 'the rule was written down, but nothing enforces it',
  source_strength_weak: 'the rule was inferred rather than stated',
  verification_agreement: 'a second model attacked the argument and found no fault',
}

/** Why a ceiling was applied, in the same voice. */
export const CEILING: Record<string, string> = {
  source_tier_3_documentation: 'the rule was read out of prose, not configuration',
  source_tier_4_history: 'the rule was inferred from commit history',
  source_tier_5_convention: 'the rule was inferred from a naming convention',
  observation_inferred: 'recovery inferred this dependency rather than reading it',
  verification_disagree: 'the second model objected to the argument',
  verification_uncertain: 'the second model could not say',
  arbiter_disagreed: 'the deterministic table disagreed with the models',
  unverified_by_choice: 'this run did not ask the second model',
  unverified_unavailable: 'the second model could not be reached',
  verdict_without_a_model: 'no model produced this verdict — the table did',
  every_answer_rejected: 'every model answer was rejected, so nothing was concluded',
}

/** The most this method publishes, read off the edge with a safe fallback. */
export function ceilingOf(edge: ValidatedEdge): number {
  return edge.confidence_maximum || 0.85
}

/**
 * A short word for where the number sits on its own scale.
 *
 * Bands rather than a percentage. `0.85` of a possible `0.85` is a hundred
 * per cent of what this method can establish, and printing "100%" beside a
 * verdict would claim a certainty the design explicitly refuses - the
 * remaining 0.15 is what an uncalibrated score over an unlabelled
 * architecture cannot reach.
 */
export function band(edge: ValidatedEdge): string {
  const ceiling = ceilingOf(edge)

  if (edge.confidence <= 0) return 'nothing claimed'
  if (edge.confidence >= ceiling) return 'as strong as this method gets'
  if (edge.confidence >= ceiling * 0.75) return 'strong'
  if (edge.confidence >= ceiling * 0.5) return 'held back'
  return 'weak — for a person to read'
}

/**
 * The whole explanation as plain text, for a hover.
 *
 * A native `title`, because it has to work on an SVG edge label, in a table
 * cell and on a stat without three implementations of a tooltip.
 */
export function explain(edge: ValidatedEdge): string {
  const ceiling = ceilingOf(edge)

  if (edge.confidence <= 0 && Object.keys(edge.confidence_terms).length === 0) {
    return 'No number, because nothing was claimed about this dependency.'
  }

  const lines = [
    `${edge.confidence.toFixed(2)} out of ${ceiling.toFixed(2)} — how much this`,
    `verdict can be relied on, not whether the dependency is healthy.`,
    '',
  ]

  for (const [name, value] of Object.entries(edge.confidence_terms)) {
    lines.push(`  +${value.toFixed(2)}  ${TERM[name] ?? name.replace(/_/g, ' ')}`)
  }

  if (edge.confidence_ceiling) {
    lines.push('')
    lines.push(
      `Capped: ${CEILING[edge.confidence_ceiling] ?? edge.confidence_ceiling.replace(/_/g, ' ')}.`,
    )
  }

  lines.push('')
  lines.push(
    `${ceiling.toFixed(2)} is the maximum. The missing ${(1 - ceiling).toFixed(2)} is what an`,
  )
  lines.push('uncalibrated score over an unlabelled architecture cannot establish.')

  return lines.join('\n')
}
