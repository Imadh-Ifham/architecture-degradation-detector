/**
 * One stage, as the screen needs it.
 *
 * Description:
 *   The backend answers with every stage already finished. This turns that
 *   answer plus how far the replay has got into the state each stage is drawn
 *   in, so the component below is a drawing and nothing else.
 */

import type { StageDescription, StageRecord } from '../../lib/api'

export interface StageView {
  name: string
  role: string
  usesModel: boolean
  implemented: boolean
  record: StageRecord | null
  state: 'idle' | 'running' | 'done' | 'skipped' | 'failed' | 'unbuilt'
}

export function toStageViews(
  stages: StageDescription[],
  records: StageRecord[],
  revealed: number,
): StageView[] {
  const byName = new Map(records.map((record) => [record.name, record]))

  return stages.map((stage, index) => {
    const record = byName.get(stage.name) ?? null

    if (!stage.implemented) {
      return { ...view(stage), record: null, state: 'unbuilt' }
    }

    if (records.length === 0) {
      return { ...view(stage), record: null, state: 'idle' }
    }

    if (index > revealed) {
      return { ...view(stage), record: null, state: 'idle' }
    }

    if (index === revealed && revealed < stages.length) {
      return { ...view(stage), record, state: 'running' }
    }

    const status = record?.status ?? 'skipped'
    return {
      ...view(stage),
      record,
      state: status === 'completed' ? 'done' : status === 'failed' ? 'failed' : 'skipped',
    }
  })
}

function view(stage: StageDescription) {
  return {
    name: stage.name,
    role: stage.role,
    usesModel: stage.uses_model,
    implemented: stage.implemented,
  }
}
