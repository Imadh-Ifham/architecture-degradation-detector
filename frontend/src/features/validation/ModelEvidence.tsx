/**
 * Whether a model answered, and what it was asked.
 *
 * Description:
 *   The rest of this screen reports what the system concluded. This one
 *   reports whether a language model had anything to do with it, and it
 *   exists because that could not be told from the screen.
 *
 *   **A keyless run and a working one look identical.** With no key the
 *   reasoner's ladder ends at a deterministic table, every governed fact
 *   still gets a verdict, and the table agrees with the model on the easy
 *   ones — so the buckets, the counts and the confidence all come out the
 *   same. The only thing that differs is the calls, which nothing published.
 *   Two panels here close that gap from opposite ends.
 *
 *   **The transcript is the run's own record**, written when the run was
 *   made: every request in full, every answer as it parsed, and which model
 *   the provider said replied. A call marked `replayed` came from the
 *   response cache, which is still a model's answer to the identical question
 *   and not the table's — the two words are kept apart because a warm cache
 *   makes a real run report zero live calls, and that reads as "no model" to
 *   anybody who was not told otherwise.
 *
 *   **The probe is about now.** Every figure above it can be satisfied by an
 *   answer a model gave last week. The probe asks each configured model a
 *   trivial question on this press, past the cache, and shows the request and
 *   the reply — which is the only thing on the screen that proves this
 *   installation can reach a model at all.
 */

import { useState } from 'react'
import { Button, Card, EmptyState, Pill, Spinner } from '../../components/ui'
import {
  checkModelAccess,
  messageOf,
  readTranscript,
  type ModelAccess,
  type ModelCall,
  type ModelProbe,
  type ModelTranscript,
} from '../../lib/api'
import { useRequest } from '../../lib/useRequest'

export default function ModelEvidence({
  repositoryKey,
  release,
  runId,
}: {
  repositoryKey: string
  release: string
  runId?: string
}) {
  const transcript = useRequest(
    (options) => readTranscript(repositoryKey, release, options),
    [repositoryKey, release, runId],
    Boolean(repositoryKey && release),
  )

  return (
    <div className="flex flex-col gap-7">
      <Transcript state={transcript} />
      <LiveCheck />
    </div>
  )
}

function Transcript({
  state,
}: {
  state: { data: ModelTranscript | null; isLoading: boolean; error: string | null }
}) {
  const document = state.data

  return (
    <Card
      title="What the models were asked, and what they said"
      action={
        document && (
          <span className="font-mono text-xs text-ink-4">
            run {document.run_id} · {document.base_url}
          </span>
        )
      }
    >
      {state.isLoading && <Spinner label="reading this run's calls" />}

      {!state.isLoading && !document && (
        <EmptyState
          title="No transcript for this release"
          body={
            state.error ??
            'Run the validation again and every call it makes is recorded with the request text and the answer.'
          }
        />
      )}

      {document && <Calls document={document} />}
    </Card>
  )
}

function Calls({ document }: { document: ModelTranscript }) {
  const [task, setTask] = useState<string>('all')
  const [opened, setOpened] = useState<number | null>(null)

  const tasks = ['all', ...new Set(document.calls.map((call) => call.task))]
  const shown =
    task === 'all'
      ? document.calls
      : document.calls.filter((call) => call.task === task)

  return (
    <div className="flex flex-col gap-7">
      <Verdict document={document} />

      {document.calls.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-2.5">
            {tasks.map((name) => (
              <button
                key={name}
                onClick={() => setTask(name)}
                className={`rounded-full border px-3 py-1 font-mono text-xs transition ${
                  task === name
                    ? 'border-line-strong bg-raised text-ink'
                    : 'border-line text-ink-3 hover:border-line-strong'
                }`}
              >
                {name.replace(/_/g, ' ')}
              </button>
            ))}
          </div>

          <ol className="flex flex-col gap-px overflow-hidden rounded-control border border-line bg-line">
            {shown.map((call) => (
              <Call
                key={call.sequence}
                call={call}
                isOpen={opened === call.sequence}
                onToggle={() =>
                  setOpened(opened === call.sequence ? null : call.sequence)
                }
              />
            ))}
          </ol>
        </>
      )}
    </div>
  )
}

/**
 * The sentence a reader needs before any individual call is worth opening.
 *
 * Written from the counts rather than chosen from a list of phrasings, so the
 * three situations that look alike on the rest of the screen cannot share a
 * sentence here: a model answered on this run, a model answered earlier and
 * this run replayed it, or nothing answered and the table decided.
 */
function Verdict({ document }: { document: ModelTranscript }) {
  const { live, replayed, unavailable, calls } = document.summary

  const answered = live > 0 || replayed > 0
  const tone = live > 0 ? 'ok' : replayed > 0 ? 'ai' : 'bad'

  const sentence =
    live > 0
      ? `${live} of these calls were answered by a model while this run was happening.`
      : replayed > 0
        ? `No call was made on this run: all ${replayed} answers were replayed from the cache of an identical question, which a model answered earlier. The answers are a model's; the calls are not.`
        : calls > 0
          ? 'Every call failed. Each verdict in this run came from the deterministic table, not from a model.'
          : 'This run made no model call at all. Nothing governed reached a model.'

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-4">
        <Pill tone={tone}>{answered ? 'a model answered' : 'no model answered'}</Pill>
        {!document.key_configured && <Pill tone="bad">no key was configured</Pill>}
        <Pill>{document.schema_mode} schema</Pill>
        <Pill>temperature {document.temperature}</Pill>
      </div>

      <p className="max-w-prose text-sm leading-relaxed text-ink-2">{sentence}</p>

      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
        <Count term="calls" value={calls} />
        <Count term="answered live" value={live} tone={live > 0 ? 'ok' : undefined} />
        <Count term="replayed from cache" value={replayed} />
        <Count
          term="unanswered"
          value={unavailable}
          tone={unavailable > 0 ? 'bad' : undefined}
        />
        <Count term="prompt tokens" value={document.summary.prompt_tokens} />
        <Count term="answer tokens" value={document.summary.completion_tokens} />
      </dl>
    </div>
  )
}

function Count({
  term,
  value,
  tone,
}: {
  term: string
  value: number
  tone?: 'ok' | 'bad'
}) {
  const colour = tone === 'ok' ? 'text-ok' : tone === 'bad' ? 'text-bad' : 'text-ink'

  return (
    <div className="flex flex-col gap-1 bg-panel px-4 py-3">
      <dt className="text-[11px] leading-tight text-ink-4">{term}</dt>
      <dd className={`font-mono text-lg leading-none ${colour}`}>{value}</dd>
    </div>
  )
}

function Call({
  call,
  isOpen,
  onToggle,
}: {
  call: ModelCall
  isOpen: boolean
  onToggle: () => void
}) {
  return (
    <li className="bg-panel">
      <button
        onClick={onToggle}
        className="flex w-full flex-wrap items-center justify-between gap-4 px-4 py-3 text-left transition hover:bg-raised/50"
      >
        <span className="flex min-w-0 items-center gap-3">
          <span className="font-mono text-[11px] text-ink-4">
            {String(call.sequence).padStart(3, '0')}
          </span>
          <span className="font-mono text-xs text-ink-2">
            {call.task.replace(/_/g, ' ')}
          </span>
          <span className="font-mono text-xs text-ai">{call.answered_model}</span>
        </span>

        <span className="flex shrink-0 items-center gap-3">
          <Outcome call={call} />
          <span className="font-mono text-[11px] text-ink-4">{call.latency_ms} ms</span>
        </span>
      </button>

      {isOpen && (
        <div className="flex flex-col gap-6 border-t border-line bg-sunken px-4 py-6">
          <Pair term="asked for" detail={`task ${call.task}`} />
          <Pair
            term="model"
            detail={
              call.requested_model === call.answered_model
                ? `${call.answered_model} — the model configuration named, and the one the provider reported`
                : `asked ${call.requested_model}, answered by ${call.answered_model}`
            }
          />
          <Pair
            term="prompt"
            detail={`${call.prompt_version} · evidence ${call.evidence_hash}`}
          />

          <Block label="sent to the model">{call.prompt}</Block>

          <Block label={call.response ? 'came back' : 'nothing came back'}>
            {call.response
              ? JSON.stringify(call.response, null, 2)
              : (call.error ?? 'no answer and no reason recorded')}
          </Block>
        </div>
      )}
    </li>
  )
}

function Outcome({ call }: { call: ModelCall }) {
  switch (call.outcome) {
    case 'answered':
      return <Pill tone="ok">answered live</Pill>
    case 'replayed':
      return <Pill tone="ai">replayed from cache</Pill>
    case 'unusable':
      return <Pill tone="bad">answer unreadable</Pill>
    default:
      return <Pill tone="bad">no answer</Pill>
  }
}

function Pair({ term, detail }: { term: string; detail: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-3">
      <span className="w-24 shrink-0 text-xs tracking-wide text-ink-4">{term}</span>
      <span className="font-mono text-xs break-words text-ink-2">{detail}</span>
    </div>
  )
}

function Block({ label, children }: { label: string; children: string }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs tracking-wide text-ink-4">{label}</span>
      <pre className="max-h-96 overflow-auto rounded-control border border-line bg-panel px-4 py-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-ink-2">
        {children}
      </pre>
    </div>
  )
}

/**
 * One trivial question to every configured model, on this press.
 *
 * Kept separate from the transcript because it answers a different question.
 * The transcript says what happened; this says what would happen now, and the
 * two disagree exactly when something has changed since the run — a key that
 * expired, a model the provider stopped serving, a machine with no network.
 */
function LiveCheck() {
  const [result, setResult] = useState<ModelAccess | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  async function check() {
    setIsRunning(true)
    setError(null)
    try {
      setResult(await checkModelAccess())
    } catch (cause) {
      setError(messageOf(cause))
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <Card
      title="Can this machine reach a model right now"
      action={
        <Button variant="primary" size="sm" onClick={check} disabled={isRunning}>
          {isRunning ? 'asking…' : result ? 'ask again' : 'ask every model now'}
        </Button>
      }
    >
      <div className="flex flex-col gap-7">
        <div className="flex max-w-prose flex-col gap-3 text-sm leading-relaxed text-ink-3">
          <p>
            One real call per configured model, past the response cache. It is
            the only thing on this screen that is about the present: everything
            above it can be satisfied by an answer a model gave on an earlier
            run.
          </p>
          <p className="text-xs text-ink-4">
            Every slot is sent the <em>same</em> question, which is the
            reasoner&rsquo;s. That is what makes it a reachability check — it
            establishes that the endpoint answers, that the model is still
            served under the name it was asked for, and that strict schema
            decoding works. It is deliberately <em>not</em> each model doing
            its configured job, so a surprising answer here is not a result
            about that model&rsquo;s real task. The verifier in particular is
            prompted to criticise an argument, not to reach a verdict.
          </p>
        </div>

        {isRunning && <Spinner label="calling each configured model" />}

        {error && (
          <p className="max-w-prose border-l-2 border-bad/60 pl-4 text-sm leading-relaxed text-bad">
            {error}
          </p>
        )}

        {result && <Probes result={result} />}
      </div>
    </Card>
  )
}

function Probes({ result }: { result: ModelAccess }) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-4">
        <Pill tone={result.reachable === result.probed.length ? 'ok' : 'bad'}>
          {result.reachable} of {result.probed.length} answered
        </Pill>
        <Pill tone={result.key_configured ? 'neutral' : 'bad'}>
          {result.key_configured ? 'a key is set' : 'no key is set'}
        </Pill>
        <span className="font-mono text-xs text-ink-4">{result.base_url}</span>
      </div>

      {result.arbiter_only_allowed && (
        <p className="max-w-prose border-l-2 border-warn/60 pl-4 text-xs leading-relaxed text-warn">
          This deployment permits a verdict with no model behind it. That is the
          demonstration's rollback and it is why a run with no key still
          produces verdicts — so a published figure from such a run describes
          the deterministic table rather than a model. Turn it off for any run
          whose numbers get reported.
        </p>
      )}

      <div className="flex flex-col gap-px overflow-hidden rounded-control border border-line bg-line">
        {result.probed.map((probe) => (
          <Probe key={probe.task} probe={probe} />
        ))}
      </div>
    </div>
  )
}

function Probe({ probe }: { probe: ModelProbe }) {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <div className="bg-panel">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full flex-wrap items-center justify-between gap-4 px-4 py-3 text-left transition hover:bg-raised/50"
      >
        <span className="flex min-w-0 items-center gap-3">
          <span className="font-mono text-xs text-ink-3">
            {probe.task.replace(/_/g, ' ')}
          </span>
          <span className="font-mono text-xs text-ai">{probe.requested_model}</span>
        </span>

        <span className="flex shrink-0 items-center gap-3">
          {probe.strict_schema && <Pill>strict schema</Pill>}
          <Pill tone={probe.reachable ? 'ok' : 'bad'}>
            {probe.reachable ? 'answered' : 'did not answer'}
          </Pill>
          <span className="font-mono text-[11px] text-ink-4">{probe.latency_ms} ms</span>
        </span>
      </button>

      {isOpen && (
        <div className="flex flex-col gap-6 border-t border-line bg-sunken px-4 py-6">
          <Block label="sent">{probe.prompt}</Block>
          <Block label={probe.reachable ? 'came back' : 'why it did not answer'}>
            {probe.response
              ? JSON.stringify(probe.response, null, 2)
              : (probe.error ?? 'no reason recorded')}
          </Block>
        </div>
      )}
    </div>
  )
}
