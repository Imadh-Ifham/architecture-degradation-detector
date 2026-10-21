/**
 * The navigation, and the phases of the analysis.
 *
 * Description:
 *   Two lists, kept apart on purpose.
 *
 *   **`PAGES` is where a person can go.** It is the sidebar, grouped by what
 *   somebody is doing: setting the analysis up, watching it run, or reading
 *   what it produced. It names places rather than steps — somebody looking
 *   for the architecture diagram looks for "Architecture", not for the stage
 *   that produced it.
 *
 *   **`PHASES` is what the analysis does.** It belongs on the pipeline
 *   screen, where the order means something, and nowhere else. A process in a
 *   sidebar makes every page feel like a step in a wizard, and a person comes
 *   back to look at a result far more often than they run the thing.
 *
 *   **Names are the product's, never the project's.** No screen says which
 *   team or research component produced what.
 */

export type PageGroup = 'set up' | 'run' | 'results'

export interface PageDefinition {
  path: string
  label: string
  group: PageGroup
  summary: string
  /** Live, or holding a place for work that is not written yet. */
  state: 'ready' | 'reserved'
}

export const PAGES: readonly PageDefinition[] = [
  {
    path: '/repositories',
    label: 'Repositories',
    group: 'set up',
    summary: 'The systems under analysis, and their releases',
    state: 'ready',
  },
  {
    path: '/decisions',
    label: 'Decisions',
    group: 'set up',
    summary: 'What the architecture is judged against',
    state: 'ready',
  },
  {
    path: '/',
    label: 'Pipeline',
    group: 'run',
    summary: 'Run the analysis and watch it move',
    state: 'ready',
  },
  {
    path: '/recovery',
    label: 'Recovery',
    group: 'results',
    summary: 'How the architecture was recovered, stage by stage',
    state: 'ready',
  },
  {
    path: '/architecture',
    label: 'Architecture',
    group: 'results',
    summary: 'The recovered system, as a diagram and as a table',
    state: 'ready',
  },
  {
    path: '/validation',
    label: 'Validation',
    group: 'results',
    summary: 'What was judged, who judged it, and what checked that',
    state: 'ready',
  },
  {
    path: '/findings',
    label: 'Findings',
    group: 'results',
    summary: 'Every judged dependency, with the evidence behind it',
    state: 'ready',
  },
  {
    path: '/canvas',
    label: 'Canvas',
    group: 'results',
    summary: 'Every graph the analysis produced, side by side',
    state: 'ready',
  },
  {
    path: '/drift',
    label: 'Drift',
    group: 'results',
    summary: 'What changed between releases, and how far',
    state: 'ready',
  },
  {
    path: '/priorities',
    label: 'Priorities',
    group: 'results',
    summary: 'Findings ranked by how much they matter',
    state: 'ready',
  },
]

export const PAGE_GROUPS: readonly PageGroup[] = ['set up', 'run', 'results']

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
  /** What has to be true before it can run at all. */
  requires: string
  state: 'ready' | 'reserved'
}

/**
 * The four phases, in the order the analysis runs them.
 *
 * **The order is a dependency, not a preference.** Each phase reads what the
 * one before it left behind, so a phase whose input does not exist cannot
 * run and the screen says why rather than failing when the button is pressed.
 *
 * A phase being `reserved` is a statement about this application and not
 * about the system: the work exists, the screen for it does not yet. The
 * pipeline draws it either way, because a phase missing from the drawing is
 * a phase nobody remembers to build a screen for.
 */
export const PHASES: readonly PhaseDefinition[] = [
  {
    id: 'recover',
    label: 'Recover',
    input: 'a repository and a release',
    output: 'the architecture as it is',
    page: '/architecture',
    requires: 'a repository has been added',
    state: 'ready',
  },
  {
    id: 'validate',
    label: 'Validate',
    input: 'the architecture and the recorded decisions',
    output: 'a verdict on every dependency',
    page: '/validation',
    requires: 'the architecture for this release has been recovered',
    state: 'ready',
  },
  {
    id: 'detect',
    label: 'Detect',
    input: 'every validated release',
    output: 'what degraded, and when it started',
    page: '/drift',
    requires: 'a release has been validated',
    state: 'ready',
  },
  {
    id: 'prioritise',
    label: 'Score',
    input: 'what degraded',
    output: 'a ranked list with reasons',
    page: '/priorities',
    requires: 'degradation has been detected',
    state: 'ready',
  },
]
