/**
 * The navigation, and the phases of the analysis.
 *
 * Description:
 *   Two lists, kept apart on purpose.
 *
 *   **`PAGES` is where a person can go.** It is the sidebar, and it names
 *   places rather than steps: somebody looking for the architecture diagram
 *   looks for "Architecture", not for the stage that produced it.
 *
 *   **`PHASES` is what the analysis does.** It belongs on the pipeline screen,
 *   where the order means something, and nowhere else. Putting a process in a
 *   sidebar makes every page feel like a step in a wizard, and the system is
 *   not a wizard: a person comes back to look at a result far more often than
 *   they run the thing.
 *
 *   **Names are the product's, never the project's.** No screen says which
 *   team or which research component produced what. A person reading the
 *   screen cares what the thing is.
 */

export interface PageDefinition {
  path: string
  label: string
  summary: string
  /** Live, or holding a place for work that is not written yet. */
  state: 'ready' | 'reserved'
}

export const PAGES: readonly PageDefinition[] = [
  {
    path: '/',
    label: 'Pipeline',
    summary: 'Run the analysis and watch it move',
    state: 'ready',
  },
  {
    path: '/repositories',
    label: 'Repositories',
    summary: 'The systems under analysis, and their releases',
    state: 'ready',
  },
  {
    path: '/architecture',
    label: 'Architecture',
    summary: 'The recovered system, as a diagram and as a table',
    state: 'ready',
  },
  {
    path: '/decisions',
    label: 'Decisions',
    summary: 'What the architecture is judged against',
    state: 'ready',
  },
  {
    path: '/findings',
    label: 'Findings',
    summary: 'Every judged dependency, with the evidence behind it',
    state: 'reserved',
  },
  {
    path: '/drift',
    label: 'Drift',
    summary: 'What changed between releases, and how far',
    state: 'reserved',
  },
  {
    path: '/priorities',
    label: 'Priorities',
    summary: 'Findings ranked by how much they matter',
    state: 'reserved',
  },
]

export type PhaseId = 'recover' | 'validate' | 'detect' | 'prioritise'

export interface PhaseDefinition {
  id: PhaseId
  label: string
  /** What it reads, in a person's words. */
  input: string
  /** What it leaves behind for the next phase. */
  output: string
  /** Where a person goes to look at the result. */
  page: string
  state: 'ready' | 'reserved'
}

/**
 * The four phases, in the order the analysis runs them.
 *
 * A phase being `reserved` is a statement about this application and not
 * about the system: the work exists, the screen for it does not yet. The
 * pipeline draws it either way, because a phase that is missing from the
 * drawing is a phase nobody remembers to build a screen for.
 */
export const PHASES: readonly PhaseDefinition[] = [
  {
    id: 'recover',
    label: 'Recover',
    input: 'a repository and a release',
    output: 'the architecture as it is',
    page: '/architecture',
    state: 'ready',
  },
  {
    id: 'validate',
    label: 'Validate',
    input: 'the architecture and the recorded decisions',
    output: 'a verdict on every dependency',
    page: '/findings',
    state: 'ready',
  },
  {
    id: 'detect',
    label: 'Detect',
    input: 'two or more validated releases',
    output: 'what degraded, and when it started',
    page: '/drift',
    state: 'reserved',
  },
  {
    id: 'prioritise',
    label: 'Prioritise',
    input: 'what degraded',
    output: 'a ranked list with reasons',
    page: '/priorities',
    state: 'reserved',
  },
]
