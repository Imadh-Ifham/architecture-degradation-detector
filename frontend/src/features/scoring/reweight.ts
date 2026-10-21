/**
 * The ranking again, with other weights.
 *
 * Description:
 *   Fixed-reference TOPSIS needs nothing but each event's 0-1 value per part
 *   and the weights, and both are in the report: the ideal event is the
 *   weights themselves (value 1 everywhere), the anti-ideal is 0. So the
 *   screen can re-rank exactly as the backend does - with the saved weights it
 *   gives the saved scores to the last digit - and show what a different
 *   judgement of what matters would change. Nothing is saved.
 */

import type { Dimension, SeverityRecord } from '../../lib/api'

export interface Rescored {
  eventId: string
  rank: number
  severity: number
}

/** Weights scaled to sum to 1; all zero stays all zero. */
export function normalised(weights: Partial<Record<Dimension, number>>, active: Dimension[]) {
  const total = active.reduce((sum, key) => sum + (weights[key] ?? 0), 0)
  return Object.fromEntries(
    active.map((key) => [key, total > 0 ? (weights[key] ?? 0) / total : 0]),
  ) as Partial<Record<Dimension, number>>
}

/** S = d- / (d+ + d-), ranked by S descending, ties by event id (as the backend). */
export function rerank(
  records: SeverityRecord[],
  active: Dimension[],
  weights: Partial<Record<Dimension, number>>,
): Rescored[] {
  const scored = records.map((record) => {
    let plus = 0
    let minus = 0
    for (const key of active) {
      const w = weights[key] ?? 0
      const v = (record.dimensions[key]?.normalized ?? 0) * w
      plus += (v - w) ** 2
      minus += v ** 2
    }
    const total = Math.sqrt(plus) + Math.sqrt(minus)
    return { eventId: record.event_id, severity: total > 0 ? Math.sqrt(minus) / total : 0 }
  })
  scored.sort((a, b) => b.severity - a.severity || (a.eventId < b.eventId ? -1 : 1))
  return scored.map((item, index) => ({ ...item, rank: index + 1 }))
}
