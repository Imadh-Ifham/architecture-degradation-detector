const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

export interface ServerStatus {
  message: string
  environment: string
}

export async function fetchServerStatus(
  signal?: AbortSignal,
): Promise<ServerStatus> {
  const response = await fetch(`${API_BASE_URL}/`, { signal })

  if (!response.ok) {
    throw new Error(
      `Backend responded with ${response.status} ${response.statusText}`,
    )
  }

  return (await response.json()) as ServerStatus
}
