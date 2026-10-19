/**
 * One request, with its loading, error and retry states.
 *
 * Description:
 *   Every screen that reads from the backend needs the same four things: the
 *   data, whether it is still coming, what went wrong, and a way to ask
 *   again. Writing that four times produces four slightly different answers
 *   to "what happens when it fails".
 *
 *   The request is aborted on unmount, and an abort is not an error: a
 *   component that navigated away has not failed at anything.
 */

import { useCallback, useEffect, useState } from 'react'
import { isAbort, messageOf, type RequestOptions } from './api'

export interface RequestState<T> {
  data: T | null
  isLoading: boolean
  error: string | null
  reload: () => void
}

export function useRequest<T>(
  send: (options: RequestOptions) => Promise<T>,
  dependencies: readonly unknown[] = [],
  enabled = true,
): RequestState<T> {
  const [data, setData] = useState<T | null>(null)
  const [isLoading, setIsLoading] = useState(enabled)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!enabled) {
      setIsLoading(false)
      return
    }

    const controller = new AbortController()
    setIsLoading(true)

    send({ signal: controller.signal })
      .then((result) => {
        setData(result)
        setError(null)
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || isAbort(cause)) return
        setError(messageOf(cause))
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })

    return () => controller.abort()
    // `send` is rebuilt on every render by design; the dependency list the
    // caller passes is what decides when the request is made again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, attempt, enabled])

  const reload = useCallback(() => setAttempt((current) => current + 1), [])

  return { data, isLoading, error, reload }
}
