/**
 * The screens that are not written yet.
 *
 * Description:
 *   Three routes, held open with their name, their place in the navigation
 *   and the backend they will read. Whoever builds one replaces the element
 *   here with their own page and deletes its entry - the route, the label and
 *   the sidebar position stay as they are.
 *
 *   Each one names the folder its code goes in, so two people cannot put the
 *   same screen in two places.
 */

import ReservedPage from '../../components/ReservedPage'

export function FindingsPage() {
  return (
    <ReservedPage
      eyebrow="judged"
      title="Findings"
      description="Every dependency with a verdict on it, and the evidence each verdict rests on."
      shows={[
        'One row per dependency: what was concluded, how confident the system is, and what it was judged against.',
        'The quoted lines a verdict cites, in the file they came from, so a claim can be checked rather than taken.',
        'Which conclusions a model produced, which a deterministic rule produced, and where the two disagreed.',
        'The queue of findings held back for a person to decide, and what confirming one changes.',
      ]}
      reads={[
        {
          endpoint: 'POST /validations',
          note: 'The run. Already called by the pipeline screen; this screen reads the same result.',
        },
        {
          endpoint: 'GET /validations/reviews',
          note: 'The findings held back for a person, oldest first.',
        },
        {
          endpoint: 'POST /validations/reviews/{item_id}',
          note: 'Records a decision. It does not re-run anything — the run is a separate act.',
        },
      ]}
      folder="src/features/findings/"
    />
  )
}

export function DriftPage() {
  return (
    <ReservedPage
      eyebrow="over time"
      title="Drift"
      description="What changed between two releases of the same system, and which changes are getting worse rather than simply different."
      shows={[
        'Two releases side by side, with the elements in the same places, so the difference is visible instead of searched for.',
        'What was added, what was removed, and which dependency changed its verdict.',
        'A trend per measure across the releases on record, with how certain that trend is.',
        'The point a problem started, rather than only the fact that it exists now.',
      ]}
      reads={[
        {
          endpoint: 'the published graph of each release',
          note: 'Written by the validation phase, one document per release.',
        },
        {
          endpoint: 'GET /repositories/{id}/snapshots',
          note: 'The releases on record, oldest first, with the field that ordered them.',
        },
      ]}
      folder="src/features/drift/"
    />
  )
}

export function PrioritiesPage() {
  return (
    <ReservedPage
      eyebrow="ranked"
      title="Priorities"
      description="The findings that matter most, with the reasons they rank where they do."
      shows={[
        'A ranked list, with each finding’s score broken into the parts that produced it.',
        'What a score is made of: how much of the system a problem touches, how often that area changes, whether it breaks a recorded decision, and how long it has persisted.',
        'Findings that could not be scored, listed rather than dropped.',
        'Whether the numbers came from real analysis or from a fixture, said plainly on the page.',
      ]}
      reads={[
        {
          endpoint: 'the severity report',
          note: 'Produced from the findings of the phase before it.',
        },
      ]}
      folder="src/features/priorities/"
    />
  )
}
