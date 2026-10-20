/**
 * The run, read back as sentences.
 *
 * Description:
 *   A model is handed the figures this release published and asked to write
 *   what they say. Four paragraphs: what the run read, what it concluded,
 *   what to distrust about it, and one line of headline.
 *
 *   **It is a reading of the result and not part of it.** Nothing here
 *   reaches a verdict, changes a confidence or touches the published graph —
 *   the account is written after everything is decided, from numbers that are
 *   already on this screen. Where a sentence disagrees with a figure beside
 *   it, the figure is the one to believe, and the figures the model was shown
 *   are printed under the prose so that is checkable rather than asserted.
 *
 *   It is behind a button rather than loaded with the page, for two reasons
 *   that point the same way. It costs a model call, and a paragraph that
 *   appears on its own next to the verdicts invites being read as one of
 *   them. Asking for it is the reader deciding they want the softer version.
 *
 *   When no model can be reached it says so and shows nothing. A sentence
 *   assembled here from the same numbers would read like the model's at a
 *   glance, and the one thing this panel must not do is make it harder to
 *   tell which text on the screen a model wrote.
 */

import { useState } from 'react'
import { Button, Card, Pill, Spinner } from '../../components/ui'
import { messageOf, narrateRun, type RunNarrative as Narrative } from '../../lib/api'

export default function RunNarrative({
  repositoryKey,
  release,
}: {
  repositoryKey: string
  release: string
}) {
  const [narrative, setNarrative] = useState<Narrative | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isWriting, setIsWriting] = useState(false)

  async function write() {
    setIsWriting(true)
    setError(null)
    try {
      setNarrative(await narrateRun(repositoryKey, release))
    } catch (cause) {
      setError(messageOf(cause))
    } finally {
      setIsWriting(false)
    }
  }

  return (
    <Card
      title="This run in plain English"
      action={
        <div className="flex items-center gap-4">
          {narrative && (
            <span className="font-mono text-xs text-ai">
              written by {narrative.model_id}
              {narrative.cached && ' · replayed'}
            </span>
          )}
          <Button variant="secondary" size="sm" onClick={write} disabled={isWriting}>
            {isWriting ? 'writing…' : narrative ? 'write it again' : 'ask for the account'}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-7">
        {!narrative && !isWriting && !error && (
          <p className="max-w-prose text-sm leading-relaxed text-ink-3">
            A model is given the figures this release published and asked to say
            what they mean. It reaches no verdict and adds no finding — it is
            the same result, in sentences. The figures it was shown are printed
            underneath it.
          </p>
        )}

        {isWriting && <Spinner label="a model is reading the figures" />}

        {error && (
          <p className="max-w-prose border-l-2 border-bad/60 pl-4 text-sm leading-relaxed text-bad">
            {error}
          </p>
        )}

        {narrative && <Account narrative={narrative} />}
      </div>
    </Card>
  )
}

function Account({ narrative }: { narrative: Narrative }) {
  const [showFigures, setShowFigures] = useState(false)

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-4 rounded-card border border-ai/40 px-7 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <Pill tone="ai">a model wrote this</Pill>
          <span className="font-mono text-[11px] text-ink-4">
            {narrative.prompt_version}
          </span>
        </div>
        <p className="max-w-prose text-base leading-relaxed text-ink">
          {narrative.headline}
        </p>
      </div>

      <Paragraph term="what it read">{narrative.what_it_read}</Paragraph>
      <Paragraph term="what it concluded">{narrative.what_it_concluded}</Paragraph>
      <Paragraph term="what to distrust">{narrative.what_to_distrust}</Paragraph>

      <div className="flex flex-col gap-4 border-t border-line pt-6">
        <button
          onClick={() => setShowFigures(!showFigures)}
          className="self-start font-mono text-xs text-ink-3 transition hover:text-ink"
        >
          {showFigures ? 'hide' : 'show'} the figures the model was shown →
        </button>

        {showFigures && (
          <pre className="max-h-96 overflow-auto rounded-control border border-line bg-sunken px-4 py-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-ink-2">
            {JSON.stringify(narrative.figures, null, 2)}
          </pre>
        )}

        <p className="max-w-prose text-xs leading-relaxed text-ink-4">
          Every number in the account comes from this block, and the block comes
          from the published document. Nothing above was re-derived, and a
          sentence that disagrees with a count on this screen is the sentence
          that is wrong.
        </p>
      </div>
    </div>
  )
}

function Paragraph({ term, children }: { term: string; children: string }) {
  return (
    <div className="flex flex-col gap-2.5">
      <span className="text-xs tracking-wide text-ink-4">{term}</span>
      <p className="max-w-prose text-sm leading-relaxed text-ink-2">{children}</p>
    </div>
  )
}
