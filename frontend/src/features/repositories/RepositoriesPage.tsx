/**
 * Repository setup.
 *
 * Description:
 *   Add a system to analyse, see what is already here, and remove one again.
 *
 *   **Saving is setup, and setup clones nothing.** A snapshot is a url, a
 *   branch and a release tag written down for a later run; the pipeline is
 *   the only thing that clones, recovers and validates. Submitting this form
 *   used to start a clone and six analysis stages, which made writing down a
 *   release the most expensive thing on the screen and made the run itself
 *   invisible.
 *
 *   **A branch and a release tag are both part of a snapshot's identity.**
 *   The tag names the revision recovery analyses and is what validation
 *   compares releases by, so it is required here rather than discovered
 *   missing at the end of a run.
 */

import { useCallback, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
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
import { messageOf, removeRepository, type RepositoryConfiguration } from '../../lib/api'
import { useWorkspace } from '../../workspace/useWorkspace'

export default function RepositoriesPage() {
  const {
    repositories,
    repositoryKey,
    isLoading,
    error,
    selectRepository,
    reload,
    configurations,
    configurationsError,
    isLoadingConfigurations,
    addConfiguration,
    removeConfiguration,
    startPipeline,
    isPipelineRunning,
    pipelineSnapshots,
    pipelineError,
  } = useWorkspace()

  const navigate = useNavigate()

  // Recovery has to happen before the decisions screen can report what any
  // release would be judged against, so the button that goes there runs it.
  // The progress is named rather than hidden behind a spinner: cloning ten
  // releases is minutes, and a button that looks stuck is a button somebody
  // presses twice.
  const working = pipelineSnapshots.find(
    (snapshot) => snapshot.phase === 'ingesting' || snapshot.phase === 'recovering',
  )
  const recoveryProgress = working
    ? `${working.phase === 'ingesting' ? 'cloning' : 'recovering'} ${
        pipelineSnapshots.indexOf(working) + 1
      } of ${pipelineSnapshots.length} — ${working.configuration.release_tag}`
    : 'starting'

  const goToDecisions = async () => {
    if (await startPipeline()) navigate('/decisions')
  }

  const [url, setUrl] = useState('')
  const [branch, setBranch] = useState('main')
  const [releaseTag, setReleaseTag] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [saved, setSaved] = useState<RepositoryConfiguration | null>(null)
  const [removingConfiguration, setRemovingConfiguration] = useState<string | null>(
    null,
  )
  const [removingRepository, setRemovingRepository] = useState<string | null>(null)
  const [workspaceError, setWorkspaceError] = useState<string | null>(null)

  const submit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      setIsSaving(true)
      setSubmitError(null)
      setSaved(null)

      try {
        setSaved(
          await addConfiguration({
            url,
            branch,
            release_tag: releaseTag.trim(),
          }),
        )
        // The url and branch usually describe a system more than one release
        // of it belongs to, so only the tag is cleared.
        setReleaseTag('')
      } catch (cause) {
        // The backend says which field is unusable; a generic message here
        // would throw that away.
        setSubmitError(messageOf(cause))
      } finally {
        setIsSaving(false)
      }
    },
    [addConfiguration, url, branch, releaseTag],
  )

  const dropConfiguration = useCallback(
    async (configurationId: string) => {
      setRemovingConfiguration(configurationId)
      setWorkspaceError(null)

      try {
        await removeConfiguration(configurationId)
      } catch (cause) {
        setWorkspaceError(messageOf(cause))
      } finally {
        setRemovingConfiguration(null)
      }
    },
    [removeConfiguration],
  )

  const dropRepository = useCallback(
    async (repositoryId: string) => {
      setRemovingRepository(repositoryId)
      setWorkspaceError(null)

      try {
        await removeRepository(repositoryId)
        reload()
      } catch (cause) {
        setWorkspaceError(messageOf(cause))
      } finally {
        setRemovingRepository(null)
      }
    },
    [reload],
  )

  return (
    <>
      <PageHeading
        eyebrow="sources"
        title="Repositories"
        description="A snapshot is a repository url, a branch and the release tag that names the revision. Configuring one records what should be analysed; nothing is cloned until the pipeline runs."
      />

      <Card title="Configure a snapshot">
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
              hint="Names the revision analysed, and orders it against the others."
            >
              <input
                name="release_tag"
                value={releaseTag}
                onChange={(event) => setReleaseTag(event.target.value)}
                placeholder="v1.4.0"
                autoComplete="off"
                required
                className={inputClass}
              />
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-5">
            <Button type="submit" variant="primary" disabled={isSaving}>
              {isSaving ? 'Saving…' : 'Save snapshot'}
            </Button>
            {isSaving && <Spinner label="writing the configuration" />}
            <span className="text-xs text-ink-4">
              Nothing is cloned here. The pipeline does that when you run it.
            </span>
          </div>

          {submitError && <ErrorState message={submitError} />}

          {saved && (
            <p className="flex flex-wrap items-center gap-3 text-sm text-ink-2">
              <Pill tone="ok">saved</Pill>
              <span className="font-mono text-xs">
                {saved.release_tag} · {saved.branch}
              </span>
              {/* No shortcut to the pipeline from here. A release reaches it
                  through the decisions screen, because the pipeline validates
                  against the source chosen for each release and there is no
                  source until somebody chooses one. A link that skipped that
                  led to a stack the pipeline could do nothing with. */}
              <span className="text-xs text-ink-4">
                add another, or choose what they are judged against below
              </span>
            </p>
          )}
        </form>
      </Card>

      <Card
        title="Configured snapshots"
        action={
          <span className="font-mono text-xs text-ink-4">{configurations.length}</span>
        }
      >
        {configurationsError && (
          <ErrorState message={configurationsError} onRetry={reload} />
        )}

        {isLoadingConfigurations && !configurationsError && (
          <Spinner label="reading the configured snapshots" />
        )}

        {!isLoadingConfigurations && !configurationsError && configurations.length === 0 && (
          <EmptyState
            title="Nothing configured yet"
            body="Configure a snapshot above. The pipeline runs every configured snapshot in the order they appear here."
          />
        )}

        <ol className="flex flex-col">
          {configurations.map((snapshot, index) => (
            <li
              key={snapshot.id}
              className="flex flex-wrap items-center justify-between gap-5 border-b border-line py-5 first:pt-0 last:border-b-0 last:pb-0"
            >
              <div className="flex min-w-0 items-center gap-4">
                <span className="font-mono text-xs text-ink-4">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <div className="flex min-w-0 flex-col gap-1.5">
                  <span className="truncate font-mono text-sm text-ink">
                    {snapshot.url}
                  </span>
                  <span className="font-mono text-xs text-ink-4">
                    {snapshot.branch} · {snapshot.release_tag}
                  </span>
                </div>
              </div>

              <Button
                size="sm"
                onClick={() => dropConfiguration(snapshot.id)}
                disabled={removingConfiguration === snapshot.id}
              >
                {removingConfiguration === snapshot.id ? 'Removing…' : 'Remove'}
              </Button>
            </li>
          ))}
        </ol>

        {configurations.length > 0 && (
          <div className="mt-7 flex flex-col gap-4 border-t border-line pt-6">
            <div className="flex flex-wrap items-center gap-5">
              <Button
                variant="primary"
                size="sm"
                disabled={isPipelineRunning}
                onClick={goToDecisions}
              >
                {isPipelineRunning ? 'Recovering…' : 'Select the decision knowledge'}
              </Button>
              {isPipelineRunning && <Spinner label={recoveryProgress} />}
            </div>

            <p className="max-w-prose text-xs leading-relaxed text-ink-4">
              {/* Said plainly because the button does more than its name. A
                  release has to be recovered before anything can report what
                  it would be judged against, and cloning several is minutes
                  rather than seconds. */}
              Each configured release is cloned and recovered first — what a
              release is judged against cannot be read until it exists. Then
              you choose, per release, on the decisions screen.
            </p>

            {pipelineError && <ErrorState message={pipelineError} />}
          </div>
        )}
      </Card>

      <Card
        title="Clones in the workspace"
        action={<span className="font-mono text-xs text-ink-4">{repositories.length}</span>}
      >
        {error && <ErrorState message={error} onRetry={reload} />}
        {workspaceError && <ErrorState message={workspaceError} />}

        {isLoading && !error && <Spinner label="reading the workspace" />}

        {!isLoading && !error && repositories.length === 0 && (
          <EmptyState
            title="Nothing cloned yet"
            body="A clone appears here once the pipeline has run for the snapshot that produces it. Every result screen reads what a clone was analysed into."
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
                {(item.repository_id ?? item.id) === repositoryKey ? (
                  <Pill tone="ok">selected</Pill>
                ) : (
                  <Button
                    size="sm"
                    variant="quiet"
                    onClick={() => selectRepository(item.repository_id ?? item.id)}
                  >
                    Select
                  </Button>
                )}
                <Button
                  size="sm"
                  onClick={() => dropRepository(item.id)}
                  disabled={removingRepository === item.id}
                >
                  {removingRepository === item.id ? 'Removing…' : 'Remove'}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </>
  )
}
