/**
 * The three decision sources, in a person's words.
 *
 * Description:
 *   One definition, because the decisions list, the row for each release and
 *   the pipeline all name the same three things. Two copies of these strings
 *   is two vocabularies, and the one somebody reads on the pipeline would stop
 *   matching the one they chose from.
 *
 *   **`readsFrom` is the part that is easy to leave out and should not be.** A
 *   card showing only a number invites the reader to assume all the rules
 *   behind it are the same kind of thing. They are not: a rule read out of an
 *   enforced policy file and a rule somebody wrote in prose are different
 *   strengths of evidence, and the tier is what caps the conclusion later.
 */

import type { DecisionMode } from '../../lib/api'

export const MODE: Record<
  DecisionMode,
  { title: string; short: string; detail: string }
> = {
  repo_adr: {
    title: 'Decision records in this repository',
    short: 'Records in this repository',
    detail: 'Written decisions kept alongside the code.',
  },
  external_adr: {
    title: 'Decision records in a repository you name',
    short: 'Records in another repository',
    detail: 'For teams that keep their decisions outside the codebase.',
  },
  combined: {
    title: 'Both, plus rules recovered from configuration',
    short: 'Both, plus configuration',
    detail:
      'The only option that produces a result on a repository holding no written decisions.',
  },
}

/** Which file types a mode reads, so the kinds of evidence are visible. */
export const READS_FROM: Record<
  DecisionMode,
  readonly { glyph: string; label: string }[]
> = {
  repo_adr: [{ glyph: 'MD', label: 'decision records in this repository' }],
  external_adr: [{ glyph: 'MD', label: 'decision records in another repository' }],
  combined: [
    { glyph: 'MD', label: 'decision records, where a repository keeps any' },
    { glyph: 'YML', label: 'network policies and identity manifests' },
    { glyph: 'PRO', label: 'service contracts (.proto)' },
  ],
}
