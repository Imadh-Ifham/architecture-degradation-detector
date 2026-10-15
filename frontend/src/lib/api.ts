const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export interface ServerStatus {
  message: string
  environment: string
}

export interface RepositorySource {
  url: string
  branch: string
}

export interface IngestedRepository {
  id: string
  url: string
  branch: string
  commit: string
  path: string
  ingested_at: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init)

  if (!response.ok) {
    throw new ApiError(response.status, await describeFailure(response))
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

async function describeFailure(response: Response): Promise<string> {
  try {
    const body = await response.json()

    if (typeof body?.detail === 'string') {
      return body.detail
    }

    // FastAPI validation errors arrive as a list of {msg, loc} entries.
    if (Array.isArray(body?.detail)) {
      const messages = body.detail
        .map((entry: { msg?: string }) => entry?.msg)
        .filter((message: unknown): message is string => Boolean(message))

      if (messages.length > 0) {
        return messages.join('; ')
      }
    }
  } catch {
    // Not a JSON body; fall through to the status text.
  }

  return `Request failed with status ${response.status}`
}

export function fetchServerStatus(signal?: AbortSignal): Promise<ServerStatus> {
  return request<ServerStatus>('/', { signal })
}

export function listRepositories(
  signal?: AbortSignal,
): Promise<IngestedRepository[]> {
  return request<IngestedRepository[]>('/repositories', { signal })
}

export function ingestRepository(
  source: RepositorySource,
  signal?: AbortSignal,
): Promise<IngestedRepository> {
  return request<IngestedRepository>('/repositories', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(source),
    signal,
  })
}

export function removeRepository(
  repositoryId: string,
  signal?: AbortSignal,
): Promise<void> {
  return request<void>(`/repositories/${encodeURIComponent(repositoryId)}`, {
    method: 'DELETE',
    signal,
  })
}
