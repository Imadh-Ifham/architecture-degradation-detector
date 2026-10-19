/**
 * The stages inside one phase.
 *
 * Description:
 *   A phase is one box on the pipeline; this is what is inside it. The stages
 *   arrive from the backend in run order, and each one shows a **number**
 *   rather than a tick - "15 facts" says something happened, a tick says
 *   nothing.
 *
 *   Two stages of the validation phase call a language model and the rest are
 *   ordinary code. That difference is marked, because it is the most common
 *   question anybody asks about the system and the answer should be visible
 *   rather than explained.
 */

import { Pill } from '../../components/ui'
import type { StageView } from './stageViews'

export default function StageTrack({ stages }: { stages: StageView[] }) {
  return (
    <ol className="grid gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
      {stages.map((stage, index) => (
        <li
          key={stage.name}
          className={`flex flex-col gap-3 bg-panel px-6 py-5 ${
            stage.state === 'running' ? 'bg-raised' : ''
          }`}
          style={{ animation: 'stage-in 240ms var(--ease-flow) both' }}
        >
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-[11px] text-ink-4">
              {String(index + 1).padStart(2, '0')}
            </span>
            {stage.usesModel && <Pill tone="ai">model</Pill>}
          </div>

          <span
            className={`text-sm leading-snug ${
              stage.state === 'idle' || stage.state === 'unbuilt'
                ? 'text-ink-4'
                : 'text-ink'
            }`}
          >
            {label(stage.name)}
          </span>

          <StageDetail stage={stage} />
        </li>
      ))}
    </ol>
  )
}

function StageDetail({ stage }: { stage: StageView }) {
  if (stage.state === 'unbuilt') {
    return <span className="font-mono text-xs text-ink-4">not built yet</span>
  }

  if (stage.state === 'running') {
    return (
      <span className="flex items-center gap-2 font-mono text-xs text-ai">
        <span className="size-1.5 animate-[pulse-dot_1100ms_ease-in-out_infinite] rounded-full bg-ai" />
        working
      </span>
    )
  }

  if (stage.state === 'idle' || !stage.record) {
    return <span className="font-mono text-xs text-ink-4">waiting</span>
  }

  const counts = Object.entries(stage.record.counts).slice(0, 3)

  return (
    <div className="flex flex-col gap-1.5">
      {counts.length === 0 && (
        <span className="font-mono text-xs text-ink-3">{stage.record.status}</span>
      )}
      {counts.map(([key, value]) => (
        <span key={key} className="font-mono text-xs text-ink-2">
          <span className="text-ink">{value}</span> {key.replace(/_/g, ' ')}
        </span>
      ))}
      <span className="font-mono text-[11px] text-ink-4">
        {stage.record.duration_ms} ms
      </span>
      {stage.record.note && (
        <span className="text-xs leading-relaxed text-warn">{stage.record.note}</span>
      )}
    </div>
  )
}

/** The stage's name, as a person would say it. */
function label(name: string): string {
  return name.replace(/_/g, ' ')
}
