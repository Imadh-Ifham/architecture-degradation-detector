/**
 * Where each element is drawn.
 *
 * Description:
 *   A deterministic layered layout: rank by the longest path from anything
 *   with nothing pointing at it, order alphabetically inside a rank, and
 *   place by `(rank, index)`.
 *
 *   **A force-directed layout is the obvious choice and the wrong one.** It
 *   settles differently on every load, so one release looks like two
 *   different systems and two releases look unrelated - which destroys the
 *   only thing this diagram is for. Here the positions are a function of the
 *   graph, so the same release draws identically every time and a screenshot
 *   in a document matches what is on the screen.
 *
 *   Elements with no dependencies are not dropped. A service nothing points
 *   at is usually the interesting one, and deleting it from the picture
 *   deletes the observation.
 */

export interface LayoutNode {
  id: string
  x: number
  y: number
  rank: number
}

export interface LayoutResult {
  nodes: Map<string, LayoutNode>
  isolated: string[]
  width: number
  height: number
}

export const NODE_WIDTH = 208
export const NODE_HEIGHT = 56
const COLUMN_GAP = 108
const ROW_GAP = 34
const PADDING = 40

export function layeredLayout(
  ids: string[],
  edges: { source_id: string; target_id: string }[],
): LayoutResult {
  const present = new Set(ids)
  const real = edges.filter(
    (edge) => present.has(edge.source_id) && present.has(edge.target_id),
  )

  const rank = new Map<string, number>(ids.map((id) => [id, 0]))

  // Relax once per node: enough for any acyclic graph, and it terminates on a
  // cyclic one instead of looping, which a real repository can produce.
  for (let pass = 0; pass < ids.length; pass += 1) {
    let moved = false

    for (const edge of real) {
      const next = (rank.get(edge.source_id) ?? 0) + 1

      if (next > (rank.get(edge.target_id) ?? 0) && next < ids.length) {
        rank.set(edge.target_id, next)
        moved = true
      }
    }

    if (!moved) break
  }

  const connected = new Set<string>()
  for (const edge of real) {
    connected.add(edge.source_id)
    connected.add(edge.target_id)
  }

  const isolated = ids.filter((id) => !connected.has(id)).sort()
  const columns = new Map<number, string[]>()

  for (const id of ids) {
    if (!connected.has(id)) continue

    const column = rank.get(id) ?? 0
    columns.set(column, [...(columns.get(column) ?? []), id])
  }

  const tallest = Math.max(1, ...[...columns.values()].map((column) => column.length))
  const height = PADDING * 2 + tallest * NODE_HEIGHT + (tallest - 1) * ROW_GAP
  const nodes = new Map<string, LayoutNode>()

  for (const [column, members] of [...columns.entries()].sort((a, b) => a[0] - b[0])) {
    const ordered = [...members].sort()
    const span = ordered.length * NODE_HEIGHT + (ordered.length - 1) * ROW_GAP
    const top = (height - span) / 2

    ordered.forEach((id, index) => {
      nodes.set(id, {
        id,
        rank: column,
        x: PADDING + column * (NODE_WIDTH + COLUMN_GAP),
        y: top + index * (NODE_HEIGHT + ROW_GAP),
      })
    })
  }

  const columnCount = Math.max(1, columns.size)
  const width =
    PADDING * 2 + columnCount * NODE_WIDTH + (columnCount - 1) * COLUMN_GAP

  return { nodes, isolated, width, height }
}

/** The curve from one element's right edge to another's left edge. */
export function edgePath(from: LayoutNode, to: LayoutNode): string {
  const x1 = from.x + NODE_WIDTH
  const y1 = from.y + NODE_HEIGHT / 2
  const x2 = to.x
  const y2 = to.y + NODE_HEIGHT / 2
  const bend = Math.max(36, (x2 - x1) * 0.45)

  return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`
}
