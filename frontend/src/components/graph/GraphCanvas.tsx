/**
 * A graph, drawn.
 *
 * Description:
 *   One drawing used by every screen that shows a graph. It takes nodes and
 *   edges already reduced to what a picture needs — a title, a tone, a line
 *   style — and knows nothing about architectures, verdicts or releases.
 *
 *   **One drawing rather than one per screen.** The recovered architecture
 *   and the validated one are the same picture with different things written
 *   on the edges. Two implementations would drift, and the second one would
 *   be the one nobody checked.
 *
 *   **Line style carries the meaning, not colour alone.** Every tone also has
 *   a weight or a dash, and the legend spells the word out. A washed-out
 *   projector, a printed appendix and a colour-blind reader all have to work,
 *   and at least two of those happen.
 *
 *   **Positions can come from a larger graph than the one drawn.** A screen
 *   stepping through releases passes the union of every release as `layout`,
 *   so an element sits in the same place in each and the step reads as the
 *   system changing rather than the picture being redrawn. Without it, the
 *   layout is the drawn graph's own, as before.
 *
 *   Hovering a node dims everything it does not touch. With fifteen edges
 *   that is a convenience; at fifty it is the only way the picture is
 *   readable, and it costs one class.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { NODE_HEIGHT, NODE_WIDTH, edgePath, layeredLayout } from './layout'

export type GraphTone = 'neutral' | 'ok' | 'warn' | 'bad' | 'ai' | 'faint'

/**
 * Above this many edges, labels are drawn on hover and on the selected edge
 * only. Below it they are all drawn, because at that size the labels are the
 * most informative thing on the drawing rather than noise.
 */
const LABELLED_EDGE_LIMIT = 18

export interface GraphNode {
  id: string
  title: string
  subtitle?: string
  /** A short figure drawn at the right of the box, such as a rollup. */
  badge?: string
  tone?: GraphTone
  /** Drawn faint and dashed: present elsewhere, not in this graph. */
  ghost?: boolean
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  tone?: GraphTone
  dashed?: boolean
  /** Drawn on the edge itself, for a verdict or a confidence. */
  label?: string
  emphasis?: boolean
}

const STROKE: Record<GraphTone, string> = {
  neutral: 'stroke-line-strong',
  ok: 'stroke-ok/70',
  warn: 'stroke-warn',
  bad: 'stroke-bad',
  ai: 'stroke-ai',
  faint: 'stroke-line',
}

const BOX: Record<GraphTone, string> = {
  neutral: 'fill-panel stroke-line-strong',
  ok: 'fill-panel stroke-ok/60',
  warn: 'fill-panel stroke-warn/70',
  bad: 'fill-panel stroke-bad/70',
  ai: 'fill-panel stroke-ai/70',
  faint: 'fill-panel stroke-line',
}

const TEXT: Record<GraphTone, string> = {
  neutral: 'fill-ink-3',
  ok: 'fill-ok',
  warn: 'fill-warn',
  bad: 'fill-bad',
  ai: 'fill-ai',
  faint: 'fill-ink-4',
}

export default function GraphCanvas({
  nodes,
  edges,
  selected,
  onSelect,
  selectedEdge,
  onSelectEdge,
  legend,
  footer,
  layout,
}: {
  nodes: GraphNode[]
  edges: GraphEdge[]
  /** The graph positions are computed from, when it is larger than the drawn one. */
  layout?: { ids: string[]; edges: { source: string; target: string }[] }
  selected?: string | null
  onSelect?: (id: string | null) => void
  selectedEdge?: string | null
  onSelectEdge?: (id: string | null) => void
  legend?: ReactNode
  footer?: ReactNode
}) {
  const [hovered, setHovered] = useState<string | null>(null)
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null)
  const focus = hovered ?? selected ?? null
  const viewport = useRef<HTMLDivElement>(null)
  const { view, controls, onPointerDown, isPanning } = usePanZoom(viewport)

  const { nodes: placed, isolated: unplaced, width, height } = layeredLayout(
    layout?.ids ?? nodes.map((node) => node.id),
    (layout?.edges ?? edges).map((edge) => ({
      source_id: edge.source,
      target_id: edge.target,
    })),
  )

  // Isolated in the drawn graph, not in the layout: the note below is about
  // what this picture shows, and a ghost is not an element of it.
  const drawnIds = new Set(nodes.filter((node) => !node.ghost).map((node) => node.id))
  const linked = new Set(edges.flatMap((edge) => [edge.source, edge.target]))
  const isolated = layout
    ? [...drawnIds].filter((id) => !linked.has(id)).sort()
    : unplaced

  const byId = new Map(nodes.map((node) => [node.id, node]))

  return (
    <div className="flex flex-col gap-7">
      <div
        ref={viewport}
        onPointerDown={onPointerDown}
        className={`surface-grid relative overflow-hidden rounded-card border border-line bg-sunken ${
          isPanning ? 'cursor-grabbing' : 'cursor-grab'
        }`}
        style={{ height: 'min(72vh, 760px)', minHeight: 420 }}
      >
        <ViewControls {...controls} />

        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-full w-full touch-none select-none"
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={`${nodes.length} elements and ${edges.length} dependencies`}
        >
          <g
            transform={`translate(${view.x} ${view.y}) scale(${view.k})`}
            style={{ transition: isPanning ? 'none' : 'transform 120ms var(--ease-flow)' }}
          >
          <defs>
            <marker
              id="graph-arrow"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M0 0 L8 4 L0 8 z" className="fill-ink-4" />
            </marker>
          </defs>

          {edges.map((edge) => {
            const from = placed.get(edge.source)
            const to = placed.get(edge.target)
            if (!from || !to) return null

            const touched = !focus || edge.source === focus || edge.target === focus
            const tone = edge.tone ?? 'neutral'
            const path = edgePath(from, to)
            const midX = (from.x + NODE_WIDTH + to.x) / 2
            const midY = (from.y + to.y + NODE_HEIGHT) / 2
            const isSelected = edge.id === selectedEdge
            const isHovered = edge.id === hoveredEdge

            // A label on every edge turns a drawing into a wall of text. The
            // label is drawn where it is read: on the edge under the pointer,
            // on the edge that was clicked, and - when the graph is small
            // enough that they do not collide - on all of them.
            const showLabel =
              edge.label && (isSelected || isHovered || edges.length <= LABELLED_EDGE_LIMIT)

            return (
              <g
                key={edge.id}
                className={`${touched ? '' : 'opacity-15'} ${
                  onSelectEdge ? 'cursor-pointer' : ''
                }`}
                onMouseEnter={() => setHoveredEdge(edge.id)}
                onMouseLeave={() => setHoveredEdge(null)}
                onClick={(event) => {
                  if (!onSelectEdge) return
                  event.stopPropagation()
                  onSelectEdge(isSelected ? null : edge.id)
                }}
              >
                {/* A wider invisible path: a 1.3px line is a hard thing to hit. */}
                <path d={path} fill="none" strokeWidth="14" className="stroke-transparent" />
                <path
                  d={path}
                  fill="none"
                  strokeWidth={isSelected ? 2.8 : edge.emphasis ? 2.2 : 1.3}
                  strokeDasharray={edge.dashed ? '5 5' : undefined}
                  className={STROKE[tone]}
                  markerEnd="url(#graph-arrow)"
                />
                {showLabel && (
                  <>
                    <rect
                      x={midX - Math.max(20, edge.label!.length * 3.6)}
                      y={midY - 9}
                      width={Math.max(40, edge.label!.length * 7.2)}
                      height="18"
                      rx="9"
                      className={`fill-sunken ${STROKE[tone]}`}
                      strokeWidth="1"
                    />
                    <text
                      x={midX}
                      y={midY + 4}
                      textAnchor="middle"
                      className={`font-mono text-[10px] ${TEXT[tone]}`}
                    >
                      {edge.label}
                    </text>
                  </>
                )}
              </g>
            )
          })}

          {nodes.map((node) => {
            const at = placed.get(node.id)
            if (!at) return null

            const touched = !focus || isNeighbour(node.id, focus, edges)
            const isSelected = node.id === selected

            return (
              <g
                key={node.id}
                className={`cursor-pointer ${touched ? '' : 'opacity-25'} ${
                  node.ghost ? 'opacity-40' : ''
                }`}
                onMouseEnter={() => setHovered(node.id)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onSelect?.(isSelected ? null : node.id)}
              >
                <rect
                  x={at.x}
                  y={at.y}
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={8}
                  className={isSelected ? 'fill-raised stroke-ink' : BOX[node.tone ?? 'neutral']}
                  strokeWidth={isSelected ? 2 : 1.2}
                  strokeDasharray={node.ghost ? '4 4' : undefined}
                />
                <text x={at.x + 16} y={at.y + 24} className="fill-ink font-mono text-[12.5px]">
                  {clip(node.title, 22)}
                </text>
                {node.subtitle && (
                  <text
                    x={at.x + 16}
                    y={at.y + 42}
                    className="fill-ink-4 font-mono text-[10.5px]"
                  >
                    {clip(node.subtitle, 24)}
                  </text>
                )}
                {node.badge && (
                  <text
                    x={at.x + NODE_WIDTH - 16}
                    y={at.y + 24}
                    textAnchor="end"
                    className="fill-ink-3 font-mono text-[11px]"
                  >
                    {node.badge}
                  </text>
                )}
              </g>
            )
          })}
          </g>
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-x-8 gap-y-3 font-mono text-xs text-ink-3">
        {legend}
        <span className="text-ink-4">drag to move · wheel to zoom</span>
      </div>

      {isolated.length > 0 && (
        <p className="max-w-prose text-sm leading-relaxed text-ink-3">
          <span className="text-ink">Nothing points at</span>{' '}
          {isolated.map((id) => byId.get(id)?.title ?? id).join(', ')} — kept on the
          page rather than dropped, because an element with no dependencies is
          usually the one worth asking about.
        </p>
      )}

      {footer}
    </div>
  )
}

/**
 * Moving around the drawing.
 *
 * Description:
 *   Drag anywhere to pan, wheel or the buttons to zoom, and one control to
 *   put it back. A graph of forty elements does not fit on a screen at a
 *   readable size, and the alternatives are both worse: shrinking it until
 *   the labels are unreadable, or cropping it so part of the system is
 *   simply absent.
 *
 *   Zooming with the wheel is attached by hand rather than through the JSX
 *   prop, because React registers wheel listeners passively and a passive
 *   listener cannot stop the page scrolling underneath the drawing.
 */
function usePanZoom(viewport: React.RefObject<HTMLDivElement | null>) {
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const [isPanning, setIsPanning] = useState(false)
  const from = useRef({ x: 0, y: 0, viewX: 0, viewY: 0 })

  const zoomBy = useCallback((factor: number) => {
    setView((current) => ({
      ...current,
      k: Math.min(3, Math.max(0.4, current.k * factor)),
    }))
  }, [])

  useEffect(() => {
    const element = viewport.current
    if (!element) return

    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      zoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12)
    }

    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [viewport, zoomBy])

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      from.current = {
        x: event.clientX,
        y: event.clientY,
        viewX: view.x,
        viewY: view.y,
      }
      setIsPanning(true)

      const move = (moved: PointerEvent) => {
        setView((current) => ({
          ...current,
          x: from.current.viewX + (moved.clientX - from.current.x),
          y: from.current.viewY + (moved.clientY - from.current.y),
        }))
      }

      const up = () => {
        setIsPanning(false)
        window.removeEventListener('pointermove', move)
        window.removeEventListener('pointerup', up)
      }

      window.addEventListener('pointermove', move)
      window.addEventListener('pointerup', up)
    },
    [view.x, view.y],
  )

  return {
    view,
    isPanning,
    onPointerDown,
    controls: {
      zoom: view.k,
      onZoomIn: () => zoomBy(1.2),
      onZoomOut: () => zoomBy(1 / 1.2),
      onReset: () => setView({ x: 0, y: 0, k: 1 }),
    },
  }
}

function ViewControls({
  zoom,
  onZoomIn,
  onZoomOut,
  onReset,
}: {
  zoom: number
  onZoomIn: () => void
  onZoomOut: () => void
  onReset: () => void
}) {
  return (
    <div
      className="absolute right-4 bottom-4 z-10 flex items-center gap-1 rounded-control border border-line-strong bg-panel/90 p-1 backdrop-blur"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <ControlButton label="Zoom out" onClick={onZoomOut}>
        −
      </ControlButton>
      <span className="w-12 text-center font-mono text-[11px] text-ink-3">
        {Math.round(zoom * 100)}%
      </span>
      <ControlButton label="Zoom in" onClick={onZoomIn}>
        +
      </ControlButton>
      <span className="mx-1 h-4 w-px bg-line" />
      <ControlButton label="Reset the view" onClick={onReset}>
        ⌂
      </ControlButton>
    </div>
  )
}

function ControlButton({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="size-7 rounded-[4px] text-sm text-ink-2 transition hover:bg-raised hover:text-ink"
    >
      {children}
    </button>
  )
}

/** One legend entry: a line in its real style, and the word it means. */
export function GraphKey({
  tone = 'neutral',
  dashed,
  children,
}: {
  tone?: GraphTone
  dashed?: boolean
  children: ReactNode
}) {
  return (
    <span className="flex items-center gap-2.5">
      <svg width="30" height="8" aria-hidden="true">
        <line
          x1="0"
          y1="4"
          x2="30"
          y2="4"
          strokeWidth="1.8"
          strokeDasharray={dashed ? '5 5' : undefined}
          className={STROKE[tone]}
        />
      </svg>
      {children}
    </span>
  )
}

function isNeighbour(id: string, focus: string, edges: GraphEdge[]): boolean {
  if (id === focus) return true

  return edges.some(
    (edge) =>
      (edge.source === focus && edge.target === id) ||
      (edge.target === focus && edge.source === id),
  )
}

function clip(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value
}
