/**
 * One pipeline run: do what the configured snapshots still need, and stop.
 *
 * Description:
 *   Recovery is the expensive step and it is the only step this module runs.
 *   Snapshots are recovered one at a time: a run that is watched is a run
 *   whose progress can be reported, and sequential execution is what makes
 *   "which snapshot is it on" a question with one answer.
 *
 *   **A run does only what is missing.** The backend reports, per configured
 *   snapshot, whether its revision is cloned and whether a finished recovery
 *   left an architecture behind. A snapshot that is already recovered is not
 *   cloned and not analysed again; one that is cloned is recovered without
 *   being cloned again. Re-cloning is not idle housekeeping - it replaces the
 *   checkout's directory, and that directory is where the snapshot's recovery
 *   artifacts live - so pressing run twice used to delete the first press's
 *   work before redoing it.
 *
 *   `force` is the one way to ask for the work over again, and it exists
 *   because skipping correctly means never redoing anything else: a snapshot
 *   recovered before a bug was fixed would otherwise be skipped for ever.
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
  type ConfigurationState,
  type RecoveryResult,
  type RepositoryConfiguration,
} from '../lib/api'

export type SnapshotPhase =
  | 'queued'
  | 'cloned'
  | 'ingesting'
  | 'recovering'
  | 'recovered'
  | 'failed'

/**
 * What this press did to a snapshot, as opposed to what it now is.
 *
 * `cloned` means it was cloned and recovered; `recovered` means the checkout
 * was reused; `skipped` means it was already recovered and the run left it
 * exactly as it found it.
 */
export type SnapshotAction = 'cloned' | 'recovered' | 'skipped'

/** Which call failed, so the screen can say where the run stopped. */
export type SnapshotFault = 'ingest' | 'recovery'

export interface SnapshotRun {
  configuration: RepositoryConfiguration
  phase: SnapshotPhase
  /** What this press did. Null until the run reaches this snapshot. */
  action: SnapshotAction | null
  /** The clone's workspace id, once one exists. */
  repositoryId: string | null
  recovery: RecoveryResult | null
  /** What the machine already held when the run started, if it was read. */
  stored: ConfigurationState | null
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
  /** What the backend says is already done, keyed by configuration id. */
  stored?: ReadonlyMap<string, ConfigurationState>
  /** Clone and recover every snapshot again, whatever is already on disk. */
  force?: boolean
}

export interface PipelineOutcome {
  snapshots: SnapshotRun[]
  /** Set when the stack did not finish recovering, so it cannot be judged. */
  blockedAt: 'recovery' | null
  /** How many snapshots this press actually cloned or recovered. */
  worked: number
}

export async function runPipeline(
  configurations: RepositoryConfiguration[],
  options: RunPipelineOptions,
): Promise<PipelineOutcome> {
  const stored = options.stored ?? new Map<string, ConfigurationState>()
  const force = options.force ?? false

  let snapshots: SnapshotRun[] = configurations.map((configuration) => {
    const state = stored.get(configuration.id)

    return {
      configuration,
      // A row reads as what the machine has from the first render, so the
      // stack does not claim to have done nothing when it has done half.
      phase:
        !force && state?.stage === 'recovered'
          ? 'recovered'
          : !force && state?.stage === 'cloned'
            ? 'cloned'
            : 'queued',
      action: null,
      repositoryId: force ? null : (state?.clone?.id ?? null),
      recovery: null,
      stored: state ?? null,
      error: null,
      fault: null,
    }
  })

  const update = (index: number, patch: Partial<SnapshotRun>) => {
    snapshots = snapshots.map((item, at) =>
      at === index ? { ...item, ...patch } : item,
    )
    options.onChange(snapshots)
  }

  options.onChange(snapshots)

  // Everything is already done: nothing is cloned, nothing is analysed, and
  // the stack is ready to be judged. Saying `recovering` here would show a
  // phase that is not happening.
  const pending = snapshots.filter((snapshot) => snapshot.phase !== 'recovered')

  if (pending.length === 0) {
    options.onPhase?.('recovered')

    return { snapshots, blockedAt: null, worked: 0 }
  }

  options.onPhase?.('recovering')

  let worked = 0

  for (let index = 0; index < snapshots.length; index += 1) {
    const { configuration } = snapshots[index]
    const state = stored.get(configuration.id)

    if (!force && state?.stage === 'recovered') {
      update(index, {
        phase: 'recovered',
        action: 'skipped',
        repositoryId: state.clone?.id ?? null,
        recovery: null,
        error: null,
        fault: null,
      })
      continue
    }

    // A checkout that exists is not cloned again. Only its analysis is
    // missing, and re-cloning would delete the artifacts of a previous run.
    let repositoryId = force ? null : (state?.clone?.id ?? null)
    let action: SnapshotAction = 'recovered'

    if (repositoryId) {
      update(index, { phase: 'recovering', action, repositoryId, error: null, fault: null })
    } else {
      update(index, { phase: 'ingesting', action: 'cloned', error: null, fault: null })

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
          action: null,
          fault: 'ingest',
          error: messageOf(cause),
        })
        continue
      }

      action = 'cloned'
      update(index, { phase: 'recovering', action, repositoryId })
    }

    worked += 1

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

      update(index, { phase: 'recovered', action, recovery })
    } catch (cause) {
      update(index, {
        phase: 'failed',
        action: null,
        fault: 'recovery',
        error: messageOf(cause),
      })
    }
  }

  if (snapshots.some((snapshot) => snapshot.phase === 'failed')) {
    options.onPhase?.('blocked')

    return { snapshots, blockedAt: 'recovery', worked }
  }

  options.onPhase?.('recovered')

  return { snapshots, blockedAt: null, worked }
}
