/**
 * Validating the whole stack, while nobody is watching it.
 *
 * Description:
 *   A stack of twenty releases is started and then left. The two things the
 *   person who walked away needs on their return are **how far it got** and
 *   **what, if anything, refused** — and a spinner saying "validating v0.9.0"
 *   answers neither.
 *
 *   **The pause is shown rather than hidden.** Between releases that spent
 *   model calls the run waits a little over a minute, because the provider's
 *   token budget is per minute and shared across runs: three cold releases
 *   back to back drained it, and one call then waited a minute and gave up.
 *   A screen that went quiet for seventy seconds with no explanation reads as
 *   a hang, so the wait counts down and says why it exists.
 *
 *   **A release that replayed is not paused for.** It spent nothing, so there
 *   is nothing to wait for — which is what makes a second pass over a warm
 *   stack take seconds rather than twenty pauses.
 *
 *   **Failures do not stop the stack.** One release refused by a rate limit
 *   used to abandon the other nineteen. They are collected and listed at the
 *   end instead, because the useful answer is *these three need running
 *   again*, not *it stopped somewhere*.
 */

import { Card, Pill } from '../../components/ui'
import type { StackProgress } from '../../workspace/context'

export default function StackRun({ progress }: { progress: StackProgress }) {
  const finished = progress.done >= progress.total && !progress.release
  const percent = progress.total === 0 ? 0 : (progress.done / progress.total) * 100

  return (
    <Card
      title={finished ? 'Every release has been through' : 'Validating every release'}
      action={
        <span className="font-mono text-xs text-ink-4">
          {progress.done} of {progress.total}
        </span>
      }
    >
      <div className="flex flex-col gap-6">
        <span className="h-2 w-full overflow-hidden rounded-full bg-raised">
          <span
            className={`block h-full transition-[width] duration-500 ${
              progress.failures.length > 0 ? 'bg-warn' : 'bg-ok'
            }`}
            style={{ width: `${percent}%` }}
          />
        </span>

        <div className="flex flex-wrap items-center gap-4">
          {progress.release && (
            <>
              <Pill tone="ai">validating {progress.release}</Pill>
              <span className="text-xs leading-relaxed text-ink-4">
                A release not yet in the cache costs about four minutes; one
                already validated replays in seconds.
              </span>
            </>
          )}

          {progress.pausingFor > 0 && (
            <>
              <Pill tone="warn">waiting {progress.pausingFor}s</Pill>
              <span className="max-w-prose text-xs leading-relaxed text-ink-4">
                Letting the provider&rsquo;s per-minute token budget refill.
                It is shared across runs, so going straight on would make the
                next release queue and could cost a fact its second opinion.
                Only releases that actually spent calls are waited for.
              </span>
            </>
          )}

          {finished && progress.failures.length === 0 && (
            <Pill tone="ok">all {progress.total} validated</Pill>
          )}
        </div>

        {progress.failures.length > 0 && (
          <div className="flex flex-col gap-3">
            <span className="text-xs tracking-wide text-ink-4">
              {finished ? 'these refused — run them again' : 'refused so far'}
            </span>
            <ul className="flex flex-col gap-2">
              {progress.failures.map((failure) => (
                <li
                  key={failure.release}
                  className="flex flex-col gap-1 border-l-2 border-warn/60 pl-4"
                >
                  <span className="font-mono text-xs text-ink-2">{failure.release}</span>
                  <span className="max-w-prose text-xs leading-relaxed text-warn">
                    {failure.reason}
                  </span>
                </li>
              ))}
            </ul>
            <p className="max-w-prose text-xs leading-relaxed text-ink-4">
              The rest of the stack carried on. A release refused by a rate
              limit usually succeeds on a second attempt, when the budget has
              refilled.
            </p>
          </div>
        )}
      </div>
    </Card>
  )
}
