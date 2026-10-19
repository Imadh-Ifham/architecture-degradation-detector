/**
 * The pipeline, drawn as a pipeline.
 *
 * Description:
 *   Four phases, joined by pipe. While a phase is working, the pipe feeding
 *   it carries a visible flow and the phase itself is lit; a finished phase
 *   is filled and the flow has moved on.
 *
 *   **Why this is a drawing and not a list of rows.** The one thing a person
 *   has to understand in the first five seconds is that this is a sequence
 *   where each part hands something to the next. A list of four rows with
 *   ticks says "four things happened"; a pipe with something moving through
 *   it says what the system is. The motion is the explanation, which is why
 *   it is here and why it is nowhere else in the application.
 *
 *   Under reduced-motion the flow stops and the states still arrive: lit,
 *   filled, waiting. Nothing is only an animation.
 */

import { PHASES, type PhaseId } from '../../layouts/navigation'

export type PhaseState =
  | 'blocked'
  | 'waiting'
  | 'running'
  | 'done'
  | 'reserved'

const NODE_WIDTH = 200
const NODE_HEIGHT = 92
const GAP = 68
const TOP = 54
const VIEW_WIDTH = PHASES.length * NODE_WIDTH + (PHASES.length - 1) * GAP
const VIEW_HEIGHT = TOP + NODE_HEIGHT + 86

export default function PipelineFlow({
  states,
  onSelect,
  selected,
}: {
  states: Record<PhaseId, PhaseState>
  selected: PhaseId
  onSelect: (id: PhaseId) => void
}) {
  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        className="h-auto w-full min-w-[760px]"
        role="img"
        aria-label="The analysis pipeline: recover, validate, detect, prioritise"
      >
        {PHASES.slice(0, -1).map((phase, index) => (
          <Pipe
            key={phase.id}
            index={index}
            flowing={states[PHASES[index + 1].id] === 'running'}
            filled={states[phase.id] === 'done'}
          />
        ))}

        {PHASES.map((phase, index) => (
          <Phase
            key={phase.id}
            index={index}
            label={phase.label}
            output={phase.output}
            state={states[phase.id]}
            isSelected={phase.id === selected}
            onSelect={() => onSelect(phase.id)}
          />
        ))}
      </svg>
    </div>
  )
}

function Pipe({
  index,
  flowing,
  filled,
}: {
  index: number
  flowing: boolean
  filled: boolean
}) {
  const x1 = index * (NODE_WIDTH + GAP) + NODE_WIDTH
  const x2 = x1 + GAP
  const y = TOP + NODE_HEIGHT / 2
  const d = `M ${x1} ${y} L ${x2} ${y}`

  return (
    <g>
      {/* The pipe wall, always there, so an empty pipe still reads as a pipe. */}
      <path d={d} className="stroke-line" strokeWidth="12" strokeLinecap="round" />
      {filled && (
        <path
          d={d}
          className="stroke-ok/35"
          strokeWidth="12"
          strokeLinecap="round"
        />
      )}
      {flowing && (
        <path
          d={d}
          className="stroke-ai animate-[pipe-flow_900ms_linear_infinite]"
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray="10 20"
        />
      )}
      {/* The direction, stated once per joint rather than inferred. */}
      <path
        d={`M ${x2 - 7} ${y - 5} L ${x2 - 1} ${y} L ${x2 - 7} ${y + 5}`}
        className="fill-none stroke-ink-4"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </g>
  )
}

function Phase({
  index,
  label,
  output,
  state,
  isSelected,
  onSelect,
}: {
  index: number
  label: string
  output: string
  state: PhaseState
  isSelected: boolean
  onSelect: () => void
}) {
  const x = index * (NODE_WIDTH + GAP)

  const body = {
    blocked: 'fill-sunken stroke-line',
    waiting: 'fill-panel stroke-line-strong',
    running: 'fill-ai-wash stroke-ai',
    done: 'fill-panel stroke-ok/70',
    reserved: 'fill-panel stroke-line [stroke-dasharray:4_4]',
  }[state]

  const labelTone = state === 'done' || state === 'running' ? 'fill-ink' : 'fill-ink-2'

  return (
    <g className="cursor-pointer" onClick={onSelect} role="button" tabIndex={0}>
      {isSelected && (
        <rect
          x={x - 7}
          y={TOP - 7}
          width={NODE_WIDTH + 14}
          height={NODE_HEIGHT + 14}
          rx={14}
          className="fill-none stroke-ink-4"
          strokeDasharray="3 4"
        />
      )}

      <rect
        x={x}
        y={TOP}
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={10}
        className={body}
        strokeWidth="1.5"
      />

      <text
        x={x + 22}
        y={TOP + 36}
        className={`font-sans text-[15px] font-semibold ${labelTone}`}
      >
        {label}
      </text>

      <text x={x + 22} y={TOP + 60} className="fill-ink-3 font-mono text-[11px]">
        {output.length > 26 ? `${output.slice(0, 25)}…` : output}
      </text>

      <StateMark x={x + NODE_WIDTH - 24} y={TOP + 30} state={state} />

      <text
        x={x + 22}
        y={TOP + NODE_HEIGHT + 28}
        className="fill-ink-4 font-mono text-[11px]"
      >
        {
          {
            blocked: 'needs the phase before it',
            waiting: 'ready to run',
            running: 'running',
            done: 'complete',
            reserved: 'screen not built',
          }[state]
        }
      </text>
    </g>
  )
}

function StateMark({ x, y, state }: { x: number; y: number; state: PhaseState }) {
  if (state === 'running') {
    return (
      <circle
        cx={x}
        cy={y}
        r="5"
        className="fill-ai animate-[pulse-dot_1100ms_ease-in-out_infinite]"
      />
    )
  }

  if (state === 'done') {
    return (
      <path
        d={`M ${x - 6} ${y} l 4 4 l 7 -8`}
        className="fill-none stroke-ok"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    )
  }

  if (state === 'blocked') {
    // A lock rather than an empty circle: waiting and cannot-yet are
    // different states, and only one of them is about to change by itself.
    return (
      <g className="stroke-ink-4" strokeWidth="1.4" fill="none">
        <rect x={x - 5} y={y - 2} width="10" height="8" rx="1.5" />
        <path d={`M ${x - 3} ${y - 2} v -2.5 a 3 3 0 0 1 6 0 v 2.5`} />
      </g>
    )
  }

  return <circle cx={x} cy={y} r="4.5" className="fill-none stroke-ink-4" strokeWidth="1.5" />
}
