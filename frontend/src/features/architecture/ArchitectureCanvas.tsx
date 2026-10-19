/**
 * The architecture, drawn.
 *
 * Description:
 *   Every element of one release and every dependency between them, from the
 *   stored snapshot. Nothing is computed here that the backend already
 *   counted: a figure worked out in the browser is a second implementation of
 *   it, and the two disagree on exactly the release somebody is looking at.
 *
 *   **Line style carries the meaning, not colour alone.** A call between two
 *   services is a solid line; a dependency on a cache or a database is
 *   dashed; a dependency a source-level call confirmed carries a filled
 *   joint. A projector washing out the colour, a printed appendix and a
 *   colour-blind reader all have to work, and at least two of those happen.
 *
 *   Hovering an element dims everything it does not touch. With fifteen edges
 *   that is a convenience; at fifty it is the only way the picture is
 *   readable, and it costs one class.
 */

import { useState } from 'react'
import type { SnapshotElement, SnapshotRelationship } from '../../lib/api'
import { NODE_HEIGHT, NODE_WIDTH, edgePath, layeredLayout } from './layout'

export default function ArchitectureCanvas({
  elements,
  relationships,
  selected,
  onSelect,
}: {
  elements: SnapshotElement[]
  relationships: SnapshotRelationship[]
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const [hovered, setHovered] = useState<string | null>(null)
  const focus = hovered ?? selected

  const { nodes, isolated, width, height } = layeredLayout(
    elements.map((element) => element.id),
    relationships,
  )

  const byId = new Map(elements.map((element) => [element.id, element]))
  const outgoing = new Map<string, number>()

  for (const edge of relationships) {
    outgoing.set(edge.source_id, (outgoing.get(edge.source_id) ?? 0) + 1)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="surface-grid overflow-x-auto rounded-card border border-line bg-sunken">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full"
          style={{ minWidth: Math.min(width, 1100) }}
          role="img"
          aria-label={`${elements.length} elements and ${relationships.length} dependencies`}
        >
          <defs>
            <marker
              id="arrow"
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

          {relationships.map((edge) => {
            const from = nodes.get(edge.source_id)
            const to = nodes.get(edge.target_id)
            if (!from || !to) return null

            const touched =
              !focus || edge.source_id === focus || edge.target_id === focus
            const infrastructure = edge.kind === 'infrastructure_dependency'

            return (
              <g key={edge.id} className={touched ? '' : 'opacity-15'}>
                <path
                  d={edgePath(from, to)}
                  fill="none"
                  strokeWidth={edge.confirmed_by_source ? 1.8 : 1.2}
                  strokeDasharray={infrastructure ? '5 5' : undefined}
                  className={
                    edge.confirmed_by_source ? 'stroke-ok/70' : 'stroke-line-strong'
                  }
                  markerEnd="url(#arrow)"
                />
              </g>
            )
          })}

          {elements.map((element) => {
            const node = nodes.get(element.id)
            if (!node) return null

            const touched = !focus || isNeighbour(element.id, focus, relationships)
            const isSelected = element.id === selected

            return (
              <g
                key={element.id}
                className={`cursor-pointer ${touched ? '' : 'opacity-25'}`}
                onMouseEnter={() => setHovered(element.id)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onSelect(isSelected ? null : element.id)}
              >
                <rect
                  x={node.x}
                  y={node.y}
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={8}
                  className={`fill-panel ${
                    isSelected ? 'stroke-ink' : 'stroke-line-strong'
                  }`}
                  strokeWidth={isSelected ? 2 : 1.2}
                />
                <text
                  x={node.x + 16}
                  y={node.y + 24}
                  className="fill-ink font-mono text-[12.5px]"
                >
                  {clip(element.name, 22)}
                </text>
                <text
                  x={node.x + 16}
                  y={node.y + 42}
                  className="fill-ink-4 font-mono text-[10.5px]"
                >
                  {element.kind.replace(/_/g, ' ')}
                </text>
                {outgoing.get(element.id) && (
                  <text
                    x={node.x + NODE_WIDTH - 16}
                    y={node.y + 24}
                    textAnchor="end"
                    className="fill-ink-3 font-mono text-[11px]"
                  >
                    {outgoing.get(element.id)} →
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-x-8 gap-y-3 font-mono text-xs text-ink-3">
        <Key dash={false} tone="stroke-ok/70">
          confirmed in source
        </Key>
        <Key dash={false} tone="stroke-line-strong">
          declared in configuration
        </Key>
        <Key dash tone="stroke-line-strong">
          cache, database or broker
        </Key>
      </div>

      {isolated.length > 0 && (
        <p className="text-sm leading-relaxed text-ink-3">
          <span className="text-ink">Nothing points at</span>{' '}
          {isolated.map((id) => byId.get(id)?.name ?? id).join(', ')} — kept on the
          page rather than dropped, because an element with no dependencies is
          usually the one worth asking about.
        </p>
      )}
    </div>
  )
}

function Key({
  dash,
  tone,
  children,
}: {
  dash: boolean
  tone: string
  children: string
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
          strokeDasharray={dash ? '5 5' : undefined}
          className={tone}
        />
      </svg>
      {children}
    </span>
  )
}

function isNeighbour(
  id: string,
  focus: string,
  relationships: SnapshotRelationship[],
): boolean {
  if (id === focus) return true

  return relationships.some(
    (edge) =>
      (edge.source_id === focus && edge.target_id === id) ||
      (edge.target_id === focus && edge.source_id === id),
  )
}

function clip(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value
}
