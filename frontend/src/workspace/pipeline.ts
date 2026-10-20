/**
 * One pipeline run: recover every snapshot, then validate every snapshot.
 *
 * Description:
 *   The order is the whole point of this module. Recovery is the expensive
 *   step and validation reads what recovery produced, so every snapshot is
 *   recovered first and validation starts only once all of them have. Both
 *   phases run one snapshot at a time: a run that is watched is a run whose
 *   progress can be reported, and sequential execution is what makes "which
 *   snapshot is it on" a question with one answer.
 *
 *   **A failure is never carried forward.** A snapshot that fails to clone,
 *   fails to recover, or recovers without producing a snapshot is marked
 *   failed with the reason, and the validation phase does not start at all
 *   while any snapshot is in that state. Validating only the snapshots that
 *   happened to work would publish a result that reads like a clean run of a
 *   smaller pipeline.
 *
 *   This is wiring, not UI: it takes the calls and an `onChange` sink so the
 *   pipeline screen can render progress and a test can run it without React.
 */

import {
  ingestRepository,
  messageOf,
  runRecovery,
  runValidation,
  type DecisionMode,
  type RecoveryResult,
  type RepositoryConfiguration,
  type ValidationRun,
} from '../lib/api'

export type SnapshotPhase =
  | 'queued'
  | 'ingesting'
  | 'recovering'
  | 'recovered'
  | 'validating'
  | 'validated'
  | 'failed'

/** Which call failed, so the screen can say where the run stopped. */
export type SnapshotFault = 'ingest' | 'recovery' | 'validation'

export interface SnapshotRun {
  configuration: RepositoryConfiguration
  phase: SnapshotPhase
  /** The clone's workspace id, once ingestion has produced one. */
  repositoryId: string | null
  recovery: RecoveryResult | null
  run: ValidationRun | null
  error: string | null
  fault: SnapshotFault | null
}

export type PipelinePhase =
  | 'idle'
  | 'recovering'
  | 'validating'
  | 'complete'
  | 'blocked'
  | 'failed'

export interface RunPipelineOptions {
  decisionMode: DecisionMode
  adrRepositoryId?: string | null
  onChange: (snapshots: SnapshotRun[]) => void
  onPhase?: (phase: PipelinePhase) => void
  onValidated?: (snapshot: SnapshotRun) => void
}

export interface PipelineOutcome {
  snapshots: SnapshotRun[]
  /** Set when validation never started, because recovery did not finish. */
  blockedAt: 'recovery' | null
}

export async function runPipeline(
  configurations: RepositoryConfiguration[],
  options: RunPipelineOptions,
): Promise<PipelineOutcome> {
  let snapshots: SnapshotRun[] = configurations.map((configuration) => ({
    configuration,
    phase: 'queued',
    repositoryId: null,
    recovery: null,
    run: null,
    error: null,
    fault: null,
  }))

  const update = (index: number, patch: Partial<SnapshotRun>) => {
    snapshots = snapshots.map((item, at) =>
      at === index ? { ...item, ...patch } : item,
    )
    options.onChange(snapshots)
  }

  options.onPhase?.('recovering')

  for (let index = 0; index < snapshots.length; index += 1) {
    const { configuration } = snapshots[index]

    update(index, { phase: 'ingesting', error: null, fault: null })

    let repositoryId: string

    try {
      const ingested = await ingestRepository({
        url: configuration.url,
        branch: configuration.branch,
        revision: configuration.release_tag,
      })
      repositoryId = ingested.id
    } catch (cause) {
      update(index, {
        phase: 'failed',
        fault: 'ingest',
        error: messageOf(cause),
      })
      continue
    }

    update(index, { phase: 'recovering', repositoryId })

    try {
      const recovery = await runRecovery(repositoryId)

      // Recovery reports a stage failure in the body rather than the status,
      // so "it answered" is not "it produced an architecture".
      if (!recovery.graph_construction || recovery.graph_construction_error) {
        update(index, {
          phase: 'failed',
          fault: 'recovery',
          recovery,
          error:
            recovery.graph_construction_error ??
            'recovery stopped before it produced an architecture snapshot',
        })
        continue
      }

      update(index, { phase: 'recovered', recovery })
    } catch (cause) {
      update(index, {
        phase: 'failed',
        fault: 'recovery',
        error: messageOf(cause),
      })
    }
  }

  if (snapshots.some((snapshot) => snapshot.phase === 'failed')) {
    options.onPhase?.('blocked')

    return { snapshots, blockedAt: 'recovery' }
  }

  options.onPhase?.('validating')

  for (let index = 0; index < snapshots.length; index += 1) {
    const snapshot = snapshots[index]

    update(index, { phase: 'validating' })

    try {
      const run = await runValidation({
        repository_id: snapshot.recovery?.repository_id ?? snapshot.repositoryId ?? '',
        release_id: snapshot.configuration.release_tag,
        decision_mode: options.decisionMode,
        adr_repository_id: options.adrRepositoryId || null,
      })

      const validated: SnapshotRun = { ...snapshots[index], phase: 'validated', run }
      update(index, { phase: 'validated', run })
      options.onValidated?.(validated)
    } catch (cause) {
      update(index, {
        phase: 'failed',
        fault: 'validation',
        error: messageOf(cause),
      })
    }
  }

  const failed = snapshots.some((snapshot) => snapshot.phase === 'failed')
  options.onPhase?.(failed ? 'failed' : 'complete')

  return { snapshots, blockedAt: null }
}
