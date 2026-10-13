/**
 * Backend status card.
 *
 * Author: Imadh Ifham
 * Date: 2026-10-13
 * Description:
 *   Calls the backend root endpoint and renders the returned message and
 *   environment, covering the loading, error and retry states.
 */

import { useCallback, useEffect, useState } from 'react'
import { fetchServerStatus, type ServerStatus } from '../lib/api'

type LoadState = 'loading' | 'success' | 'error'

/** One label/value row of the status table. */
function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-slate-800 py-3 last:border-b-0">
      <dt className="text-sm text-slate-400">{label}</dt>
      <dd className="font-mono text-sm text-slate-100">{value}</dd>
    </div>
  )
}

/** Fetch and display the backend root endpoint response. */
export default function BackendStatus() {
  const [state, setState] = useState<LoadState>('loading')
  const [status, setStatus] = useState<ServerStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    // State is only touched inside the promise callbacks, never
    // synchronously, so the effect does not trigger a cascading render.
    fetchServerStatus(controller.signal)
      .then((result) => {
        setStatus(result)
        setState('success')
      })
      .catch((cause: unknown) => {
        // An abort means the component unmounted; it is not a real failure.
        if (controller.signal.aborted) return

        setError(cause instanceof Error ? cause.message : String(cause))
        setState('error')
      })

    // Abort the in-flight request when the component unmounts.
    return () => controller.abort()
  }, [attempt])

  /** Return to the loading state and trigger a fresh request. */
  const retry = useCallback(() => {
    setState('loading')
    setError(null)
    setAttempt((current) => current + 1)
  }, [])

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight text-white">
          Backend Connection
        </h2>
        <p className="text-slate-400">
          Live response from the backend root endpoint.
        </p>
      </header>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6">
        {state === 'loading' && (
          <p className="text-sm text-slate-400">Loading backend status…</p>
        )}

        {state === 'error' && (
          <div className="space-y-4">
            <p className="text-sm text-red-400">
              Could not reach the backend: {error}
            </p>
            <button
              type="button"
              onClick={retry}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-200 transition hover:bg-slate-800"
            >
              Retry
            </button>
          </div>
        )}

        {state === 'success' && status && (
          <dl>
            <StatusRow label="Message" value={status.message} />
            <StatusRow label="Environment" value={status.environment} />
          </dl>
        )}
      </div>
    </section>
  )
}
