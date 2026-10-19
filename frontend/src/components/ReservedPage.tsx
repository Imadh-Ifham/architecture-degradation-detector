/**
 * A page held open for work that is not written yet.
 *
 * Description:
 *   The screens this application will have, standing in for themselves until
 *   whoever owns them builds them. Each one names what belongs there, which
 *   backend it reads, and where the work goes.
 *
 *   **Why a placeholder is better than no route.** An absent page is a
 *   decision nobody made: the person who comes to build it has to invent
 *   where it lives, what it is called and how it is reached, and whatever
 *   they invent will not match the three screens beside it. A reserved page
 *   fixes the name, the route and the frame now, so the work that arrives
 *   later fits the first time.
 *
 *   **It must not look finished.** No invented figures, no sample rows. The
 *   page says what it is for, and the sidebar says "soon".
 */

import { Card, PageHeading, Pill } from './ui'

export interface ReservedPageProps {
  eyebrow: string
  title: string
  description: string
  /** What this screen will show, in the words a person would use. */
  shows: string[]
  /** The backend it reads, so the first question is already answered. */
  reads: { endpoint: string; note: string }[]
  /** Where the code goes, so two people do not put it in two places. */
  folder: string
}

export default function ReservedPage({
  eyebrow,
  title,
  description,
  shows,
  reads,
  folder,
}: ReservedPageProps) {
  return (
    <>
      <PageHeading
        eyebrow={eyebrow}
        title={title}
        description={description}
        action={<Pill tone="warn">not built yet</Pill>}
      />

      <div className="grid gap-7 lg:grid-cols-2">
        <Card title="What belongs here">
          <ul className="flex flex-col gap-3">
            {shows.map((item) => (
              <li key={item} className="flex gap-3 text-sm leading-relaxed text-ink-2">
                <span className="mt-2 size-1 shrink-0 rounded-full bg-ink-4" />
                {item}
              </li>
            ))}
          </ul>
        </Card>

        <Card title="What it reads">
          <div className="flex flex-col gap-5">
            {reads.map((item) => (
              <div key={item.endpoint} className="flex flex-col gap-1.5">
                <code className="font-mono text-sm text-ink">{item.endpoint}</code>
                <span className="text-xs leading-relaxed text-ink-3">{item.note}</span>
              </div>
            ))}

            <div className="flex flex-col gap-1.5 border-t border-line pt-5">
              <span className="text-xs tracking-wide text-ink-4">the code goes in</span>
              <code className="font-mono text-sm text-ink-2">{folder}</code>
            </div>
          </div>
        </Card>
      </div>
    </>
  )
}
