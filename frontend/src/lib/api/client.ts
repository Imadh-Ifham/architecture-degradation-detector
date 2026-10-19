/**
 * HTTP client.
 *
 * Description:
 *   The one place in the application that knows a URL, a method or a status
 *   code. Everything else calls a named function and receives a typed shape.
 *
 *   Every request takes an `AbortSignal` so a component that unmounts stops
 *   its own work. Nothing here retries: a retry hides a backend that is down
 *   behind a screen that looks slow.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

/** A request the backend refused, carrying the detail it refused with. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }

  /** Whether the backend said the input is unusable rather than wrong. */
  get isConflict(): boolean {
    return this.status === 409
  }
}

export interface RequestOptions {
  signal?: AbortSignal
  query?: Record<string, string | number | boolean | undefined>
}

export async function get<T>(path: string, options: RequestOptions = {}) {
  return send<T>(path, { method: 'GET' }, options)
}

export async function post<T>(
  path: string,
  body?: unknown,
  options: RequestOptions = {},
) {
  return send<T>(
    path,
    {
      method: 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
    options,
  )
}

export async function remove<T = void>(path: string, options: RequestOptions = {}) {
  return send<T>(path, { method: 'DELETE' }, options)
}

async function send<T>(
  path: string,
  init: RequestInit,
  { signal, query }: RequestOptions,
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}${search(query)}`, { ...init, signal })

  if (!response.ok) {
    throw new ApiError(response.status, await describeFailure(response))
  }

  // 204 carries no body, and asking for one throws.
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

function search(query: RequestOptions['query']): string {
  if (!query) return ''

  const parameters = new URLSearchParams()

  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') {
      parameters.set(key, String(value))
    }
  }

  const rendered = parameters.toString()
  return rendered ? `?${rendered}` : ''
}

/**
 * The backend's own explanation, preferred over a status code.
 *
 * It says things a screen cannot work out for itself - which branch does not
 * exist, which release was never ingested - and those sentences are the whole
 * reason a 409 is useful rather than annoying.
 */
async function describeFailure(response: Response): Promise<string> {
  try {
    const body = await response.json()

    if (typeof body?.detail === 'string') {
      return body.detail
    }

    // Validation errors arrive as a list of {msg, loc} entries.
    if (Array.isArray(body?.detail)) {
      const messages = body.detail
        .map((entry: { msg?: string }) => entry?.msg)
        .filter((message: unknown): message is string => Boolean(message))

      if (messages.length > 0) {
        return messages.join('; ')
      }
    }
  } catch {
    // Not a JSON body; fall through to the status.
  }

  return `Request failed with status ${response.status}`
}

/** Whether a rejected promise is an aborted request rather than a failure. */
export function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === 'AbortError'
}

/** One error message, from anything that can be thrown. */
export function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause)
}
