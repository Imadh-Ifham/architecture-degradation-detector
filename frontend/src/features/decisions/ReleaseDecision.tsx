/**
 * What one release is judged against.
 *
 * Description:
 *   One row of the decisions list: a release, the three sources it could be
 *   judged against, and - once opened - what each of them would actually
 *   supply for *that* release.
 *
 *   **The yields are fetched when the row is opened, not when the list is.**
 *   A stack of fifty releases is fifty probes, each of which reads files and
 *   runs the scan; doing that on mount would make the screen unusable at the
 *   size it exists for. The counts a person needs are the ones for the release
 *   they are deciding about.
 *
 *   **Per release, because a repository's history is not uniform.** A team
 *   adopts decision records partway through; the source with something to say
 *   about an early release is often not the one with something to say about a
 *   recent one. One mode applied to the whole stack would quietly judge the
 *   early releases against a source that did not exist yet.
 */

import { useState } from 'react'
import { Button, ErrorState, Pill, Spinner } from '../../components/ui'
import {
  readDecisionSources,
  type DecisionMode,
  type ModeAvailability,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'
import type { DecisionChoice } from '../../workspace/context'
import { MODE, READS_FROM } from './modes'
import RuleList from './RuleList'
import WhatWasExtracted from './WhatWasExtracted'

export default function ReleaseDecision({
  repositoryKey,
  release,
  choice,
  onChoose,
  isValidated,
}: {
  repositoryKey: string
  release: string
  choice: DecisionChoice | undefined
  onChoose: (choice: DecisionChoice) => void
  isValidated: boolean
}) {
  const [isOpen, setIsOpen] = useState(false)

  // Fetched for the row whether or not it is open. The count is the thing
  // somebody is choosing *on* - a card with no number on it asks them to pick
  // blind - so it cannot wait for an expand. What the expand buys is the
  // detail: each source's own sentence, and the rules themselves.
  const sources = useRequest(
    (options) => readDecisionSources(repositoryKey, release, options),
    [repositoryKey, release],
  )

  const modes = sources.data?.modes ?? []
  const chosenYield = modes.find((row) => row.mode === choice?.mode)
  const recommended = sources.data?.recommended ?? null

  return (
    <li className="flex flex-col gap-5 bg-panel px-6 py-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <span className="font-mono text-sm text-ink">{release}</span>
          {isValidated && <Pill tone="ok">judged</Pill>}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {sources.isLoading && <Spinner label="reading" />}
          {choice ? (
            <Pill tone="ai">{MODE[choice.mode].short}</Pill>
          ) : (
            <Pill tone="warn">nothing chosen</Pill>
          )}
          <Button size="sm" variant="quiet" onClick={() => setIsOpen(!isOpen)}>
            {isOpen ? 'Hide the rules' : 'Show the rules'}
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {(Object.keys(MODE) as DecisionMode[]).map((mode) => (
          <ModeButton
            key={mode}
            mode={mode}
            isChosen={choice?.mode === mode}
            isRecommended={recommended === mode}
            yields={modes.find((row) => row.mode === mode)}
            onChoose={() =>
              onChoose({ mode, adrRepositoryId: choice?.adrRepositoryId ?? null })
            }
          />
        ))}
      </div>

      {sources.error && <ErrorState message={sources.error} onRetry={sources.reload} />}

      {isOpen && (
        <div className="flex flex-col gap-5 border-t border-line pt-5">
          {sources.data && (
            <>
              <ul className="flex flex-col gap-2">
                {modes.map((row) => (
                  <Yield key={row.mode} row={row} />
                ))}
              </ul>

              {choice && (
                <>
                  {/* Before the rules themselves, what kind of rules they
                      are. The count a reader carries away from this screen
                      is the one they will be asked to defend, and the total
                      on its own overstates what governs the architecture. */}
                  {chosenYield && <WhatWasExtracted mode={chosenYield} />}
                  <RuleList
                    repositoryId={repositoryKey}
                    release={release}
                    mode={choice.mode}
                  />
                </>
              )}
            </>
          )}
        </div>
      )}
    </li>
  )
}

function ModeButton({
  mode,
  isChosen,
  isRecommended,
  yields,
  onChoose,
}: {
  mode: DecisionMode
  isChosen: boolean
  isRecommended: boolean
  yields: ModeAvailability | undefined
  onChoose: () => void
}) {
  return (
    <button
      type="button"
      onClick={onChoose}
      className={`flex flex-col gap-2.5 rounded-card border p-4 text-left transition ${
        isChosen
          ? 'border-ai bg-ai-wash'
          : 'border-line bg-field hover:border-line-strong'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="text-xs leading-snug font-medium">{MODE[mode].short}</span>
        {yields ? (
          <span
            className={`font-mono text-sm ${yields.records ? 'text-ink' : 'text-ink-4'}`}
          >
            {yields.records}
          </span>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {READS_FROM[mode].map((source) => (
          <span
            key={source.glyph}
            title={source.label}
            className="inline-flex rounded border border-line-strong px-1 py-0.5 font-mono text-[10px] text-ink-4"
          >
            {source.glyph}
          </span>
        ))}
        {isRecommended && <Pill tone="ok">most to offer</Pill>}
      </div>
    </button>
  )
}

/** One source's own sentence, which is where a zero explains itself. */
function Yield({ row }: { row: ModeAvailability }) {
  return (
    <li className="flex flex-col gap-1">
      <span className="font-mono text-xs text-ink-2">
        <span className="text-ink">{row.records}</span> {MODE[row.mode].short}
        {!row.ran && <span className="text-warn"> · not configured</span>}
      </span>
      {row.reason && (
        <span className="text-xs leading-relaxed text-ink-4">{row.reason}</span>
      )}
      {Object.entries(row.source_notes).map(([source, note]) => (
        <span key={source} className="text-xs leading-relaxed text-ink-4">
          {source.replace(/_/g, ' ')}: {note}
        </span>
      ))}
    </li>
  )
}
