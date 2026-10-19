/**
 * Repositories screen.
 *
 * Description:
 *   Add a system to analyse, see what is already here, and remove one again.
 *   Carried forward from the first version of this application, with the same
 *   behaviour and the shared layout: the request is aborted on unmount, the
 *   list refreshes after a change, and the backend's own words are what a
 *   failure says.
 *
 *   **A branch and a release are two different acts.** Adding a branch
 *   follows a moving target; adding a release pins one revision and leaves
 *   the others alone. They are two forms rather than a checkbox, because the
 *   thing that comes back is different and a person should know which they
 *   asked for before they ask.
 */

import { useCallback, useState, type FormEvent } from 'react'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  PageHeading,
  Pill,
  Spinner,
  inputClass,
} from '../../components/ui'
import {
  ingestRelease,
  ingestRepository,
  messageOf,
  removeRepository,
  type IngestResult,
} from '../../lib/api'
import { useWorkspace } from '../../workspace/useWorkspace'
import IngestReport from './IngestReport'

export default function RepositoriesPage() {
  const { repositories, repository, isLoading, error, select, reload } = useWorkspace()

  const [url, setUrl] = useState('')
  const [branch, setBranch] = useState('main')
  const [revision, setRevision] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [result, setResult] = useState<IngestResult | null>(null)
  const [removingId, setRemovingId] = useState<string | null>(null)

  const submit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      setIsSubmitting(true)
      setSubmitError(null)
      setResult(null)

      try {
        const added = revision.trim()
          ? await ingestRelease({ url, branch, revision: revision.trim() })
          : await ingestRepository({ url, branch })

        setResult(added)
        setUrl('')
        setRevision('')
        reload()
      } catch (cause) {
        // The backend says which branch is missing or what git refused; a
        // generic message here would throw that away.
        setSubmitError(messageOf(cause))
      } finally {
        setIsSubmitting(false)
      }
    },
    [url, branch, revision, reload],
  )

  const drop = useCallback(
    async (repositoryId: string) => {
      setRemovingId(repositoryId)

      try {
        await removeRepository(repositoryId)
        reload()
      } catch (cause) {
        setSubmitError(messageOf(cause))
      } finally {
        setRemovingId(null)
      }
    },
    [reload],
  )

  return (
    <>
      <PageHeading
        eyebrow="sources"
        title="Repositories"
        description="A repository is cloned into the server workspace and analysed there. One release at a time, named so it can be ordered against the others."
      />

      <Card title="Add a repository">
        <form onSubmit={submit} className="flex flex-col gap-7">
          <div className="grid gap-6 lg:grid-cols-[2fr_1fr_1fr]">
            <Field label="Repository URL">
              <input
                name="url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://github.com/organisation/project.git"
                autoComplete="off"
                required
                className={inputClass}
              />
            </Field>

            <Field label="Branch">
              <input
                name="branch"
                value={branch}
                onChange={(event) => setBranch(event.target.value)}
                placeholder="main"
                autoComplete="off"
                required
                className={inputClass}
              />
            </Field>

            <Field
              label="Release tag"
              hint="Optional. Pins one revision and names it, so releases can be ordered."
            >
              <input
                name="revision"
                value={revision}
                onChange={(event) => setRevision(event.target.value)}
                placeholder="v1.4.0"
                autoComplete="off"
                className={inputClass}
              />
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-5">
            <Button type="submit" variant="primary" disabled={isSubmitting}>
              {isSubmitting ? 'Cloning…' : revision.trim() ? 'Add release' : 'Add repository'}
            </Button>
            {isSubmitting && <Spinner label="cloning and analysing, this takes a moment" />}
          </div>

          {submitError && <ErrorState message={submitError} />}
        </form>
      </Card>

      {result && <IngestReport result={result} />}

      <Card
        title="In the workspace"
        action={<span className="font-mono text-xs text-ink-4">{repositories.length}</span>}
      >
        {error && <ErrorState message={error} onRetry={reload} />}

        {isLoading && !error && <Spinner label="reading the workspace" />}

        {!isLoading && !error && repositories.length === 0 && (
          <EmptyState
            title="Nothing here yet"
            body="Add a repository above. Nothing else in the application has anything to show until one is here."
          />
        )}

        <ul className="flex flex-col">
          {repositories.map((item) => (
            <li
              key={item.id}
              className="flex flex-wrap items-center justify-between gap-5 border-b border-line py-5 first:pt-0 last:border-b-0 last:pb-0"
            >
              <div className="flex min-w-0 flex-col gap-1.5">
                <span className="truncate font-mono text-sm text-ink">{item.url}</span>
                <span className="font-mono text-xs text-ink-4">
                  {item.release_tag ?? item.branch} · {item.commit.slice(0, 7)}
                </span>
              </div>

              <div className="flex items-center gap-3">
                {repository?.id === item.id ? (
                  <Pill tone="ok">selected</Pill>
                ) : (
                  <Button size="sm" variant="quiet" onClick={() => select(item.id)}>
                    Select
                  </Button>
                )}
                <Button
                  size="sm"
                  onClick={() => drop(item.id)}
                  disabled={removingId === item.id}
                >
                  {removingId === item.id ? 'Removing…' : 'Remove'}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </>
  )
}
