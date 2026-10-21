/**
 * The four parts a severity score is made of, and the words the screen uses.
 *
 * Description:
 *   Everything a first-time reader needs to read a ranking is decided here:
 *   what each part asks, what a degradation type means in plain words, why a
 *   row ranks where it does, and how a run is named. Every sentence is built
 *   from numbers already in the report; nothing is invented.
 *
 *   The part colours are categories (`dim-*` tokens), never the signal
 *   colours: a part is not a state, and green or red would read as good or bad.
 */

import type {
  DataProvenance,
  Dimension,
  ScoringRunSummary,
  SeverityRecord,
  SeverityReportV1,
} from '../../lib/api'

export interface DimensionInfo {
  key: Dimension
  label: string
  question: string
  /** Background class of the part's colour (a `dim-*` token). */
  fill: string
}

export const DIMENSIONS: readonly DimensionInfo[] = [
  {
    key: 'blast_radius',
    label: 'Blast radius',
    question: 'How much of the system depends on it?',
    fill: 'bg-dim-reach',
  },
  {
    key: 'hotspot',
    label: 'Hotspot',
    question: 'How actively, by how many people and how often to fix bugs, is that code changing?',
    fill: 'bg-dim-churn',
  },
  {
    key: 'adr_violation',
    label: 'Decision violation',
    question: 'Does it break a recorded architecture decision?',
    fill: 'bg-dim-decision',
  },
  {
    key: 'persistence',
    label: 'Persistence',
    question: 'How many releases has it stayed, and how fast is it growing?',
    fill: 'bg-dim-age',
  },
]

/** Whether a part took part in this record's score. Off is not zero. */
export function isActive(record: SeverityRecord, key: Dimension): boolean {
  return record.dimensions[key]?.active !== false
}

/** The weight each part carried in this run (the same on every record). */
export function weightsOf(report: SeverityReportV1): Partial<Record<Dimension, number>> {
  const first = report.records?.[0]
  const weights: Partial<Record<Dimension, number>> = {}
  for (const { key } of DIMENSIONS) {
    if (report.active_dimensions.includes(key)) {
      weights[key] = first?.dimensions[key]?.weight ?? 0
    }
  }
  return weights
}

const TYPE_NAMES: Record<string, string> = {
  CyclicDependency: 'Dependency cycle — these parts depend on each other in a loop',
  HubLikeElement: 'Hub — too many other parts depend on it',
  UnstableDependency: 'Depends on parts that change more often than it does',
  OversizedElement: 'Grown too large',
  SharedPersistence: 'Shared database — several parts write the same data',
  InappropriateIntimacy: 'Too tightly coupled — the parts reach into each other',
  MetricDrift: 'A structural measure keeps getting worse',
  BigBallOfMud: 'Whole-system tangle',
}

/** A degradation type in plain words; unknown types are split into words. */
export function plainType(type: string): string {
  return TYPE_NAMES[type] ?? type.replace(/([a-z])([A-Z])/g, '$1 $2')
}

/** Why this row ranks where it does, from its own contributions. */
export function reason(record: SeverityRecord): string {
  const parts = DIMENSIONS.filter((d) => isActive(record, d.key))
    .map((d) => ({ label: d.label, share: record.contributions[d.key] ?? 0 }))
    .filter((p) => p.share > 0)
    .sort((a, b) => b.share - a.share)

  let sentence: string
  if (parts.length === 0) {
    sentence = 'Scores zero on every part in use'
  } else if (parts[0].share >= 0.6) {
    sentence = `Mostly ${parts[0].label.toLowerCase()} (${percent(parts[0].share)})`
  } else {
    sentence = parts
      .slice(0, 2)
      .map((p) => `${p.label.toLowerCase()} ${percent(p.share)}`)
      .join(' + ')
    sentence = sentence.charAt(0).toUpperCase() + sentence.slice(1)
  }

  const extras: string[] = []
  const decision = record.dimensions.adr_violation
  if (decision && decision.active !== false && decision.normalized > 0) {
    extras.push('breaks a recorded decision')
  }
  if (record.context_tag === 'UNCERTAIN') extras.push('detection marked it uncertain')
  return [sentence, ...extras].join(' · ')
}

export type Level = 'high' | 'medium' | 'low'

/** Position in this list, in thirds: a relative word, not a threshold. */
export function levelOf(rank: number, total: number): Level {
  if (total <= 0) return 'low'
  const position = (rank - 1) / total
  if (position < 1 / 3) return 'high'
  if (position < 2 / 3) return 'medium'
  return 'low'
}

/** Severity as a 0-100 score, for reading; the 0-1 value stays beside it. */
export function score(severity: number): number {
  return Math.round(severity * 100)
}

/** What the page must say about where the numbers came from. */
export function provenanceNote(provenance: DataProvenance): string | null {
  if (provenance === 'live') {
    return 'Ranked from this repository’s own pipeline output and commit history. A ranking orders what detection found for attention; it is not a confirmed finding until a developer reviews it.'
  }
  if (provenance === 'fixture-events+live-history') {
    return 'The degradation events and the architecture graph here are hand-made; only the commit history is real. The ranking shows how scoring works, not findings about this system.'
  }
  return 'The degradation events here come from a synthetic or hand-made system. The ranking shows how scoring works, not findings about a real system.'
}

/**
 * One name per system. The workspace keys a repository by its url
 * (`microservices-demo-<12 hex>`); hand-made inputs name it (`online-boutique`).
 * The hash is dropped and the known repository names are mapped to one name.
 */
const SYSTEM_ALIASES: Record<string, string> = { 'microservices-demo': 'online-boutique' }

export function systemKey(systemId: string): string {
  const bare = systemId.replace(/^c4-/, '').replace(/-[0-9a-f]{12}$/, '')
  return SYSTEM_ALIASES[bare] ?? bare
}

/** Whether a ranking belongs to the selected repository. */
export function sameSystem(systemId: string, repositoryKey: string): boolean {
  return Boolean(repositoryKey) && systemKey(systemId) === systemKey(repositoryKey)
}

/** A system id as a name: "online-boutique" -> "Online Boutique". */
export function systemName(systemId: string): string {
  const words = systemKey(systemId).split(/[-_]/).filter(Boolean)
  return words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

/** A run named in words: where its events came from, and what was switched on. */
export function runTitle(run: ScoringRunSummary): string {
  const name = systemName(run.system_id)
  const decisions = run.active_dimensions.includes('adr_violation')
    ? 'decision check on'
    : 'decision check off'
  if (run.data_provenance === 'live') return `${name}: detection run`
  if (run.data_provenance === 'fixture-events+live-history') {
    return `${name}: hand-made events, real history, ${decisions}`
  }
  return `${name}: designed test system, ${decisions}`
}

/** Release, events read, when it was made, and the id for whoever needs it. */
export function runMeta(run: ScoringRunSummary): string {
  const made = new Date(run.created_at).toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
  const events = `${run.counts.payloads} event${run.counts.payloads === 1 ? '' : 's'}`
  return `${run.release_id} · ${events} · ${made} · ${run.run_id}`
}

export function percent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`
}

/** A record's elements without a kind prefix ("svc:cart" -> "cart"), or its id. */
export function subject(record: SeverityRecord): string {
  const elements = (record.elements ?? []).map((id) => id.replace(/^[a-z]+:/, ''))
  return elements.length > 0 ? elements.join(' + ') : record.event_id
}
