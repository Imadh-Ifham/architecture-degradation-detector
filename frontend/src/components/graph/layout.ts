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
 *   **Cycles are ranked by dropping the edge that closes them.** Ranking by
 *   plain relaxation does not settle on a cycle - each pass pushes the members
 *   one column further, so a two-node cycle lands fourteen columns out and
 *   every node is drawn outside the viewBox. A real repository produces cycles
 *   routinely (`a` calls `b` while `b` reports to `a`), so the graph is made
 *   acyclic by ignoring back edges found in a depth-first walk and then ranked
 *   by longest path. The column count then follows the longest genuine chain
 *   rather than the size of the graph.
 *
 *   **Every element is drawn.** Elements with no dependencies are laid out in
 *   their own band under the graph rather than dropped: a service nothing
 *   points at is usually the interesting one, and a canvas that draws seven of
 *   fourteen elements while the page counts fourteen is a canvas that lies
 *   about what it is showing.
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

/** Vertical space between the graph and the band of unattached elements. */
const BAND_GAP = 56

/** How many unattached elements sit side by side before the band wraps. */
const BAND_COLUMNS = 4

export function layeredLayout(
  ids: string[],
  edges: { source_id: string; target_id: string }[],
): LayoutResult {
  const present = new Set(ids)
  const real = edges.filter(
    (edge) => present.has(edge.source_id) && present.has(edge.target_id),
  )

  const rank = ranksFor(ids, real)

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

  // The width follows the highest column index, not how many columns there
  // are. A graph ranked 0..12 has thirteen columns; a graph whose ranks start
  // at 12 has one column and is drawn thirteen columns out. Computing the
  // width from the count put every node outside the viewBox, which is a blank
  // drawing under a heading that says fourteen elements.
  const columnCount = columns.size === 0 ? 0 : Math.max(...columns.keys()) + 1
  const tallest = Math.max(1, ...[...columns.values()].map((column) => column.length))
  const graphHeight = tallest * NODE_HEIGHT + (tallest - 1) * ROW_GAP

  const perRow = Math.max(
    1,
    Math.min(BAND_COLUMNS, columnCount > 0 ? columnCount : BAND_COLUMNS),
  )
  const rows = Math.ceil(isolated.length / perRow)
  const bandHeight = isolated.length
    ? BAND_GAP + rows * NODE_HEIGHT + (rows - 1) * ROW_GAP
    : 0

  const nodes = new Map<string, LayoutNode>()

  for (const [column, members] of [...columns.entries()].sort((a, b) => a[0] - b[0])) {
    const ordered = [...members].sort()
    const span = ordered.length * NODE_HEIGHT + (ordered.length - 1) * ROW_GAP
    const top = PADDING + (graphHeight - span) / 2

    ordered.forEach((id, index) => {
      nodes.set(id, {
        id,
        rank: column,
        x: PADDING + column * (NODE_WIDTH + COLUMN_GAP),
        y: top + index * (NODE_HEIGHT + ROW_GAP),
      })
    })
  }

  const inRow = Math.min(perRow, Math.max(isolated.length, 1))
  const rowWidth = inRow * NODE_WIDTH + (inRow - 1) * COLUMN_GAP
  const bandTop = PADDING + graphHeight + BAND_GAP

  isolated.forEach((id, index) => {
    const row = Math.floor(index / perRow)
    const column = index % perRow
    const inThisRow = Math.min(perRow, isolated.length - row * perRow)
    const thisRowWidth =
      inThisRow * NODE_WIDTH + (inThisRow - 1) * COLUMN_GAP
    const offset = (rowWidth - thisRowWidth) / 2

    nodes.set(id, {
      id,
      // Not ranked: nothing in the graph connects it, which is exactly what
      // the band it sits in exists to say.
      rank: -1,
      x: PADDING + offset + column * (NODE_WIDTH + COLUMN_GAP),
      y: bandTop + row * (NODE_HEIGHT + ROW_GAP),
    })
  })

  const width = Math.max(
    PADDING * 2 + columnCount * NODE_WIDTH + (columnCount - 1) * COLUMN_GAP,
    isolated.length ? PADDING * 2 + rowWidth : 0,
    PADDING * 2 + NODE_WIDTH,
  )
  const height = PADDING * 2 + graphHeight + bandHeight

  return { nodes, isolated, width, height }
}

/**
 * The column each element belongs in: the longest path that reaches it.
 *
 * Back edges are dropped before ranking, so a cycle contributes one edge fewer
 * rather than an unbounded chain. What remains is acyclic, and a single
 * longest-path pass in topological order is exact for it.
 */
function ranksFor(
  ids: string[],
  edges: { source_id: string; target_id: string }[],
): Map<string, number> {
  const successors = new Map<string, string[]>(ids.map((id) => [id, []]))
  for (const edge of edges) {
    successors.get(edge.source_id)?.push(edge.target_id)
  }

  // Iterative depth-first: a repository can nest deeper than the call stack is
  // happy with, and the order has to be identical on every run.
  const onStack = new Set<string>()
  const seen = new Set<string>()
  const finished: string[] = []
  const forward = new Map<string, string[]>(ids.map((id) => [id, []]))

  for (const start of ids) {
    if (seen.has(start)) continue

    seen.add(start)
    onStack.add(start)

    const stack: { id: string; next: number }[] = [{ id: start, next: 0 }]

    while (stack.length > 0) {
      const frame = stack[stack.length - 1]
      const children = successors.get(frame.id) ?? []

      if (frame.next < children.length) {
        const target = children[frame.next]
        frame.next += 1

        // An edge back into a node still on the stack closes a cycle. It is
        // drawn, and it does not rank: rank is what makes the drawing
        // readable, and a cycle has no longest path to speak of.
        if (onStack.has(target)) continue

        forward.get(frame.id)?.push(target)

        if (!seen.has(target)) {
          seen.add(target)
          onStack.add(target)
          stack.push({ id: target, next: 0 })
        }
      } else {
        onStack.delete(frame.id)
        finished.push(frame.id)
        stack.pop()
      }
    }
  }

  const rank = new Map<string, number>(ids.map((id) => [id, 0]))

  // Reverse finishing order is a topological order of the acyclic remainder,
  // so one forward pass settles every longest path.
  for (let index = finished.length - 1; index >= 0; index -= 1) {
    const id = finished[index]
    const value = rank.get(id) ?? 0

    for (const target of forward.get(id) ?? []) {
      if (value + 1 > (rank.get(target) ?? 0)) {
        rank.set(target, value + 1)
      }
    }
  }

  return rank
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
