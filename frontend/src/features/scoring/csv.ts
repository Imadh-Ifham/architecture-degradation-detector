/**
 * The ranking as CSV: one row per ranked event, every part's value, weight
 * and share, and the reason line - built from the saved report, so the file
 * says exactly what the screen says.
 */

import type { SeverityReportV1 } from '../../lib/api'
import { DIMENSIONS, isActive, plainType, reason, score, subject } from './dimensions'

/** One row per ranked event; a part that was off is left empty, never 0. */
export function rankingCsv(report: SeverityReportV1): string {
  const head = [
    'rank',
    'event_id',
    'what',
    'type',
    'score_0_100',
    'severity',
    ...DIMENSIONS.flatMap((d) => [`${d.key}_value`, `${d.key}_weight`, `${d.key}_share`]),
    'why',
  ]
  const rows = (report.records ?? []).map((record) => [
    record.rank,
    record.event_id,
    subject(record),
    plainType(record.anti_pattern_type),
    score(record.severity),
    record.severity.toFixed(6),
    ...DIMENSIONS.flatMap((d) =>
      isActive(record, d.key)
        ? [
            record.dimensions[d.key].normalized.toFixed(4),
            record.dimensions[d.key].weight.toFixed(4),
            (record.contributions[d.key] ?? 0).toFixed(4),
          ]
        : ['', '', ''],
    ),
    reason(record),
  ])
  return [head, ...rows].map((row) => row.map(cell).join(',')).join('\r\n') + '\r\n'
}

function cell(value: string | number): string {
  const text = String(value)
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}
