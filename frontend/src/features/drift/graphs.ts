/**
 * Each release of a detection run, as something drawable.
 *
 * Description:
 *   The same reduction the canvas does for one release - nodes and edges with
 *   a tone and a line style - done for a run of several, so the drawing stays
 *   the one `GraphCanvas` every graph on this application uses.
 *
 *   **One set of positions for every release.** Each release is drawn on the
 *   layout of the union of all of them, keyed by the element's identity
 *   across releases rather than its id in one. Stepping from one release to
 *   the next then moves nothing that stayed: what appears is new, what fades
 *   is gone, and the eye follows the change instead of re-reading the
 *   picture. A layout per release would redraw the system every step and
 *   make two releases of it look like two systems.
 *
 *   **Identity is the lineage, not the id.** Tracking links an element to its
 *   predecessor across renames, so a renamed service keeps its place. An
 *   element is keyed by the first id its lineage had; one that leaves and
 *   comes back under the same id falls back on that id, which is the same
 *   place.
 */

import type { GraphEdge, GraphNode } from '../../components/graph/GraphCanvas'
import type { AntiPatternInstance, DegradationReport, DriftRelease } from '../../lib/api'
import { antiPattern } from './labels'

/** Where every element of every release sits: the stable key for each. */
export interface RunLayout {
  ids: string[]
  edges: { source: string; target: string }[]
  /** `release::element` -> the key that element is drawn at. */
  keyOf: (releaseId: string, elementId: string) => string
}

export function runLayout(report: DegradationReport): RunLayout {
  const firstOf = new Map(
    report.lineages.map((lineage) => [lineage.lineage_id, lineage.members[0]?.element_id]),
  )
  const keys = new Map<string, string>()

  for (const release of report.releases) {
    for (const element of release.elements) {
      const root = element.lineage_id ? firstOf.get(element.lineage_id) : undefined
      keys.set(`${release.release_id}::${element.id}`, root ?? element.id)
    }
  }

  const keyOf = (releaseId: string, elementId: string) =>
    keys.get(`${releaseId}::${elementId}`) ?? elementId

  const ids = new Set<string>()
  const edges = new Map<string, { source: string; target: string }>()

  for (const release of report.releases) {
    for (const element of release.elements) ids.add(keyOf(release.release_id, element.id))

    for (const edge of release.dependencies) {
      const source = keyOf(release.release_id, edge.source)
      const target = keyOf(release.release_id, edge.target)
      edges.set(`${source}->${target}`, { source, target })
    }
  }

  const sorted = [...ids].sort()
  return { ids: sorted, edges: withoutBackEdges(sorted, [...edges.values()]), keyOf }
}

/**
 * The edges positions are computed from: every edge except those closing a cycle.
 *
 * The layout ranks an element by the longest path into it, and a cycle has no
 * longest path - its members climb until the layout gives up, which on a
 * union of ten releases with a cycle in each pushes them off the right of the
 * drawing. Dropping the edge that closes each cycle (a depth-first back edge,
 * found in a fixed order so the layout is the same on every load) gives a
 * layering; every edge, cyclic ones included, is still drawn.
 */
function withoutBackEdges(
  ids: string[],
  edges: { source: string; target: string }[],
): { source: string; target: string }[] {
  const out = new Map<string, string[]>()
  for (const edge of edges) out.set(edge.source, [...(out.get(edge.source) ?? []), edge.target])
  for (const targets of out.values()) targets.sort()

  const state = new Map<string, 'open' | 'done'>()
  const back = new Set<string>()

  const visit = (id: string) => {
    state.set(id, 'open')
    for (const target of out.get(id) ?? []) {
      const seen = state.get(target)
      if (seen === 'open') back.add(`${id}->${target}`)
      else if (!seen) visit(target)
    }
    state.set(id, 'done')
  }

  // Elements nothing points at go first, so a cycle is cut where it is
  // entered rather than wherever the alphabet happens to start.
  const pointedAt = new Set(edges.map((edge) => edge.target))
  for (const id of [...ids.filter((id) => !pointedAt.has(id)), ...ids]) {
    if (!state.has(id)) visit(id)
  }

  return edges.filter((edge) => !back.has(`${edge.source}->${edge.target}`))
}

/** Which anti-patterns each element of a release takes part in. */
export function membership(release: DriftRelease): Map<string, AntiPatternInstance[]> {
  const found = new Map<string, AntiPatternInstance[]>()

  for (const instance of release.instances) {
    for (const member of instance.members) {
      found.set(member, [...(found.get(member) ?? []), instance])
    }
  }

  return found
}

/** The anti-patterns on one box, in as few characters as a badge has. */
export function badgeOf(instances: AntiPatternInstance[] | undefined): string | undefined {
  if (!instances?.length) return undefined

  const types = [...new Set(instances.map((instance) => antiPattern(instance.anti_pattern_type).short))]
  return types.length > 2 ? `${types.slice(0, 2).join('·')} +${types.length - 2}` : types.join('·')
}

/** Whether an edge runs inside one cycle, which is what makes it part of the problem. */
export function cyclicEdges(release: DriftRelease): Set<string> {
  const inside = new Set<string>()

  for (const instance of release.instances) {
    if (instance.anti_pattern_type !== 'CyclicDependency') continue
    const members = new Set(instance.members)

    for (const edge of release.dependencies) {
      if (members.has(edge.source) && members.has(edge.target)) {
        inside.add(`${edge.source}->${edge.target}`)
      }
    }
  }

  return inside
}

export interface ReleaseDrawing {
  nodes: GraphNode[]
  edges: GraphEdge[]
  /** Drawn key -> the element's id in this release, for selecting it. */
  elementAt: Map<string, string>
  added: number
  removed: number
}

/**
 * One release on the run's layout.
 *
 * `previous` turns on the comparison: what is new since it is drawn in the
 * model colour, and what it had that this release does not is drawn as a
 * ghost. `focus` narrows the picture to one instance - its members stay
 * lit and everything else steps back.
 */
export function releaseGraph(
  release: DriftRelease,
  layout: RunLayout,
  {
    previous,
    focus,
  }: { previous?: DriftRelease | null; focus?: AntiPatternInstance | null } = {},
): ReleaseDrawing {
  const key = (elementId: string) => layout.keyOf(release.release_id, elementId)
  const keyBefore = (elementId: string) =>
    previous ? layout.keyOf(previous.release_id, elementId) : elementId

  const members = membership(release)
  const inCycle = cyclicEdges(release)
  const focused = new Set(focus?.members ?? [])

  const before = new Set(previous?.elements.map((element) => keyBefore(element.id)) ?? [])
  const edgesBefore = new Set(
    previous?.dependencies.map((edge) => `${keyBefore(edge.source)}->${keyBefore(edge.target)}`) ?? [],
  )

  const present = new Set(release.elements.map((element) => key(element.id)))
  const elementAt = new Map(release.elements.map((element) => [key(element.id), element.id]))

  let added = 0

  const nodes: GraphNode[] = release.elements.map((element) => {
    const isNew = Boolean(previous) && !before.has(key(element.id))
    if (isNew) added += 1

    const involved = members.get(element.id)
    const tone: GraphNode['tone'] = focus
      ? focused.has(element.id)
        ? 'bad'
        : 'faint'
      : involved
        ? 'bad'
        : isNew
          ? 'ai'
          : 'neutral'

    return {
      id: key(element.id),
      title: element.name,
      subtitle: isNew ? `${element.kind} · new` : element.kind,
      badge: badgeOf(involved),
      tone,
    }
  })

  const ghosts: GraphNode[] = (previous?.elements ?? [])
    .filter((element) => !present.has(keyBefore(element.id)))
    .map((element) => ({
      id: keyBefore(element.id),
      title: element.name,
      subtitle: `${element.kind} · gone`,
      tone: 'faint',
      ghost: true,
    }))

  const edges: GraphEdge[] = release.dependencies.map((edge) => {
    const id = `${key(edge.source)}->${key(edge.target)}`
    const cyclic = inCycle.has(`${edge.source}->${edge.target}`)
    const isNew = Boolean(previous) && !edgesBefore.has(id)
    const lit = !focus || (focused.has(edge.source) && focused.has(edge.target))

    return {
      id,
      source: key(edge.source),
      target: key(edge.target),
      tone: !lit ? 'faint' : cyclic ? 'bad' : isNew ? 'ai' : 'neutral',
      emphasis: lit && (cyclic || isNew),
      label: edge.types[0],
    } satisfies GraphEdge
  })

  const drawn = new Set(edges.map((edge) => edge.id))
  const goneEdges: GraphEdge[] = (previous?.dependencies ?? [])
    .map((edge) => ({ source: keyBefore(edge.source), target: keyBefore(edge.target) }))
    .filter((edge) => !drawn.has(`${edge.source}->${edge.target}`))
    .map((edge) => ({
      id: `gone:${edge.source}->${edge.target}`,
      source: edge.source,
      target: edge.target,
      tone: 'faint',
      dashed: true,
    }))

  return {
    nodes: [...nodes, ...ghosts],
    edges: [...edges, ...goneEdges],
    elementAt,
    added,
    removed: ghosts.length,
  }
}
