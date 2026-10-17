# Model access in architecture validation — design, configuration and measured behaviour

- **Project:** J26-SE-332 · Detection of Architecture Degradation in Maintenance-Phase Software Systems (SLIIT IT4010)
- **Component:** C2 — Architecture Validation · Owner: Aman Mohamed M.A (IT23187078)
- **Status:** Implemented and verified against the live provider on 17–18 Oct 2026
- **Version:** 1.0 · 18 Oct 2026
- **Covers:** every language-model call the backend makes — how the provider is reached, which model
  answers which task, what the model is and is not allowed to decide, and what has been measured
- **Code:** `backend/app/infrastructure/ai/`, and the reasoning stage at
  `backend/app/components/architecture_validation/validation_reasoning/`

## 1. Where a model is used, and where it deliberately is not

The validation component runs eight stages in order. Six of them are deterministic: the same input
produces the same output with no network call. Only two consult a language model.

| # | Stage | Model | Built |
| --- | --- | --- | --- |
| 1 | `observation_normalization` | no | yes |
| 2 | `decision_knowledge` | no | yes |
| 3 | `evidence_retrieval` | no | yes |
| 4 | `validation_reasoning` | **yes** | yes |
| 5 | `independent_verification` | **yes** | not yet |
| 6 | `classification` | no | not yet |
| 7 | `architect_review` | no | not yet |
| 8 | `graph_publishing` | no | not yet |

That split is a design position rather than an accident of sequencing. Recovering decision records
from configuration, assembling an evidence package, ordering releases and resolving which decision
supersedes which are all problems with correct answers that can be computed, and a model asked to do
any of them would introduce variance into a result that has none. The model is asked exactly one
question, on a packet of evidence that has already been retrieved, hashed and sealed: *does this
observed dependency obey this recorded decision?*

Keeping that boundary sharp has a second effect that matters for the research claim. Because stages
1–3 are deterministic, a disagreement between two runs can only have come from stage 4 or 5, which
makes the model's contribution measurable instead of diffuse.

## 2. The model decision

### 2.1 The one hard requirement

The provider must support **strict JSON-schema output**, also called constrained decoding. A model
without it is not a slower option here; it is a different design, because the failure semantics
change (§4).

### 2.2 What was chosen

A **free, open-weights model reached over an OpenAI-compatible HTTP endpoint**, rather than a
commercial frontier API. Four reasons, in the order they carry weight:

1. **The task shape suits a small model.** This is constrained classification over supplied
   evidence. The output vocabulary is five fixed values, the evidence is already retrieved, and the
   question concerns one pair of elements. The model is not reasoning open-endedly over a
   repository; it is judging a sealed packet. Small models close most of the quality gap on that
   shape.
2. **A weaker model exercises the safeguards that are the actual contribution.** The checks in §6
   exist because a model can produce a confident answer with no basis for it. A frontier model would
   be right often enough to hide a broken check. For a component whose contribution is the checking,
   a weaker model is an advantage during development.
3. **Model choice becomes a variable the evaluation can sweep.** Running the same corpus through
   several models is a configuration change and a reportable result. At per-call commercial pricing
   across a corpus it would not have been affordable.
4. **Published weights can be re-run by a third party.** Open weights remain available for
   independent replication in a way that a hosted frontier model, which will have been retired or
   replaced, does not.

The accepted cost, stated rather than hidden: lower agreement rates and more `insufficient_evidence`
outcomes than a frontier model would produce. Those are numbers to report in the evaluation's
threats-to-validity section.

### 2.3 Why one HTTP request and no vendor SDK

Chat completion against these providers is a single `POST` with a JSON body. An SDK earns its place
for streaming, tool-calling loops and multimodal payloads, none of which this component uses, and it
brings that vendor's authentication, error hierarchy and defaults with it — which quietly makes
changing provider harder than changing a URL. The client is `httpx` and the adapter is one file.

## 3. What is configured

### 3.1 Models

| Role | Model | Why this one |
| --- | --- | --- |
| Reasoner (stage 4) | `openai/gpt-oss-20b` | Open weights under Apache 2.0, on the provider's strict-schema list, 131 072-token context, sub-second responses |
| Verifier (stage 5) | `qwen/qwen3.8-27b` | **A different model family**, so it does not share the reasoner's training mix or its blind spots. Same provider, so one credential |
| Second attempt | `openai/gpt-oss-120b` | Same API and same strict support, larger sibling. Reached without new configuration |
| Offline attempt | `llama3.2:3b` | A local runtime, for a venue with no network. Sized for 4 GB of video memory |

Two different families for stages 4 and 5 is the point of having stage 5 at all: a verifier with the
reasoner's own weights would mostly agree with it, and the agreement would mean nothing.

### 3.2 Request parameters

| Parameter | Value | Reason |
| --- | --- | --- |
| `temperature` | `0.0` | A verdict that changes between two runs over identical evidence is not a verdict. This is not a conversational application |
| `seed` | `42` | Fixes tie-breaking when two continuations are near-equally likely |
| `response_format` | strict JSON schema | §4 |
| `timeout` | 60 s | One slow response cannot stall a run |
| retries | 1 identical retry | §6 |

Temperature and seed remove the *avoidable* variation. They do not make a hosted model
deterministic: server-side batching, floating-point reduction order on a GPU, and a provider
redeploying a model under an unchanged name all still move the output. The defensible claim is
therefore *every available control is applied, and the residual variation is measured* — which is
why each verdict records the model identifier the provider **reported** rather than the one that was
requested.

### 3.3 Credentials

The API key is read from the environment and from nowhere else. There is no default value for it in
code: a key written into a settings default is a key that gets committed, and a committed secret
remains in the history after it is deleted. `backend/.env` is not tracked, and `backend/.env.example`
carries the variable names with empty values so that a fresh clone states what has to be supplied.

### 3.4 The two switches the fallback ladder needs

| Field | Default | What it decides |
| --- | --- | --- |
| local endpoint URL | unset | Where the offline rung asks. Unset means no local runtime is installed, and that rung reports itself unavailable rather than sending a local model identifier to the hosted endpoint (§7) |
| allow a verdict from the table alone | permitted | Whether the component may produce a verdict with no model behind it |

The second field is one setting with two opposite correct values, which is why it is a setting. In
a demonstration it must be permitted: that rung is the rollback for a venue with no usable network,
and the verdicts it produces are honest about having no model behind them. In any run whose numbers
are reported it must be refused, because without a credential *every* governed fact degrades to the
table, each verdict truthfully says so, and an aggregate drawn from that run would describe the
deterministic table while being read as describing a model. Nothing in the output would be false;
the summary would be. So such a run stops, naming the fact it stopped on.

It is passed to the reasoning stage as an argument rather than read there from configuration, for
the same reason the prompt and the ladder's rungs are: that stage reads no files and names no
models, and composition is done at the application's edge.

## 4. Structured output is what makes a model a component

A JSON schema can be handed to the provider and enforced *during* generation: at each step the
decoder is restricted to tokens that keep the output valid. The provider documents two modes, and
the difference is not cosmetic.

| Mode | Behaviour | Usable here |
| --- | --- | --- |
| **strict** | Constrained decoding. The provider documents that output cannot violate the schema and that schema-validation error handling is unnecessary | **required** |
| best-effort | The model is asked to comply and the provider returns HTTP 400 when it does not | no |

Best-effort is unusable for this component specifically. It converts a content problem into a
transport error, so *the model gave an unusable answer* and *the request failed* arrive as the same
event — and the retry policy then reasons about the wrong failure. The component raises rather than
downgrading to best-effort if a configured model lacks strict support, because a silent downgrade is
the failure this design is least able to detect.

Two consequences shape the code:

- **Strict mode constrains the schema as well as the output.** Every property must be listed as
  required and every object must forbid additional properties; an optional field is expressed as a
  union with null rather than by being omitted. A schema generated from an ordinary dataclass
  satisfies none of those, so the adapter rewrites it on the way out. This keeps provider
  requirements out of the component's data models.
- **Field order was expected to be free accuracy, and measurement says it is not available.** The
  intent was to declare `reasoning` and the citation list before `verdict`, so that the model works
  through the evidence and only then names a conclusion. The schema does declare them in that order
  and the rewriting step preserves it, which was verified by inspecting the request. The provider
  nevertheless returns `verdict` first, identically across repeated calls at temperature zero, so
  constrained decoding here enforces the schema's *content* and not its field order. The claim is
  therefore withdrawn rather than restated: see §9.4 for the measurement and what it does and does
  not cost.

## 5. How model access is arranged in the code

Four layers, each knowing less than the one below it.

```
validation_reasoning/service.py     knows: a task name, a prompt, a schema
    |                               does not know: model, provider, URL, credential
    v
ConfiguredAIClient                  task -> model, strict-support check,
infrastructure/ai/interface.py      response cache, stamps the result
    |
    v
OpenAICompatibleProvider            one HTTP POST, schema rewriting, typed errors
    |
    v
the provider's chat-completions endpoint
```

The reasoning stage's entire interaction with a model is:

```python
result = self._ai.complete(
    task=TASK_PRIMARY_VERDICT,              # a task name, never a model name
    prompt=render(self._prompt, package),   # the sealed package and nothing else
    schema=verdict_schema(),
    prompt_version=self._prompt.version,
    evidence_hash=package.evidence_hash,
)
```

No model identifier, no URL, no credential, no HTTP client import. The component depends on a
Protocol it declares itself and the adapter is injected at the composition root. This satisfies the
architectural rule that no component depends on a particular provider or model *structurally*,
rather than by everyone remembering to be careful — and a test asserts it, because remembering has a
short shelf life.

The task-to-model mapping is the hinge. A component names `primary_verdict`; configuration decides
what answers it. That indirection is what turns the model into an experimental variable, and it is
why the lower rungs of §7 are additional **tasks** rather than model names passed down from a
component.

The prompt lives in a versioned file, `primary_verdict.v1.md`, loaded by the composition root and
passed in; the component holds the shape of the answer and never opens a file. The version is read
from the file name, because a version string that an author has to remember to increment eventually
describes the wrong text. A changed prompt becomes `v2` and `v1` is never edited once results exist.

## 6. What a schema cannot promise, and what checks it

A strict schema guarantees that the verdict is one of five permitted values and that the citation
list is present. It cannot guarantee that the cited references exist: `["ADR-999"]` is perfectly
schema-valid. The provider's own documentation makes the same point, that structured output ensures
schema compliance and not semantic accuracy.

So four checks run in code on every response, and none of them is a model.

| Check | What it catches | Could a schema do it? |
| --- | --- | --- |
| A · shape | the response cannot be read | mostly, yes — this is the exception handler |
| B · citation existence | it cited something that was not in the evidence package | **no, and this is the grounding guarantee** |
| C · citation role | the conclusion rests only on background context, not on a rule | no |
| D · supersession | the conclusion rests on a decision that had been replaced | no |

Check B is set subtraction over the package's reference identifiers. It is the only thing standing
between an invented source and a published result, and it is ten lines.

Above the four sits a **deterministic arbiter**: a small decision table over the closed constraint
vocabulary, with no weights and no model, which judges the same fact independently. Every verdict
records whether the model and the table agreed. Where they disagree, the fact is published for human
review with both answers kept rather than being resolved by either one. This is the answer to *what
if the model is wrong* that does not consist of asking another model.

A rejected response is retried once, identically. If it fails again, the outcome is
`insufficient_evidence` rather than a verdict — an explicit value that is routable downstream, which
a wrong confirmation is not. The design bias throughout is that a false confirmation corrupts the
next component's input silently, while an abstention is visible.

## 7. Availability: the fallback ladder

Model access is a rented network service, so it can be slow, rate-limited, offline, or retired. The
reasoner descends a fixed ladder and every verdict records which rung answered it.

| Rung | What it is | When |
| --- | --- | --- |
| 1 | the response cache | the identical question has been asked before |
| 2 | the configured model, then one identical retry | normal operation |
| 3 | the larger sibling on the same provider | the configured model is unavailable |
| 4 | a local runtime | no network |
| 5 | the deterministic arbiter alone | no model answered; the verdict says so |
| — | `insufficient_evidence` | the arbiter abstains as well |

Rung 5 is the reason a missing credential does not stop a run: the component still produces a
verdict for every governed fact and states on each one that no model was involved. A run that fell
through to the table and reported itself like a normal run would be the failure this design most
wants to avoid, so the stage publishes counts of how many verdicts came from the model, from the
table and from cache.

**Rung 5 is measured rather than asserted.** A test builds the real HTTP adapter, gives it no
credential, points it at a closed local port and judges three recorded facts of the corpus. All
three are decided; each one reports the arbiter as its source, a model identifier of `none`, the
rung it reached, and the governing rule as its citation; and the model-versus-table agreement field
is null rather than *agreed*, because there was no model verdict to compare and a passed check must
never be inferred from a check that did not happen. The test needs no network — a refused connection
on the loopback interface returns immediately — so it runs in the default suite on any machine.

**Rung 4 required a correction that is worth recording, because the defect was invisible by
construction.** A task resolves to a model identifier, and the client held a single provider
adapter, which is the adapter configured for the hosted endpoint. The local rung therefore sent a
local model identifier to the hosted provider, which does not serve it; the resulting
*model not found* response was indistinguishable from an outage, the ladder correctly descended past
it, and every test of the ladder's behaviour passed. The rung existed in configuration and could
never have answered — and installing a local runtime would not have changed that.

The repair makes the endpoint part of what a task resolves to, not an assumption held by the client:
configuration answers *which URL serves this task* alongside *which model serves this task*, and the
client holds one adapter per endpoint. With no local endpoint configured, the rung now reports
itself unavailable and names the setting that would configure it, which is the same outcome the
ladder saw before but for a stated reason rather than by accident. The general point is that **a
fallback path which degrades silently into the next one cannot be shown to work by testing the thing
that consumes it**; it has to be reached directly.

Verification (stage 5) deliberately has **no** fallback ladder. A verifier that falls back to the
reasoner's model is a model agreeing with itself.

## 8. Reproducibility: the response cache

```
key = sha256(task | prompt_version | model_id | schema_mode | evidence_hash)
```

One mechanism addresses four separate problems:

| Problem | How the cache addresses it |
| --- | --- |
| the per-minute token limit | re-running an unchanged release makes zero model calls |
| development cost and speed | the twentieth test run is instant and free |
| **reproducibility** | identical input provably yields the identical verdict |
| demonstration reliability | a warmed cache cannot be broken by a rate limit or a dead network |

Every component of the key is there because changing it must miss: a changed prompt, model, schema
mode, task, or a single character of evidence is a different question, and serving a stale verdict
for a changed question is worse than having no cache. Keying on the evidence hash rather than the
fact identifier is what makes this correct — the same fact with different evidence is a different
question.

There is no invalidation logic, deliberately. Invalidation is achieved by key construction, which
designs out a classic source of subtle bugs rather than implementing it carefully.

Entries are small JSON files under the untracked artifacts directory. A fresh clone starts cold,
which is intended: **the cache is an optimisation and never an input to a result.** Each run reports
how many verdicts came from disk, so *model or cache* is always answerable.

## 9. Measured behaviour

Every figure below was read from the running system on 17–18 Oct 2026, not from documentation.
§12 reproduces all of it.

### 9.1 Provider limits

Identical on all three hosted models:

| Limit | Value | How it was established |
| --- | --- | --- |
| tokens per minute | **8 000** | 73 spent tokens reset in 547 ms; 60 / 8 000 = 7.5 ms per token |
| requests per day | **1 000** | 6 spent requests reset in 518.4 s; 86 400 / 1 000 = 86.4 s per request |

The response headers report a limit and a reset interval but not the period the limit applies over;
dividing one by the other recovers it. Published summaries of this provider's free allowance
disagree with each other and with the account's own headers, which is why the figures are read from
the account.

### 9.2 Latency

| Call | Time |
| --- | --- |
| reasoner, one verdict, cache off | 0.62 – 1.42 s |
| verifier model, one response | 0.46 s |

### 9.3 End-to-end, over a fixed sample of the corpus

Twenty governed facts — all fifteen of release `v0.10.0` and the first five of `v0.9.0`, taken in
corpus order rather than selected — each passed through decision resolution, evidence assembly, the
versioned prompt, the four checks and the arbiter comparison. The response cache was off for the
whole run, and the two pass marks were fixed before the first call.

| Property | Result | Mark set in advance |
| --- | --- | --- |
| responses valid against the strict schema | **20 of 20** | 20 of 20 |
| citations that resolved to a supplied reference | **20 of 20** | 19 of 20 |
| answered by the model rather than by the fallback table | 20 of 20 | — |
| responses that needed the one retry | 0 | — |
| model and arbiter in agreement | **20 of 20** | — |
| seconds per fact | 0.66 min · 1.08 median · 1.39 max | — |

Every verdict carried the reporting model's identifier, the prompt version, the evidence hash and
the references it cited. The citation result is the one to weigh: each package carried the governing
rule plus six to eight items of structural context, and the model cited the rule and nothing else on
all twenty, so the grounding check passed on merit rather than on an empty citation list.

The sample was paced at one call every seven seconds. Twenty rendered packages cost about 16 000
tokens in total against a ceiling of 8 000 a minute (§9.1), so an unpaced run would have exhausted
the minute around the tenth call and the rest would have arrived as rate-limit failures. The
fallback ladder would have absorbed those by moving to another model, and the measurement would then
have described two models and a quota rather than one model.

### 9.4 Field order: a design expectation that measurement withdrew

The schema declares `reasoning` and `cited_evidence_refs` before `verdict` so that the conclusion is
generated last (§4). The request was inspected to confirm the declared order survives schema
rewriting in both `properties` and `required`. It does. The provider still returns `verdict` first,
and did so identically on three consecutive calls at temperature zero.

Constrained decoding here therefore enforces which fields exist, their types and the permitted
values, and leaves emission order to the model. The expectation is withdrawn rather than reworded.

What it costs, stated against the measurement rather than guessed: nothing observable on this
corpus. Agreement with the deterministic table was 20 of 20 with the conclusion generated first, so
on these facts the ordering was not carrying the accuracy it was expected to carry. That is a
finding about this corpus, which is governed by permissive rules that a small model finds easy, and
it should not be generalised to a corpus containing prohibitions. Anything that depends on the model
reasoning before concluding now needs a different mechanism, and two cheap ones remain untested: a
schema whose single top-level field is an object holding the reasoning, and two calls where the
second is given the first's output.

### 9.5 What these measurements do not establish

Twenty facts of one subject system, whose recorded decisions are permissive, every one of which the
model answered `confirms`. The result establishes that the stage is correct end to end and that
strict decoding and grounding hold at this scale. It does not establish behaviour on a fact that
*violates* a rule, because the corpus contains none at these two releases — so the rate at which the
model correctly says `contradicts` is unmeasured, and it is the number a reader will ask for. A
constructed violation is the cheapest way to obtain it and is listed in §11.

## 10. Operating constraints and what they imply

**The limits in §9.1 are per account, not per model or per component.** 8 000 tokens a minute is one
shared budget.

A two-item evidence prompt cost 435–479 tokens. A real package carries three to nine items, so a
cold run of fifteen facts through two models does not fit inside one minute. Three consequences:

- a cold full run has to be paced across several minutes, or run twice with the second run warm
- the daily request ceiling is never the binding constraint; thirty calls is three per cent of it
- the cache is not a performance nicety for a demonstration, it is what makes one possible

Any other component that is given model access shares this budget, which makes an unbounded call
loop in one component an outage for all of them. The shared client is the mitigation: a repeated
question costs nothing, and any heavy iteration runs against the test provider.

## 11. Open items

| Item | State |
| --- | --- |
| The fixed-sample evaluation of the reasoning stage against a pre-set pass bar | **done** — §9.3, both marks met |
| The rate at which the model correctly reports a violation | **unmeasured.** The corpus holds no violating fact at these releases, so a constructed one is needed |
| A mechanism for generating the reasoning before the conclusion, if that property is wanted | open — the declaration-order route does not work on this provider (§9.4) |
| Stage 5, independent verification | not built; the verifier model is configured and reachable |
| Local offline runtime (rung 4) | **reachable and tested as a path; no runtime installed.** The endpoint resolution and the unconfigured case are covered (§7). A local model answering under a strict schema is unmeasured, and needs a runtime installed |
| Two configuration fields for the lower rungs — a local endpoint URL, and a flag to refuse a verdict from the table alone | **written** (§3.4), in the example environment file, and covered by tests |
| Rung 5 verified end to end without a credential | **done** — §7 |
| Licence terms for the verifier model's published weights | **to confirm from the official model repository.** Secondary sources disagree. The reproducibility argument in §2.2 depends on this for the verifier arm, and it is cheap to settle |
| Model access for components other than architecture validation | not agreed. The infrastructure is shared by design and no other component uses it today |

## 12. Reproducing the verification

The model tests are deselected by default, so the suite stays runnable with no credential and no
network. Everything in §9 comes from these commands.

```bash
cd backend
uv run pytest                     # 1403 tests, no credential, no network
uv run pytest -m live -v          # 4 tests against the real provider, about 5 s
```

Individual checks:

```bash
uv run pytest -m live -k "rate_limits"     # prints this account's limits per model
uv run pytest -m live -k "strict_schema"   # both models answer under a strict schema
uv run pytest -m live -k "citation"        # every citation resolves to supplied evidence
```

The credential-failure path, overriding the environment for one run only:

```powershell
# PowerShell
$env:AI_API_KEY = "wrong"; uv run pytest -m live; Remove-Item Env:\AI_API_KEY
```

```bash
# POSIX shell
AI_API_KEY=wrong uv run pytest -m live
```

The provider returns HTTP 401, the adapter raises its unavailable-model error, and that is the
condition the ladder in §7 descends on.

## References

- Groq, *Structured Outputs* — strict and best-effort modes, the strict-mode model list, the
  schema requirements for constrained decoding, and the statement that structured output ensures
  schema compliance rather than semantic accuracy.
  <https://console.groq.com/docs/structured-outputs>
- OpenAI gpt-oss release coverage — `gpt-oss-120b` and `gpt-oss-20b` published 5 Aug 2025 under
  Apache 2.0 as open-weight mixture-of-experts models (about 21 B total and 3.6 B active parameters
  for the 20 B model), with a 128 K context window. Weights are published; training data and full
  training code are not, so these are open-weight rather than fully open-source.
  <https://www.theregister.com/2025/08/05/openai_open_gpt/> ·
  <https://www.deeplearning.ai/the-batch/gpt-oss-openais-first-open-weights-models-since-gpt-2-arrives-in-120-billion-and-20-billion-parameter-versions>
- Qwen3.8-27B licence — reporting conflicts. One outlet reports an Apache 2.0 release of the
  weights; other write-ups state that no licence has been confirmed. Treated as unresolved in §11
  rather than asserted here.
  <https://www.eweek.com/news/alibaba-qwen3-8-27b-license-apac-china/>
