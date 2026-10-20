/**
 * One pipeline run: recover every configured snapshot, and stop there.
 *
 * Description:
 *   Recovery is the expensive step and it is the only step this module runs.
 *   Snapshots are recovered one at a time: a run that is watched is a run
 *   whose progress can be reported, and sequential execution is what makes
 *   "which snapshot is it on" a question with one answer.
 *
 *   **Validation is deliberately not here.** It cannot be started until
 *   somebody has chosen what the release is judged against, and that choice is
 *   the one thing the analysis cannot make for a person - a release validated
 *   against a source nobody picked reports "nothing contradicts the
 *   architecture", which is indistinguishable from a clean result on a healthy
 *   system. So this module hands back a recovered stack and the decisions
 *   screen starts the validation, with the yields of every source on screen at
 *   the moment of choosing.
 *
 *   Running it here with a default would be the same mistake in a different
 *   place: a mode selected by a constant is not a decision anybody made.
 *
 *   **A failure is never carried forward.** A snapshot that fails to clone,
 *   fails to recover, or recovers without producing a snapshot is marked
 *   failed with the reason, and the stack is reported as blocked. A partially
 *   recovered stack that went on to be validated would read like a clean run
 *   of a smaller pipeline.
 *
 *   This is wiring, not UI: it takes the calls and an `onChange` sink so the
 *   pipeline screen can render progress and a test can run it without React.
 */

import {
  ingestRepository,
  messageOf,
  runRecovery,
  type RecoveryResult,
  type RepositoryConfiguration,
} from '../lib/api'

export type SnapshotPhase =
  | 'queued'
  | 'ingesting'
  | 'recovering'
  | 'recovered'
  | 'failed'

/** Which call failed, so the screen can say where the run stopped. */
export type SnapshotFault = 'ingest' | 'recovery'

export interface SnapshotRun {
  configuration: RepositoryConfiguration
  phase: SnapshotPhase
  /** The clone's workspace id, once ingestion has produced one. */
  repositoryId: string | null
  recovery: RecoveryResult | null
  error: string | null
  fault: SnapshotFault | null
}

/**
 * How far the stack has got.
 *
 * `recovered` is a terminal state here and it is not "complete": the stack is
 * ready to be judged and nothing has judged it. Calling it complete is what
 * would let a screen show four green phases over a result that does not exist.
 */
export type PipelinePhase = 'idle' | 'recovering' | 'recovered' | 'blocked'

export interface RunPipelineOptions {
  onChange: (snapshots: SnapshotRun[]) => void
  onPhase?: (phase: PipelinePhase) => void
}

export interface PipelineOutcome {
  snapshots: SnapshotRun[]
  /** Set when the stack did not finish recovering, so it cannot be judged. */
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

  options.onPhase?.('recovered')

  return { snapshots, blockedAt: null }
}
