/**
 * The words the drift screens use.
 *
 * Description:
 *   The backend speaks in identifiers - `HubLikeElement`, `SERIES_TOO_SHORT`,
 *   `fan_in_norm` - which are right for a contract and wrong for a screen.
 *   This is the one place they are turned into a person's words, so the
 *   graph, the table and the charts say the same thing about the same
 *   finding.
 *
 *   Anything not listed here is shown as the backend named it rather than
 *   dropped: a detector added later should appear with an ugly name, not
 *   vanish.
 */

import type { GateStatus, Transition } from '../../lib/api'

export interface AntiPatternWords {
  /** A few characters, for a badge on a box that is 208 pixels wide. */
  short: string
  name: string
  /** What it is, in one sentence somebody could repeat in a review. */
  means: string
}

export const ANTI_PATTERN: Record<string, AntiPatternWords> = {
  CyclicDependency: {
    short: 'Cyc',
    name: 'Cyclic dependency',
    means: 'Elements that depend on each other in a loop, so none can change or be released alone.',
  },
  HubLikeElement: {
    short: 'Hub',
    name: 'Hub-like element',
    means: 'An element far more connected than the rest of this release, in both directions.',
  },
  UnstableDependency: {
    short: 'Uns',
    name: 'Unstable dependency',
    means: 'An element that depends on elements less stable than itself.',
  },
  OversizedElement: {
    short: 'Big',
    name: 'Oversized element',
    means: 'An element much larger than the others in the same release.',
  },
  BigBallOfMud: {
    short: 'Mud',
    name: 'Big ball of mud',
    means: 'Much of the system is one tangle with no modular structure left.',
  },
  SharedPersistence: {
    short: 'DB',
    name: 'Shared persistence',
    means: 'Two or more services reading or writing the same datastore.',
  },
}

export function antiPattern(type: string): AntiPatternWords {
  return ANTI_PATTERN[type] ?? { short: type.slice(0, 3), name: type, means: '' }
}

/** Metrics, as a person reads them. The unit stays beside the value. */
const METRIC: Record<string, string> = {
  fan_in: 'fan-in',
  fan_out: 'fan-out',
  fan_in_norm: 'fan-in (share)',
  fan_out_norm: 'fan-out (share)',
  instability: 'instability',
  size: 'size',
  size_rz: 'size (robust z)',
  scc_size: 'size of its cycle',
  unstable_dep_ratio: 'unstable dependencies (share)',
  modularity: 'modularity',
  scc_count: 'cycles',
  largest_scc_size: 'largest cycle',
  largest_scc_share: 'largest cycle (share)',
  cyclic_edge_count: 'edges in cycles',
  ap_involvement_share: 'elements in an anti-pattern (share)',
  services_per_store: 'services per datastore',
  degree: 'connections',
  member_count: 'members',
  internal_edge_count: 'edges inside it',
  bad_edge_count: 'unstable edges',
  'c1.lcom': 'lack of cohesion',
}

export function metricName(metric: string): string {
  if (metric.startsWith('ap_count.')) {
    return `${antiPattern(metric.slice('ap_count.'.length)).name} instances`
  }
  return METRIC[metric] ?? metric.replace(/_/g, ' ')
}

/** Why a series was not tested. Every one is reported; none is dropped. */
export function untestedReason(reason: string, minimum: number): string {
  return (
    {
      SERIES_TOO_SHORT: `fewer than ${minimum} releases with a value`,
      NO_WORSENING_DIRECTION: 'has no worse direction; it only supports a detector',
      TREND_ON_ENDED_INSTANCE: 'the instance is gone by the last release',
      CANDIDATE_INSTANCE_AMBIGUOUS: 'two instances of one type could be meant',
    }[reason] ?? reason.replace(/_/g, ' ').toLowerCase()
  )
}

export const GATE: Record<GateStatus, { tone: 'ok' | 'warn' | 'bad'; label: string }> = {
  ACCEPTED: { tone: 'ok', label: 'accepted' },
  DOWNWEIGHTED: { tone: 'warn', label: 'low confidence' },
  EXCLUDED: { tone: 'bad', label: 'excluded' },
}

export const TRANSITION: Record<Transition, string> = {
  INTRODUCED: 'new in this release',
  GREW: 'grew',
  SHRANK: 'shrank',
  PERSISTED: 'unchanged',
}

/** A number for a table: short, and never `NaN` for a gap. */
export function figure(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(digits)
}
