/**
 * Repository ingestion form and list.
 *
 * Author: Imadh Ifham
 * Date: 2026-10-13
 * Description:
 *   Lets a developer clone a repository (url + branch) into the backend
 *   workspace, list what is already ingested, and remove entries again.
 */

import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  ingestRepository,
  listRepositories,
  removeRepository,
  type IngestedRepository,
} from '../lib/api'

const inputClassName =
  'w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none'

/** Form to ingest a repository, plus the list of ingested repositories. */
export default function RepositoryIngestion() {
  const [url, setUrl] = useState('')
  const [branch, setBranch] = useState('')
  const [repositories, setRepositories] = useState<IngestedRepository[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  // `reloadToken` is the refresh trigger: bumping it re-runs this effect and
  // refetches the list after an ingest or a removal.
  useEffect(() => {
    const controller = new AbortController()

    listRepositories(controller.signal)
      .then((items) => {
        setRepositories(items)
        setListError(null)
      })
      .catch((cause: unknown) => {
        // An abort means the component unmounted; it is not a real failure.
        if (controller.signal.aborted) return

        setListError(cause instanceof Error ? cause.message : String(cause))
      })

    return () => controller.abort()
  }, [reloadToken])

  /** Bump the refresh token so the list effect runs again. */
  const reload = useCallback(() => setReloadToken((current) => current + 1), [])

  /** Clone the entered repository, then refresh the list on success. */
  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()

      setIsSubmitting(true)
      setSubmitError(null)

      try {
        await ingestRepository({ url, branch })
        setUrl('')
        setBranch('')
        reload()
      } catch (cause) {
        // Surfaces the backend detail, for example an unknown branch.
        setSubmitError(cause instanceof Error ? cause.message : String(cause))
      } finally {
        setIsSubmitting(false)
      }
    },
    [url, branch, reload],
  )

  /** Remove one ingested repository, then refresh the list. */
  const handleRemove = useCallback(
    async (repositoryId: string) => {
      setRemovingId(repositoryId)
      setListError(null)

      try {
        await removeRepository(repositoryId)
        reload()
      } catch (cause) {
        setListError(cause instanceof Error ? cause.message : String(cause))
      } finally {
        setRemovingId(null)
      }
    },
    [reload],
  )

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight text-white">
          Repository Ingestion
        </h1>
        <p className="text-slate-400">
          Clone a repository into the server workspace.
        </p>
      </header>

      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-xl border border-slate-800 bg-slate-900/60 p-6"
      >
        <div className="grid gap-4 sm:grid-cols-[2fr_1fr]">
          <label className="block space-y-1.5">
            <span className="text-sm text-slate-400">Repository URL</span>
            <input
              name="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://github.com/GoogleCloudPlatform/microservices-demo.git"
              autoComplete="off"
              required
              className={inputClassName}
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-sm text-slate-400">Branch</span>
            <input
              name="branch"
              value={branch}
              onChange={(event) => setBranch(event.target.value)}
              placeholder="main"
              autoComplete="off"
              required
              className={inputClassName}
            />
          </label>
        </div>

        <div className="flex items-center gap-4">
          <button
            type="submit"
            disabled={isSubmitting}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSubmitting ? 'Ingesting…' : 'Ingest repository'}
          </button>

          {isSubmitting && (
            <span className="text-sm text-slate-400">
              Cloning the branch, this can take a moment…
            </span>
          )}
        </div>

        {submitError && <p className="text-sm text-red-400">{submitError}</p>}
      </form>

      <div className="space-y-3">
        <h2 className="text-sm font-medium tracking-wide text-slate-400 uppercase">
          Ingested repositories ({repositories.length})
        </h2>

        {listError && <p className="text-sm text-red-400">{listError}</p>}

        {repositories.length === 0 && !listError && (
          <p className="text-sm text-slate-500">Nothing ingested yet.</p>
        )}

        <ul className="space-y-2">
          {repositories.map((repository) => (
            <li
              key={repository.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3"
            >
              <div className="min-w-0 space-y-0.5">
                <p className="truncate font-mono text-sm text-slate-100">
                  {repository.url}
                </p>
                <p className="font-mono text-xs text-slate-500">
                  {repository.branch} @ {repository.commit.slice(0, 7)}
                </p>
              </div>

              <button
                type="button"
                onClick={() => handleRemove(repository.id)}
                disabled={removingId === repository.id}
                className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-200 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {removingId === repository.id ? 'Removing…' : 'Remove'}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
