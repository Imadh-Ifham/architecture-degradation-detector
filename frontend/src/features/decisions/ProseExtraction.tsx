/**
 * Reading decisions out of prose.
 *
 * Description:
 *   **Nothing here runs.** It is the design for the one capability this screen
 *   is visibly missing, placed where the gap appears so the gap and the answer
 *   to it are read together.
 *
 *   The gap is measurable and it is on the screen above: a repository can hold
 *   a hundred and thirty-eight decision records and supply zero rules, because
 *   the records are paragraphs written for people and a rule has to name two
 *   elements and a constraint between them. Every other source on this screen
 *   reads a format a parser can agree with. Prose is the one that needs a model.
 *
 *   **It is drawn, not hidden, for a reason.** A screen that offers three
 *   sources and silently discards the documents a team actually wrote is a
 *   screen that misreports what is possible. Showing the step with what it
 *   would produce — and that it has not run — is the same rule the rest of this
 *   application follows: an absent check never looks like a passed one.
 *
 *   **What it would not do.** It would not raise a rule to the strength of one
 *   somebody wrote: a model's reading of a paragraph is a *candidate*, it is
 *   capped below a ratified decision, and it cannot on its own produce a
 *   contradiction. It would cite the lines it read, checked against the
 *   document rather than trusted from the output, and an architect would
 *   ratify it before it governed anything.
 */

import { Card, Pill } from '../../components/ui'

/** The step as it would run, in the order it would run. */
const STEPS: readonly { title: string; body: string }[] = [
  {
    title: 'Read the document',
    body: 'The record as written — context, decision, consequences — and the path it sits at. In a monorepository the path already names the service the decision is about, so the subject comes free.',
  },
  {
    title: 'Propose a constraint',
    body: 'One of the four the system already understands, between two named elements, or nothing at all. Most records are about naming, tooling or style and should yield nothing; a step that always finds a rule is a step that invents them.',
  },
  {
    title: 'Check the citation',
    body: 'The quoted lines have to exist in the document. Verified in code against the file, never trusted from the answer — the same guard the verdict stage already applies.',
  },
  {
    title: 'Hold it for a person',
    body: 'A proposed rule arrives capped and unratified. It ranks for review; it does not govern, and it cannot contradict anything until somebody confirms it is their team’s rule.',
  },
]

export default function ProseExtraction({ documents }: { documents: number }) {
  return (
    <Card
      title="Decisions written as prose"
      action={<Pill tone="ai">designed, not running</Pill>}
    >
      <div className="flex flex-col gap-7">
        <div className="flex flex-col gap-3">
          {documents > 0 ? (
            <p className="max-w-prose text-sm leading-relaxed text-ink-2">
              This repository holds{' '}
              <span className="font-mono text-ink">{documents}</span> decision
              records that no source above can use. They are paragraphs written
              for people, and a rule has to name two elements and a constraint
              between them.
            </p>
          ) : (
            <p className="max-w-prose text-sm leading-relaxed text-ink-2">
              Where a repository keeps decision records as prose, no source
              above can use them: a rule has to name two elements and a
              constraint between them, and a paragraph does not.
            </p>
          )}
          <p className="max-w-prose text-sm leading-relaxed text-ink-3">
            Reading them is the one job on this screen that needs a language
            model. The step below is designed and deliberately not wired up —
            what it would produce is a <em>candidate</em>, held for an
            architect, never a rule that governs on its own.
          </p>
        </div>

        <ol className="flex flex-col gap-4">
          {STEPS.map((step, index) => (
            <li key={step.title} className="flex gap-4">
              <span className="mt-0.5 font-mono text-xs text-ink-4">
                {index + 1}
              </span>
              <div className="flex flex-col gap-1">
                <span className="text-sm leading-snug text-ink">{step.title}</span>
                <p className="max-w-prose text-xs leading-relaxed text-ink-3">
                  {step.body}
                </p>
              </div>
            </li>
          ))}
        </ol>

        <p className="max-w-prose border-t border-line pt-5 text-xs leading-relaxed text-ink-4">
          A proposed rule would be capped below one a person wrote, would carry
          the lines it was read from, and could not produce a contradiction
          before somebody ratified it. Those three limits are why it is worth
          drawing before it is worth building.
        </p>
      </div>
    </Card>
  )
}
