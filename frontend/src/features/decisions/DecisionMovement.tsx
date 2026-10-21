/**
 * What each release changed in the decision history.
 *
 * Description:
 *   The count beside a release answers *how many rules are in force*. Two
 *   releases reporting the same count is the question that number cannot
 *   answer: the same rules, or a different set of the same size? Without
 *   this panel the only honest reading of four releases all saying 84 is
 *   "either nothing changed or the scan is broken, and I cannot tell which".
 *
 *   **Everything here was already in the decision log.** The scan appends a
 *   marker per release carrying what it recorded and what it closed, and a
 *   supersession event naming the rule and why it was withdrawn. Nothing is
 *   recomputed from the working trees: a second derivation would be a second
 *   opinion about what happened, and the log is the one that was acted on.
 *
 *   A release that changed nothing says so in words rather than showing an
 *   empty row. "Stated the same rules as the log already held" is a finding
 *   about two releases of a system; a blank is a screen that gave up.
 */

import { Card, EmptyState, Pill, Spinner } from '../../components/ui'
import { readDecisionHistory, type ReleaseMovement } from '../../lib/api'
import { useRequest } from '../../lib/useRequest'

export default function DecisionMovement({
  repositoryKey,
}: {
  repositoryKey: string
}) {
  const history = useRequest(
    (options) => readDecisionHistory(repositoryKey, options),
    [repositoryKey],
    Boolean(repositoryKey),
  )

  const scans = history.data ?? []

  return (
    <Card
      title="What each release changed"
      action={
        <span className="font-mono text-xs text-ink-4">
          read from the decision log, in scan order
        </span>
      }
    >
      {history.isLoading && <Spinner label="replaying the decision log" />}

      {!history.isLoading && scans.length === 0 && (
        <EmptyState
          title="No release has been scanned yet"
          body={
            history.error ??
            'A release is scanned when it is validated. Once two have been, this shows what the second one changed about the first.'
          }
        />
      )}

      {scans.length > 0 && (
        <div className="flex flex-col gap-7">
          <p className="max-w-prose text-sm leading-relaxed text-ink-3">
            The number beside a release is how many rules were in force for it.
            Two releases with the same number are not necessarily the same
            rules — this is what actually moved.
          </p>

          <ol className="flex flex-col gap-px overflow-hidden rounded-control border border-line bg-line">
            {scans.map((scan, index) => (
              <Scan key={`${scan.release_id}-${index}`} scan={scan} />
            ))}
          </ol>
        </div>
      )}
    </Card>
  )
}

function Scan({ scan }: { scan: ReleaseMovement }) {
  const quiet = scan.recorded === 0 && scan.closed === 0

  return (
    <li className="flex flex-col gap-4 bg-panel px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <span className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-sm text-ink">{scan.release_id}</span>
          <span className="font-mono text-[11px] text-ink-4">
            {scan.sources.map((source) => source.replace(/_/g, ' ')).join(' · ')}
          </span>
        </span>

        <span className="flex flex-wrap items-center gap-2.5">
          {scan.recorded > 0 && (
            <Pill tone="ok">
              {scan.recorded} new rule{scan.recorded === 1 ? '' : 's'}
            </Pill>
          )}
          {scan.closed > 0 && (
            <Pill tone="warn">
              {scan.closed} withdrawn
            </Pill>
          )}
          {quiet && <Pill>nothing moved</Pill>}
        </span>
      </div>

      {quiet && (
        <p className="max-w-prose text-xs leading-relaxed text-ink-4">
          This release stated exactly the rules the log already held. That is a
          finding about the two releases rather than a gap in the scan — the
          sources ran and agreed with what was there.
        </p>
      )}

      {scan.withdrawn.length > 0 && (
        <ul className="flex flex-col gap-2">
          {scan.withdrawn.map((rule) => (
            <li
              key={rule.decision_id}
              className="flex flex-col gap-1 border-l-2 border-warn/60 pl-4"
            >
              <span className="font-mono text-xs text-ink-2">
                {rule.decision_id}
                <span className="px-2 text-ink-4">·</span>
                {rule.subject} {rule.constraint.replace(/_/g, ' ')} {rule.object}
              </span>
              {rule.reason && (
                <span className="text-xs leading-relaxed text-warn">
                  {rule.reason}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}
