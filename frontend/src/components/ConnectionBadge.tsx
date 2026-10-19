/**
 * Backend connection badge.
 *
 * Description:
 *   Calls the root endpoint and shows whether the backend answered, and which
 *   environment answered. It sits in the instrument bar rather than on a page
 *   because "is the server up" is a question somebody has while looking at
 *   something else.
 *
 *   A failure is clickable and retries. Nothing polls: a badge that re-asks
 *   every few seconds produces load nobody asked for and a flicker everybody
 *   sees.
 */

import { fetchServerStatus } from '../lib/api'
import { useRequest } from '../lib/useRequest'

export default function ConnectionBadge() {
  const { data, isLoading, error, reload } = useRequest(
    (options) => fetchServerStatus(options),
    [],
  )

  if (isLoading) {
    return <Badge tone="text-ink-3" dot="bg-ink-4" label="connecting" />
  }

  if (error) {
    return (
      <button type="button" onClick={reload} title={error}>
        <Badge tone="text-bad" dot="bg-bad" label="backend unreachable — retry" />
      </button>
    )
  }

  return <Badge tone="text-ink-2" dot="bg-ok" label={data?.environment ?? 'connected'} />
}

function Badge({ tone, dot, label }: { tone: string; dot: string; label: string }) {
  return (
    <span className={`flex items-center gap-2 font-mono text-xs ${tone}`}>
      <span className={`size-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  )
}
