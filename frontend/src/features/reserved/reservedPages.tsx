/**
 * The screens that are not written yet.
 *
 * Description:
 *   Routes held open with their name, their place in the navigation
 *   and the backend they will read. Whoever builds one replaces the element
 *   here with their own page and deletes its entry - the route, the label and
 *   the sidebar position stay as they are.
 *
 *   Each one names the folder its code goes in, so two people cannot put the
 *   same screen in two places.
 */

import ReservedPage from '../../components/ReservedPage'

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
