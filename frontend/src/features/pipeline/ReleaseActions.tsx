/**
 * What an architect does with one release.
 *
 * Description:
 *   Validate it, and then go and read any of the four results **for that
 *   release**.
 *
 *   **Per release, not per run.** A stack of fifty releases is minutes of
 *   model calls; a loop over all of them is a progress bar somebody watches
 *   instead of a result they read. So each row is validated on its own, and
 *   the row says which source it will be judged against before it runs.
 *
 *   **Every link carries its release with it.** The result screens fall back
 *   to the workspace's focused release when they have no choice of their own,
 *   so a link sets that and navigates - which is what makes "the architecture
 *   graph of `v0.9.0`" a place rather than a release picker somebody has to
 *   find and set correctly. Without it, four links from fifty rows would all
 *   land on whichever release happened to be selected.
 */

import { useNavigate } from 'react-router'
import { Button, Pill } from '../../components/ui'
import type { ValidationRun } from '../../lib/api'
import type { DecisionChoice } from '../../workspace/context'
import { MODE, READS_FROM } from '../decisions/modes'

/**
 * Where a release can be read, and what each place needs first.
 *
 * Architecture is recovery's own output, so it is readable the moment a
 * release has recovered - gating it behind a verdict would hide the picture
 * an architect wants *before* deciding what to judge it against. The other
 * three describe a judgement and have nothing to show until one exists.
 */
const RESULTS: readonly { to: string; label: string; needsRun: boolean }[] = [
  { to: '/architecture', label: 'Architecture', needsRun: false },
  { to: '/validation', label: 'Validation', needsRun: true },
  { to: '/findings', label: 'Findings', needsRun: true },
  { to: '/canvas', label: 'Canvas', needsRun: true },
]

export default function ReleaseActions({
  release,
  choice,
  run,
  isRecovered,
  isValidating,
  onValidate,
  onFocus,
}: {
  release: string
  choice: DecisionChoice | undefined
  run: ValidationRun | undefined
  isRecovered: boolean
  isValidating: boolean
  onValidate: () => void
  onFocus: (release: string) => void
}) {
  const navigate = useNavigate()

  const open = (to: string) => {
    onFocus(release)
    navigate(to)
  }

  return (
    <div className="flex flex-col gap-4 border-t border-line pt-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-[11px] tracking-wide text-ink-4 uppercase">
            judged against
          </span>
          {choice ? (
            <>
              <Pill tone="ai">{MODE[choice.mode].short}</Pill>
              {/* The file types, repeated from the decisions screen on
                  purpose: the choice was made elsewhere, and a name on its own
                  does not say what it reads. Repeating three glyphs is cheaper
                  than sending somebody back to find out. */}
              {READS_FROM[choice.mode].map((source) => (
                <span
                  key={source.glyph}
                  title={source.label}
                  className="inline-flex rounded border border-line-strong px-1 py-0.5 font-mono text-[10px] text-ink-4"
                >
                  {source.glyph}
                </span>
              ))}
              {choice.adrRepositoryId && (
                <span className="font-mono text-xs text-ink-4">
                  + {choice.adrRepositoryId}
                </span>
              )}
            </>
          ) : (
            <Pill tone="warn">nothing chosen</Pill>
          )}
        </div>

        <Button
          variant={run ? undefined : 'primary'}
          size="sm"
          disabled={!isRecovered || !choice || isValidating}
          onClick={onValidate}
        >
          {isValidating
            ? 'Validating…'
            : run
              ? `Validate ${release} again`
              : `Validate ${release}`}
        </Button>
      </div>

      {!choice && isRecovered && (
        <p className="max-w-prose text-xs leading-relaxed text-ink-4">
          {/* Refused rather than defaulted: a mode picked by a constant is not
              a decision anybody made, and the release would be reported as
              judged against a source nobody chose. */}
          Nothing has been chosen for this release. Pick a source on the
          decisions screen before it can be validated.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {RESULTS.filter((result) => run || !result.needsRun).map((result) => (
          <Button key={result.to} size="sm" onClick={() => open(result.to)}>
            {result.label}
          </Button>
        ))}
        <span className="font-mono text-xs text-ink-4">for {release}</span>
      </div>
    </div>
  )
}
