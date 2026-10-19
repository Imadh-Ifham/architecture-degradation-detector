/**
 * Server endpoints.
 *
 * Description:
 *   The root endpoint, which is how the application knows the backend is
 *   reachable and which environment it is talking to.
 */

import { get, type RequestOptions } from './client'

export interface ServerStatus {
  message: string
  environment: string
}

export function fetchServerStatus(options?: RequestOptions) {
  return get<ServerStatus>('/', options)
}
