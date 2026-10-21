# C4 Learning Notes

One entry per task (CLAUDE.md §8). Written for a reader new to Python and to research.

## C4-T02 — Component scaffold (2026-10-14)

**What it does (plain English, 3–5 lines):**
Creates the empty "skeleton" of C4 inside the group backend: one folder per pipeline
step (ingestion, features, scoring_engine, explanation, evaluation, reporting), each
with the same three files the team requires. It also adds every C4 threshold (θ = 5,
top-N = 10, CR ≤ 0.10, …) to the shared settings, and tests that guard the
architecture rules. No research logic yet: each step's real code arrives in its own task.

**The formula / algorithm in one line:**
None yet. The rule enforced is structural: *subcomponents never import each other or
any database/LLM library; the component's `service.py` is the only way in.*

**Why this choice over the obvious alternative:**
The obvious alternative is one big `c4_severity/` package at the repo root. The team's
placement contract (INSTRUCTIONS §7) forbids new top-level folders and requires the
`service.py` / `models.py` / `ports.py` pattern. Following it keeps the maths free of
FastAPI, databases and AI SDKs, so every formula can be unit-tested in milliseconds
without Docker. A *port* (a Python `Protocol`) is an interface: it says "I need
something that can give me commit history" without saying *how*. The real
implementation lives in `app/infrastructure/`, and tests use a small in-memory fake.

**Likely panel question + a 2-sentence answer:**
*"Why are all your thresholds in settings instead of in the code?"* — Every number that
shapes a ranking (θ, k, the CR limit, the half-life) must be visible, changeable without
editing code, and recorded in each run's manifest so results are reproducible. A test
pins each default to the value in the design document, so a threshold cannot change
silently.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring -v
```
Shows the settings tests (each threshold matched to its CLAUDE.md section) and the
layer-boundary tests (no forbidden imports, no subcomponent importing another).

## C4-T03 — Tooling & quality gates (2026-10-18)

**What it does (plain English, 3–5 lines):**
Installs every library C4 will need and adds four automatic checks ("quality gates")
that every task must pass: a linter (ruff: finds likely bugs and style problems), a
formatter check (ruff format: one consistent layout), a type checker (mypy: proves
every function is called with the right kinds of values), and the tests with a
coverage report (which lines the tests actually ran). One script runs all four and
saves the result as evidence for PP1.

**The formula / algorithm in one line:**
Coverage = lines executed by tests ÷ executable lines; the gate fails below 80 %.

**Why this choice over the obvious alternative:**
The obvious alternative is turning strict checks on in `pyproject.toml` for the whole
backend. That would make teammates' code "fail" checks they never agreed to, so the
strict rules are scoped to C4 (mypy overrides per module; ruff's extra rules and the
80 % floor passed by the script). torch comes from the CPU-only index because C4 only
*runs* two small pretrained models (inference) and never trains one — the default
Linux build would download several GB of GPU libraries for nothing.

**Likely panel question + a 2-sentence answer:**
*"How do you know your code meets the standards you claim?"* — Every task must pass
four automated gates (lint, format, strict typing, tests with ≥ 80 % coverage), run by
one script that saves a timestamped report with the git commit. The reports in
`docs/pp1/evidence/` are the proof, and anyone can regenerate them with one command.

**How to demo it (exact command):**
```bash
cd backend
powershell -ExecutionPolicy Bypass -File scripts/c4_quality_gate.ps1
```

## C4-T05 — Contracts (2026-10-18)

**What it does (plain English, 3–5 lines):**
A *contract* is the agreed shape of the data passed between two components. C4 reads
C3's contract (`DegradationEventV2`: one anti-pattern that is getting worse) and writes
its own (`SeverityReportV1`: the ranked, explained list). This task wrote C4's contract
as a Pydantic model (a Python class that checks data when it is loaded), a script that
turns it into a JSON Schema (a language-neutral description other teams can read), and
a decision record on how C4 uses C3's contract, whose shape differs from our early draft.

**The formula / algorithm in one line:**
No formula; the model enforces rules such as *active weights sum to 1*, *ranks are
1..n*, and *groundedness = grounded claims ÷ total claims*, each failing with its own
named error.

**Why this choice over the obvious alternative:**
The obvious alternative was a local copy of C3's event in C4's own folder. C3 had
already published the real one, so a copy would drift from it; C4 imports the original
instead, and asks C3 for the missing fields rather than guessing them. Where C4 must
use a stand-in meanwhile (e.g. "first seen" = start of C3's analysis window), it is
written down in C4-ADR-007 so it is visible, not hidden. C4 loads the release package
C3 analysed rather than C2's graph, because its element names match C3's events exactly.

**Likely panel question + a 2-sentence answer:**
*"How do you know a report your tool produces is correct and complete?"* — Every report
is validated against the `SeverityReportV1` model before it is written: an inconsistent
one (weights not summing to 1, a rank gap, audit counts that don't add up) is refused
with a named error. The JSON Schema generated from the same model lets the API and the
frontend check the same rules, and a test fails if the committed schema is out of date.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/domain/test_severity_report.py -v
uv run python -m scripts.scoring_export_schemas --check
```

## C4-T06 — Requirements doc (2026-10-18)

**What it does (plain English, 3–5 lines):**
Writes down what C4 must do (functional requirements, FR) and how well (non-functional
requirements, NFR), for whom (personas) and why (user stories). Every requirement has a
pass/fail condition, so it can be proven by a test rather than argued. A traceability
table links each requirement to the module and test that will prove it.

**The formula / algorithm in one line:**
Requirement → module → test → task: a requirement counts as met only when its test passes.

**Why this choice over the obvious alternative:**
The obvious alternative is a feature list ("C4 ranks events"). It cannot be checked: what
counts as ranked correctly? Writing a measurable condition (e.g. "classic TOPSIS matches
pymcdm to 1e-9", "500 events in ≤ 30 s") turns each line into something a test or a timed
run can confirm, which is what the mark sheet asks for.

**Likely panel question + a 2-sentence answer:**
*"How do you know you met your requirements?"* — Each FR and NFR has a pass/fail
condition, and the traceability matrix names the test that checks it. A requirement is
ticked only when that test passes in the saved quality-gate report.

**How to demo it (exact command):**
Open `backend/app/components/degradation_scoring/docs/requirements.md`, §5, and run
`uv run pytest tests/domain/test_severity_report.py -v` to show FR-11's contract tests.

## C4-T07 — Fixtures (2026-10-18)

**What it does (plain English, 3–5 lines):**
Creates hand-designed test data: a small made-up system (22 services) and 17 C3 events,
one for each situation C4 must handle (ranked, rejected, intentional, system-wide,
superseded, unresolvable, broken). A separate file records the intended outcome of each
event, so later code can be checked against a known answer.

**The formula / algorithm in one line:**
Known input + designed answer (`fixture_expected.json`) → a test passes only when the code
reproduces the designed answer exactly.

**Why this choice over the obvious alternative:**
The obvious alternative is waiting for real C3 output. That would block C4 and give no
known right answer to test against. Synthetic fixtures are labelled as such everywhere
(file names, README, `data_provenance: "fixture"`), so they can never be mistaken for results.

**Likely panel question + a 2-sentence answer:**
*"Isn't testing on made-up data cheating?"* — Fixtures test that the code is *correct*
(it does exactly what the design says on cases with a known answer); they are never
reported as findings. Real-data evidence comes from the demo repository and the pilot
evaluation, each with its own manifest.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/test_fixtures.py -v -rs
```
Shows the two tests skipped "waiting for C3 V2.1.0".

## C4-T08 — Event loader & quarantine (2026-10-18)

**What it does (plain English, 3–5 lines):**
The front door of C4. Every event C3 sends is first checked against C3's own contract;
a broken one is put in *quarantine* (listed with the error, never scored). Valid events
that should not be ranked are *skipped* with a reason: rejected by C3's reviewer, judged
intentional, replaced by a newer version, system-wide, or (only if switched on) not yet
confirmed. Everything else goes on to be ranked, in the order it arrived.

**The formula / algorithm in one line:**
For each valid event, record the first rule that applies in the order rejected →
intentional → superseded → system scope → not confirmed; no rule applies ⇒ eligible.

**Why this choice over the obvious alternative:**
The obvious alternative is to crash on, or silently drop, a bad event. Crashing lets one
bad event stop the whole run; dropping hides problems from C3. Quarantine with a reason
keeps the run going *and* tells C3 exactly what to fix. The fixed rule order makes the
recorded reason predictable, and names C3's own decisions first.

**Likely panel question + a 2-sentence answer:**
*"What happens if C3 sends you garbage?"* — Every payload is validated against C3's
published model; anything that fails is quarantined with the exact field and error, and
no exception escapes (tested with null, numbers, strings, empty objects). The counts per
reason are part of the report, so integration problems are visible, not hidden.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/ingestion -v
```

## C4-T09 — Graph loader (2026-10-18)

**What it does (plain English, 3–5 lines):**
Turns C3's release package (the list of services and who calls whom) into a *graph*: dots
for services, arrows for dependencies. An arrow A → B means "A depends on B", and its
weight is how many calls go from A to B. Each release's graph is built once per run and
then reused. Broken graph documents stop the run with a clear error.

**The formula / algorithm in one line:**
The services that depend on X (directly or through others) = all *ancestors* of X, i.e.
every node with a path of arrows leading to X.

**Why this choice over the obvious alternative:**
The obvious alternative is drawing arrows the other way (pointing at the dependent). Both
upstream formats already use "from depends on to", so keeping it avoids a reversal on every
load, and a wrong direction would silently invert every blast-radius score. A setting can
still flip the arrows if a future graph uses the opposite convention (C4-ADR-003).

**Likely panel question + a 2-sentence answer:**
*"How do you know your graph's arrows point the right way?"* — The convention is written
down (C4-ADR-003) and tested: on the fixture graph, the services that depend on
`email-adapter` are exactly its ancestors, and the reverse switch is tested on a chain.
A node-link file that stores edges under the wrong key is refused, because it would
otherwise load with no edges and no error.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/ingestion/test_graph.py -v
```

## C4-T10 — Element resolution (2026-10-18)

**What it does (plain English, 3–5 lines):**
C3 names the parts of the system an event is about ("payment-service", or a folder like
"src/services/notification"). C4 must find those parts in the graph before it can measure
anything. It tries the exact name, then an old name (alias), then a folder whose files
belong to exactly one service. If any name cannot be found, the event is quarantined, and
the share of events that could be matched (the *resolution rate*) is reported.

**The formula / algorithm in one line:**
resolution_rate = resolved events ÷ eligible events; confidence = 1.0 if every name matched
exactly, else 0.7 (setting) when a folder match was needed.

**Why this choice over the obvious alternative:**
The obvious alternative is to rank whatever part of an event could be matched. A cycle with
one member missing would then look smaller than it is, and nobody would notice. Refusing
partial matches (and ambiguous folder matches) keeps every ranked number honest, and the
resolution rate turns the failures into a reportable C3→C4 interoperability result.

**Likely panel question + a 2-sentence answer:**
*"What if C3 and your graph disagree on names?"* — Each event is matched by exact name,
then by alias, then by folder path; anything still unmatched is quarantined with the
missing names listed, never guessed. The resolution rate (0.9 on the fixtures) is printed
in every report, so a naming mismatch between components is measured, not hidden.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/ingestion -v
```
Runs all of Layer 1 (events, graph, resolution) on the fixtures.

## C4-T11 — Blast radius (2026-10-18)

**What it does (plain English, 3–5 lines):**
For each event, measures how much of the system could be hurt if its elements break. It
gives four numbers: the share of other services that depend on the elements
(*fan-in ratio*), how "important" they are in the dependency network (*PageRank*), how
often they sit on the routes between other services (*betweenness*), and how deep below
the system's entry points they are (*depth*). Combining the four into one score comes in T17.

**The formula / algorithm in one line:**
fan_in = |dependents of S outside S| / (n − |S|); pagerank = Σ PR(v); betweenness = max
BC(v); depth = max over v of the longest shortest path from any root, measured with
every cycle collapsed into one node (*condensation*).

**Why this choice over the obvious alternative:**
The obvious alternative is counting direct callers (in-degree). That misses services that
depend on an element only indirectly, and it treats a caller nobody uses the same as a hub.
PageRank (importance passed along dependencies, Google's link-ranking idea) and betweenness
(the share of shortest routes through a node) add those views. Depth is measured on the
condensation so that all members of a cycle get one depth instead of a depth that depends
on where the cycle is entered (C4-ADR-008). PageRank and betweenness are computed once per
release and reused for every event. On very large graphs (> 5000 nodes), betweenness is
estimated from 500 randomly chosen start nodes with a fixed seed, so it stays fast and
gives the same result every run.

**Likely panel question + a 2-sentence answer:**
*"How do you know the numbers are right?"* — On four tiny graphs (star, chain, cycle,
diamond) the values were worked out by hand and the code matches them to 0.000001. The
old prototype's 13-module graph is rebuilt, and the new code reproduces its numbers for
all six events. (PageRank is computed by repeated approximation; C4 runs it until the values change by
less than 0.0000000001, so the result is far more precise than the test needs.)

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/features -v
```

## C4-T12 — Commit history and mining cache (2026-10-18)

**What it does (plain English, 3–5 lines):**
Reads the project's git history between two releases: every commit, who made it, when, its
message, and how many lines it changed in each file. Files that are not real code (vendored
libraries, generated code, test fixtures, build output like `target/` or `bin/`) are thrown
away. Each remaining file is matched to the service it belongs to, using the file paths in
the graph. The result is stored in the database, so the next run does not read git again.

**The formula / algorithm in one line:**
commits = git `from..to` (after the first-seen tag up to the detected tag), no merges →
keep files matching include globs and no exclude glob → file belongs to every service whose
`source_paths` match it; cache key = (repo, from, to, hash of the filter rules).

**Why this choice over the obvious alternative:**
The obvious alternative is mining git on every run. That takes minutes on a real project and
makes the live demo slow, so results are cached in the team's PostgreSQL database (not a
separate file store, C4-ADR-001). The cache key includes a fingerprint of the filter rules, so
changing a rule can never reuse old, differently filtered data. Merge commits are left out
because they only repeat changes that their parent commits already contain.

**Likely panel question + a 2-sentence answer:**
*"How do you know which commits belong to which architectural element?"* — Each element in
the graph lists its source files, and a changed file is attributed to every element whose
paths match it; a test builds a tiny git repository with known commits and checks every
attribution. Files shared by two elements count for both and are reported, and files no
element owns are reported too, so the mapping's gaps are measured rather than hidden.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/features/test_history.py tests/infrastructure/git/test_history.py -v
```

## C4-T13 — Hotspot features (2026-10-18)

**What it does (plain English, 3–5 lines):**
Measures how "hot" an event's code is in git history since the problem was first seen:
how many lines changed (recent changes count more), how many different people changed it,
how many other parts of the system keep changing together with it, and what share of its
changes were bug fixes. A service listed in several events is measured per event, and an
event's services are measured as one block.

**The formula / algorithm in one line:**
churn = Σ lines × e^(−λ·days before release), λ = ln 2 / half-life, half-life = 2 × median
gap between releases; authors = distinct e-mails; coupling = outside parts co-changed in ≥ 5
commits (huge commits ignored); bug-fix ratio = fix-looking commits ÷ commits.

**Why this choice over the obvious alternative:**
The obvious alternative is raw churn (just count lines). That treats a change from two years
ago like one from last week, so old, settled code looks as risky as code being fought over
now. Exponential decay (each half-life halves a change's weight) keeps recent work dominant,
and tying the half-life to the project's own release rhythm makes it fair across fast and
slow projects. Counting a shared file once per event stops cycles from looking worse just
because their members share code.

**Likely panel question + a 2-sentence answer:**
*"Isn't counting 'fix' in commit messages unreliable?"* — Yes, and we say so: it is a
heuristic, the tests show both cases it gets right and cases it misses ("resolve crash"), and
the rule is written down in C4-ADR-009. It is one of four hotspot signals, and the ablation
in T28 measures how much each signal actually contributes to the ranking.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/features/test_hotspot.py -v
```

## C4-T15 — Persistence (2026-10-18)

**What it does (plain English, 3–5 lines):**
Measures how long a degradation has been around and how fast it is getting worse, using
only the numbers C3 already sent. It counts how many releases in a row (ending at the
current one) the problem was present, and how quickly its metric grows from release to
release. A problem that has lasted and keeps growing is more urgent.

**The formula / algorithm in one line:**
consecutive = present releases in a row ending at the detected release; growth = OLS slope
of the metric over release number ÷ the metric's average (positive = worse), using the
fastest-worsening metric.

**Why this choice over the obvious alternative:**
The obvious alternative is the plain slope. But C3's metrics have different units: a class
growing by 700 lines per release would always look worse than a coupling value growing by
0.05, even if the coupling doubles. Dividing by the average turns every slope into "percent
growth per release", so different metrics can be compared fairly (C4-ADR-010).

**Likely panel question + a 2-sentence answer:**
*"C3 already computes a trend (Sen's slope, tau). Why compute your own slope?"* — C3's trend
numbers measure how *certain* the trend is, which C3 says is not severity, and using them
would let C3's evidence strength sneak into the ranking. C4 only fits a simple line through
the raw values C3 reported, which keeps the two components' jobs separate.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/features/test_persistence.py -v
```

## C4-T14 — Hotspot on Online Boutique (2026-10-18)

**What it does (plain English, 3–5 lines):**
Runs the hotspot measurement on a real project, Google's Online Boutique, for its last
three releases. Because C2 does not yet say which folders belong to which service, a
hand-made mapping (`src/<service>/**`) is used and labelled as such. The run is timed twice:
the first run reads git, the second reads the saved result from the database.

**The formula / algorithm in one line:**
first run = mine git (15.4 s); second run = read the cache (0.005 s), same answer.

**Why this choice over the obvious alternative:**
The obvious alternative is waiting for C2's real folder mapping, but then there would be no
real-project evidence for PP1. A clearly labelled manual mapping (C4-ADR-011) shows the
mechanism working today and will be swapped for C2's data without code changes.

**Likely panel question + a 2-sentence answer:**
*"What did you learn from the real repository?"* — Most of Online Boutique's recent commits
only update dependencies, so only 4 of 195 commits changed real code, and every GitHub
commit message ends with a pull-request number that our bug-fix rule wrongly counts as an
issue. Running on real data exposed both problems early, which is exactly why we tested on
a real repository before ranking with it.

**How to demo it (exact command):**
```bash
cd backend
uv run python -m scripts.c4_hotspot_profile --from-tag v0.10.4 --to-tag v0.10.7   # run twice
```

## C4-T16 — ADR loader and ADR-violation weight (2026-10-18)

**What it does (plain English, 3–5 lines):**
An ADR (architecture decision record) is a short document where a team writes down a design
rule, e.g. "core services must not call each other in a loop". If C2 says an element breaks
such a rule, C4 gives the event extra weight: more for an accepted, system-wide rule, less
for a proposed or local one. If nobody has linked events to ADRs, this criterion is simply
switched off, and the ranking uses the other three.

**The formula / algorithm in one line:**
AV = status weight × scope weight × explicitness, for the most serious ADR C2 links to the
event (e.g. accepted × system × C2-link = 1.0 × 1.0 × 1.0); no link = 0; no ADR index = off.

**Why this choice over the obvious alternative:**
The obvious alternative is to guess links ourselves, e.g. "this ADR mentions catalog-service,
so every catalog-service problem violates it". That would be C2's job (checking architecture
against decisions), and it would be wrong: a decision *about* a service is not broken by
*every* problem in it. So C4 only uses links C2 provides, and turns the criterion off — and
says so — when there are none (C4-ADR-012).

**Likely panel question + a 2-sentence answer:**
*"Your ADR criterion is off in every real run. Isn't it useless?"* — It is optional by
design: the plan's Gate 2 decides whether the ADR signal is strong enough, and every result
is produced with and without it. The mechanism is built and tested now, so switching it on
only needs C2's links, not new C4 code.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/ingestion/test_adr.py tests/components/degradation_scoring/features/test_adr_weight.py -v
```

## C4-T16b — Run results in the database (2026-10-18)

**What it does (plain English, 3–5 lines):**
Every time C4 runs, it now saves what happened at each step in three database tables you
can open in DBeaver: one row for the run (counts, which criteria were on), one row per input
event (ranked, skipped or quarantined, and why), and one row per ranked event with all its
numbers. An examiner can follow one event from input to features without reading code.

**The formula / algorithm in one line:**
run → (run_id, payload_index) ingestion rows → (run_id, event_id) feature rows → later
(run_id, event_id) score rows; every number in its own column.

**Why this choice over the obvious alternative:**
The obvious alternative is saving each run as one JSON document. That is easy to write but
unreadable in a database tool and impossible to query ("show me every event that used a
fallback"). Plain columns make each table read like a spreadsheet, and the C4 code still
never touches the database directly — it hands plain rows to a port (same pattern as the
mining cache).

**Likely panel question + a 2-sentence answer:**
*"How can I check what your system did with one event?"* — Open `c4_event_ingestion` to see
whether it was ranked, skipped or quarantined and why, then `c4_event_features` for its
blast-radius, hotspot, persistence and ADR numbers; `demo-queries.sql` has the queries. Each
run has its own id, so runs with and without the ADR index can be compared side by side.

**How to demo it (exact command):**
```bash
cd backend
uv run python -m scripts.c4_run_features --run-id fixture-demo-adr-on
# DBeaver: open app/components/degradation_scoring/docs/pp1/demo-queries.sql and run it
```

## C4-T17 — Normaliser (2026-10-18)
**What it does (plain English, 3–5 lines):**
The features come in very different units (PageRank ≈ 0.05, depth 2–4, churn in hundreds of
lines), so they cannot be added up as they are. The normaliser puts every feature on the same
0–1 scale for this system, then averages each criterion's features into one number (blast
radius = mean of its 4 features, persistence = 0.7 × releases + 0.3 × growth). The scale it
used (the "bounds") can be saved and reused, so a later run is measured with the same ruler.

**The formula / algorithm in one line:**
`x' = clip((x − P5) / (P95 − P5), 0, 1)`, where P5 / P95 are the 5th / 95th percentiles of
that feature over the run's events (a percentile = the value below which that share of the
data lies); fewer than 10 events → plain min / max instead.

**Why this choice over the obvious alternative:**
The obvious alternative is plain min-max: (x − min) / (max − min). One huge value then
squashes everyone else towards 0. With values 1…39 and one 1000, plain min-max gives 20 a
score of 0.019, while the winsorised version ("winsorise" = clip extreme values to the P5 /
P95 limits first) gives 0.486. Two owner rules on top (C4-ADR-013): a sparse feature (all 0
but one) falls back to min-max so that one signal is not lost, and the ADR weight is left as
it is because it already means the same thing in every run.

**Likely panel question + a 2-sentence answer:**
*"Why save the bounds at all — why not re-normalise every run?"* — If the scale is re-fitted
each time, adding one unrelated event changes the scale and can reorder the existing events
(rank reversal). Frozen bounds keep each event's normalised value fixed; the test adds an
extreme event and checks that the 12 existing events' values do not change at all.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/scoring_engine -v
# outlier, sparse fallback, frozen bounds and save/load tests, with hand-computed values
```
Known limitation to say out loud: with 10–20 events one outlier is 5–10 % of the data, so the
P95 limit cannot fully clip it (the outlier test therefore uses 40 events).

## C4-T18 — AHP weights (2026-10-18)
**What it does (plain English, 3–5 lines):**
Decides how much each criterion (BR, EH, AV, PS) counts in the final severity. A person
compares the criteria in pairs ("blast radius matters 2× as much as hotspot") and writes the
answers into a table, the *pairwise matrix* in `weights/ahp_v1.json`. `ahp.py` turns that table
into four weights that sum to 1 and checks the answers do not contradict each other. When a
criterion is off (AV in every real PP1 run), it gets weight 0 and the others are scaled up so
they still sum to 1.

**The formula / algorithm in one line:**
weights = principal eigenvector of the matrix (the one direction the matrix only stretches,
never turns), scaled to sum 1; `CI = (λmax − n)/(n − 1)`, `CR = CI / RI(n)`; CR > 0.10 ⇒ refuse.
(λmax = that eigenvector's stretch factor; it equals n exactly when all answers agree, so
λmax − n measures the contradiction. RI = the average CI of random matrices, so CR = "how
inconsistent compared with guessing"; 0.10 = at most 10 % of random.)

**Why this choice over the obvious alternative:**
The obvious alternative is to type four weights by hand (0.4, 0.3, …). Nobody can check those.
Pairwise answers are easier to give honestly, and AHP tells you when they contradict each other
(A > B 2×, B > C 2×, but C > A). For AV off, I rescale the 4×4 weights instead of running AHP
again on a 3×3 sub-matrix (C4-ADR-014): one set of answers, one CR, and switching AV off
leaves BR : EH : PS in the same proportions (0.556 / 0.330 / 0.114, vs 0.558 / 0.320 / 0.122 with
the sub-matrix).

**Likely panel question + a 2-sentence answer:**
*"Where do your weights come from — didn't you just invent them?"* — They are provisional,
author-elicited judgements, and the report says so in `weights_provenance`; the supervisor
elicitation session (Y05) replaces them, and the code refuses any matrix with CR > 0.10. The
method itself is checked against Saaty's own published house example (CR 0.17, which our gate
correctly refuses).

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/scoring_engine/test_ahp.py -v
```
**Before the viva (owner):** check the 8×8 house matrix in `test_ahp.py` against the table in
Saaty, T. L. (1990), "How to make a decision: The analytic hierarchy process", *European
Journal of Operational Research* 48(1), 9–26, and note the page number. It was typed from
memory; it reproduces the published weights, λmax 9.669 and CR 0.169 exactly, which is strong
but not final evidence that every cell is right.

## C4-T19 — TOPSIS ranking (2026-10-18)
**What it does (plain English, 3–5 lines):**
Turns each event's 0–1 criterion values and the AHP weights into one severity score, then sorts
the events. Picture a perfect-storm event that scores 1 on every criterion (the *ideal*) and a
harmless one that scores 0 everywhere (the *anti-ideal*). Severity says how much closer the
event is to the perfect storm than to the harmless one. The report also shows each
criterion's share of that score (*contributions*), so a reader can see why an event ranks high.

**The formula / algorithm in one line:**
`v = w · x`; `d⁺ = ‖v − A⁺‖`, `d⁻ = ‖v − A⁻‖` (straight-line distances); `S = d⁻ / (d⁺ + d⁻)`;
fixed mode: `A⁺ = w`, `A⁻ = 0`; classic: `A⁺`/`A⁻` = best / worst event of the run.

**Why this choice over the obvious alternative:**
Classic TOPSIS takes its ideal and anti-ideal from the events in the run, so adding one
unrelated event can swap two others. This is called *rank reversal*. Our test builds such a
case: E3 is worse than E1 and E2 on everything, yet adding it swaps E1 and E2 in classic mode
(0.445 < 0.555 becomes 0.631 > 0.606). Fixed-reference TOPSIS uses fixed points 1 and 0, so an
event's score depends only on its own values; adding E3 changes nothing (C4-ADR-002).

**Likely panel question + a 2-sentence answer:**
*"Why TOPSIS and not just a weighted sum?"*: A weighted sum lets a high value on one
criterion fully cancel a low value on another. TOPSIS measures distance to both a worst and a
best case, so the combination of values matters. It is also a standard, published MCDA
method. We still avoid TOPSIS's known weakness (rank reversal) with fixed reference points,
which the test demonstrates.

**How to demo it (exact command):**
```bash
cd backend
uv run pytest tests/components/degradation_scoring/scoring_engine/test_topsis.py -v
uv run python -m scripts.c4_run_features --run-id demo-on            # AV on: E01 ranks 1st
uv run python -m scripts.c4_run_features --no-adr --run-id demo-off  # AV off: E02 ranks 1st
# then queries 7-9 in docs/pp1/demo-queries.sql (use the new run ids)
```
Limitation to say out loud: fixed reference stops TOPSIS itself from reordering events, but the
0–1 scale (normaliser bounds) is still fitted on the run's events. Full stability across
releases needs the frozen calibration (§5.5).

## C4-T20 — Report writer, run manifest and the `c4_rank` script (2026-10-18)
**What it does (plain English, 3–5 lines):**
One command now runs the whole C4 pipeline so far (read events → measure → weigh → rank) and
writes five files into its own folder: the ranked report as JSON (for programs), the same
report as a web page (for people), a quarantine file (events left out, and why), a log, and a
*run manifest*. The manifest is a "receipt" of the run: which inputs (by fingerprint), which
settings, which code version and which library versions produced these numbers.

**The formula / algorithm in one line:**
`fingerprint = sha256(canonical JSON of the input)`; same inputs + same settings + same code
⇒ byte-for-byte the same `c4_report.json` (only `run_id` differs), which a test checks.

**Why this choice over the obvious alternative:**
The obvious alternative is "just print the ranking". But a number on a slide that nobody can
regenerate is not evidence. The manifest records everything needed to rerun it, and a
*golden file* (a saved, reviewed copy of the fixture report) makes any unintended change to
the numbers fail a test. A *hash* (sha256) is a short fingerprint of a file: change one
character and the fingerprint changes completely. The JSON is also read back through the
`SeverityReportV1` contract before it is written, so a broken report can never leave C4.

**Likely panel question + a 2-sentence answer:**
*"How do I know the report I am looking at was not hand-edited or produced by different
code?"*: The manifest stores the sha256 of the report file, the inputs and the git commit
(marked `-dirty` if the code had uncommitted changes). Rerunning the script on the same inputs
gives a byte-identical report, and a test proves that on every build.

**How to demo it (exact command):**
```bash
cd backend
uv run python -m scripts.c4_rank \
    --events tests/fixtures/degradation_scoring/events/fixture_events.v1.json \
    --graph  tests/fixtures/degradation_scoring/graphs/fixture_release_package.v1.5.0.json \
    --adr-index tests/fixtures/degradation_scoring/adr --run-id demo-on
uv run python -m scripts.c4_rank --events ... --graph ... --no-adr --run-id demo-off
# open artifacts/scoring/c4-fixture-shop/demo-on/c4_report.html in a browser
```
Things to say out loud: the yellow banner says the data is a fixture (hand-made test data,
not a result); each card's badges show where a stand-in was used ("fallback: presence" = C3
does not send presence history yet); the API endpoint is not wired yet because it needs a
line in the team's `app/main.py`.

## C4-T21 — First end-to-end run on a real repository (2026-10-19)
**What it does (plain English, 3–5 lines):**
Runs the whole C4 pipeline once on Online Boutique, Google's demo shop made of small
services. The events, the service graph and two ADRs are hand-made (a *fixture*: test data
we wrote ourselves), but the commit history is the real one from GitHub, so the hotspot
numbers are mined live. We run it twice, with the ADR criterion on and off, and compare the
two rankings. Both reports are saved in `docs/pp1/figures/t21_online_boutique/`.

**The formula / algorithm in one line:**
Same pipeline as T20: severity = fixed-reference TOPSIS over BR, EH, (AV), PS with AHP
weights; with AV off its weight 0.160 is shared out in proportion (BR 0.467 → 0.556, etc.).

**Why this choice over the obvious alternative:**
The obvious alternative is to wait for real C3 events and C2 links. That would leave PP1 with
no real-repository run. Using fixture events on top of real history shows the pipeline works
on a real codebase while being honest about which parts are hand-made: the report banner,
the manifest (`data_provenance: "fixture-events+live-history"`) and the README all say so.

**Likely panel question + a 2-sentence answer:**
*"Two events have zero hotspot activity although their services changed. Is that a bug?"*:
No. Hotspot only counts source-code files, and in those windows Online Boutique's changes to
checkout, cart and email were dependency bumps (`go.mod`, `.csproj`, Dockerfiles), which the
filter leaves out on purpose.

**How to demo it (exact command):**
See `docs/pp1/figures/t21_online_boutique/README.md` (two `c4_rank` commands, from `backend/`),
then open `artifacts/scoring/online-boutique/t21-ob-av-on/c4_report.html`. Things to say out
loud: E04 moves from 3rd to 2nd when AV is on because cartservice is linked to an ADR; E06
has the strongest ADR link but stays 5th, so AV adjusts the order without overriding the other
three criteria.

## C4-ADR-015 — Constant features are left out of the criterion mean (2026-10-19)
**What it does (plain English, 3–5 lines):**
Each criterion (e.g. hotspot) is the average of a few features scaled to 0–1. If one feature
has the same value for every event in a run (here: coupling is 0 for all six), it cannot tell
the events apart. Before, it got 0.5 for everyone and still went into the average, which
pulled every score towards the middle. Now it is simply left out of the average; if all of a
criterion's features are constant, that criterion is 0 for everyone.

**The formula / algorithm in one line:**
criterion = Σ wᵢ·xᵢ / Σ wᵢ over the features whose range is not zero; none left ⇒ 0.

**Why this choice over the obvious alternative:**
Keeping 0.5 (the original rule) adds the same number to every event, which carries no
information but shrinks the real differences. Removing the whole criterion from TOPSIS
instead would change the AHP weights from run to run.

**Likely panel question + a 2-sentence answer:**
*"Doesn't leaving a feature out change what the criterion means between runs?"*: Only for
features that are constant in that run, which could not change any event's position anyway;
the bounds file and log record exactly which features were left out. With frozen
calibration (§5.5) the same features are left out every time, so runs stay comparable.

**How to demo it (exact command):**
Run the T21 commands, then open `c4_run_manifest.json`: `normalization.bounds.eh_coupling`
shows `"fallback": "zero_range"`, and `logs/c4.jsonl` has the `normalisation_zero_range`
warning with `"action": "left_out"`.
