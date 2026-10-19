/**
 * Turning each stored document into something drawable.
 *
 * Description:
 *   One function per graph the analysis produces. Each reduces a document to
 *   nodes and edges with a tone and a line style, and nothing else — so the
 *   drawing stays one component and the meaning of a line is decided once,
 *   here, where the document's own words are still in view.
 *
 *   When a later phase publishes its own graph, it gets a function beside
 *   these and a tab on the canvas screen. The drawing does not change.
 */

import type { GraphEdge, GraphNode } from '../../components/graph/GraphCanvas'
import type {
  ArchitectureSnapshot,
  PublishedGraph,
  ValidatedEdge,
  ValidationRollup,
} from '../../lib/api'

/** The architecture as recovery found it, before anything judged it. */
export function recoveredGraph(snapshot: ArchitectureSnapshot): {
  nodes: GraphNode[]
  edges: GraphEdge[]
} {
  const outgoing = new Map<string, number>()

  for (const edge of snapshot.relationships) {
    outgoing.set(edge.source_id, (outgoing.get(edge.source_id) ?? 0) + 1)
  }

  return {
    nodes: snapshot.elements.map((element) => ({
      id: element.id,
      title: element.name,
      subtitle: element.kind.replace(/_/g, ' '),
      badge: outgoing.get(element.id) ? `${outgoing.get(element.id)} →` : undefined,
    })),
    edges: snapshot.relationships.map((edge) => ({
      id: edge.id,
      source: edge.source_id,
      target: edge.target_id,
      // Source-level evidence is stronger than a line in a manifest, and the
      // drawing says so rather than treating every edge as equally certain.
      tone: edge.confirmed_by_source ? 'ok' : 'neutral',
      dashed: edge.kind === 'infrastructure_dependency',
      emphasis: edge.confirmed_by_source,
    })),
  }
}

/** The same architecture with the verdict drawn on the edge it is about. */
export function validatedGraph(document: PublishedGraph): {
  nodes: GraphNode[]
  edges: GraphEdge[]
} {
  return {
    nodes: document.nodes.map((node) => ({
      id: node.id,
      title: node.name,
      subtitle: node.kind.replace(/_/g, ' '),
      badge: rollup(node.validation_rollup),
      tone: node.validation_rollup?.contradicted ? 'bad' : 'neutral',
    })),
    edges: document.links.map((edge) => ({
      id: edge.fact_id,
      source: edge.source,
      target: edge.target,
      tone: verdictTone(edge.bucket),
      dashed: verdictTone(edge.bucket) === 'faint',
      emphasis: verdictTone(edge.bucket) !== 'ok',
      label: edge.confidence > 0 ? edge.confidence.toFixed(2).slice(1) : undefined,
    })),
  }
}

/** Which dependencies a model was involved in deciding, and which were not. */
export function provenanceGraph(document: PublishedGraph): {
  nodes: GraphNode[]
  edges: GraphEdge[]
} {
  return {
    nodes: document.nodes.map((node) => ({
      id: node.id,
      title: node.name,
      subtitle: node.kind.replace(/_/g, ' '),
    })),
    edges: document.links.map((edge) => ({
      id: edge.fact_id,
      source: edge.source,
      target: edge.target,
      tone: edge.model_calls > 0 ? 'ai' : 'neutral',
      dashed: edge.model_calls === 0,
      emphasis: edge.model_calls > 0,
      label: edge.model_calls > 0 ? `${edge.model_calls}` : undefined,
    })),
  }
}

function verdictTone(bucket: string): GraphEdge['tone'] {
  const value = bucket.toLowerCase()

  if (value.includes('contradict')) return 'bad'
  if (value.includes('review')) return 'warn'
  if (value.includes('uncovered')) return 'faint'
  if (value.includes('confirm')) return 'ok'
  return 'neutral'
}

/**
 * The verdicts about one element, in four characters.
 *
 * Optional because a node the document carries no rollup for is a real
 * state - an element nothing was judged about - and reading through it
 * would crash the whole drawing over one missing object.
 */
function rollup(counts: ValidationRollup | undefined): string | undefined {
  if (!counts) return undefined

  const parts: string[] = []

  if (counts.confirmed) parts.push(`${counts.confirmed}✓`)
  if (counts.needs_review) parts.push(`${counts.needs_review}?`)
  if (counts.contradicted) parts.push(`${counts.contradicted}✕`)

  return parts.length > 0 ? parts.join(' ') : undefined
}

/** Kept typed rather than inferred, because the drawing depends on it. */
export type { ValidatedEdge }
