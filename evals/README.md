# DocForge evals

This suite measures how well DocForge's pipelines work, from the outside. It calls the app's real
service functions in an isolated sandbox and never changes the app's code.

**Status:** M5 built (2026-11-28). Three suites, in three modes each (AI off, Claude Haiku 5.5,
and a local model in LM Studio). The part without AI runs as a CI gate on every pull request into
`evals` ([below](#the-ci-gate)), and [RESULTS.md](RESULTS.md) shows the newest result of each
mode:
- **comply** checks returned documents against their template. Its three-way comparison is in
  the changelog's M2 entry.
- **generate** fills each template from 35 rough-notes texts and measures what DocForge wrote,
  hallucinations first. Its three runs happen on the owner's PC
  ([guide below](#run-the-generate-suite-on-your-pc-m3)); the comparison and five written-up
  failures are in the changelog's M3 entry.
- **analyze** builds a template from 1, 2, 3 or 5 example documents of each type and measures
  what DocForge made of each element: fields found, boilerplate kept, field types, tables,
  "label | value" information blocks, and the template's layout
  ([guide below](#run-the-analyze-suite-on-your-pc-m4)). The comparison by number of examples is
  in the changelog's M4 entry.

- Design: [DESIGN.md](DESIGN.md)
- What each milestone built and learned: [CHANGELOG.md](CHANGELOG.md)
- Project brief: [docs/projects/eval-suite.md](../docs/projects/eval-suite.md)

## Run it (no AI)

From the repo root, with Python 3.11 or newer:

```bash
pip install -e backend
```

```bash
pip install -r evals/requirements.txt
```

```bash
python -m evals corpus build
```

```bash
python -m evals run --suite comply --config evals/configs/no-ai.yaml
```

To reproduce every deterministic result at once and check it against the committed thresholds:

```bash
python -m evals run --suite all --config evals/configs/no-ai.yaml
```

```bash
python -m evals gate
```

**What each command does**
- **`corpus build`** writes the 91 documents and 238 comply cases to `evals/corpus/build/`
  (gitignored) in about 10 s, and rewrites `evals/corpus/manifest.json`. That file is committed,
  so a build that changes it means the corpus code changed. It also writes the 19 documents only
  analyze uses (the DPIA and status report examples, and one shared-value document per type),
  listed in the manifest's `analyze` section.
- **`corpus check`** rebuilds the corpus in a temp folder and compares it with the committed
  manifest. It fails, listing what changed, when a ground truth, a value or a label differs. Files
  whose bytes alone differ (another python-docx or lxml version) are only noted.
- **`run`** prints a table and writes `evals/results/<date>_<config>_comply.json`. With AI off,
  the whole comply suite takes about 40 s. A missing build is created first. If the corpus code
  no longer matches the committed manifest, the run stops.
  - `--types invoice_en nda_de`: only some types.
  - `--limit 3`: at most 3 cases per type, for smoke runs.
  - `--out DIR`: write the result file somewhere else.
  - `--keep-sandbox`: keep DocForge's temp database and data dir for debugging.
  - AI modes only: `--dry-run`, `--repeat`, `--sample`, `--max-usd`, `--model`, `--no-cache`
    (see the guide below and `python -m evals run --help`).
- **`run --suite generate`** fills each type's template from the notes cases in
  `evals/corpus/notes/` and writes `evals/results/<date>_<config>_generate.json`. With AI off it
  takes about 10 s.
  - With `ANTHROPIC_API_KEY` set, Claude Haiku 5.5 grades the free-text fields
    (`evals/configs/grader.yaml`, at most $1.00 per run). `--no-grade` skips the grading.
  - `--types` and `--limit` work as for comply; `--limit 1` takes the first notes style only.
- **`run --suite analyze`** builds 45 templates: for each of the 9 types, from its first 1, 2,
  3 and 5 examples, then from the first example and a second one that shares a value with it.
  It writes `evals/results/<date>_<config>_analyze.json`. With AI off it takes about 10 s.
  `--types` works as for comply; `--limit 1` builds from 1 example only.
- **`run --suite all`** runs comply, generate and analyze in turn, each in a process of its own,
  and writes one result file each. With AI, `--max-usd` caps the three together.
- **`gate [FILES]`** checks no-AI results (by default the newest committed ones) against
  `evals/thresholds.yaml`, and exits with 1 if anything got worse ([the CI gate](#the-ci-gate)).
  `gate --update` writes the thresholds from the results instead.
- **`report`** rebuilds [RESULTS.md](RESULTS.md) and the main README's results table from the
  newest result of each mode and suite. Nobody edits either by hand. `report --check` only checks
  they are up to date.
- **`compare A.json B.json [C.json ...]`** prints results of one suite side by side. After the
  table come the changes from the first file to each of the others: the cases whose alarm
  status changed (comply), or the fields whose outcome changed (generate). Add `--markdown` for
  a table to paste into docs.
- **`labels sheet`** picks the 30 free-text items the owner labels to check the grader
  (`--languages en` keeps only English documents with English notes); **`labels check`** reports
  how often the grader agrees with those labels (85% or more, or its grades aren't used).
- **`rescore FILE ...`** recomputes a generate result's outcomes from the values it recorded,
  after a comparison rule is fixed. Nothing is generated or graded again, and the result notes
  when it was rescored.

The tests run from the repo root:

```bash
python -m pytest tests/evals -q
```

```bash
ruff check --config evals/ruff.toml evals tests/evals
```

## The CI gate

[`.github/workflows/evals.yml`](../.github/workflows/evals.yml) runs on every pull request into
`evals` and every push to it. On Python 3.11 it:
1. installs DocForge and the eval suite
2. checks the corpus code still builds the committed manifest (`corpus check`)
3. lints and runs the eval tests
4. runs all three suites without AI, in about a minute
5. checks the results against `evals/thresholds.yaml` (`gate`)
6. checks `RESULTS.md` and the main README's results table are up to date (`report --check`)

The run keeps its result files as an artifact named `no-ai-results`.

**What fails it**
- A key metric of a suite falls below its threshold, or a metric that should stay low rises
  above it. The thresholds sit at the committed no-AI results, and the path without AI is
  deterministic, so any drop is a real change, not noise.
- A material deviation that comply finds today is no longer found. The gate names each one.
- The results ran on other cases: another corpus, other notes or other analyze documents.

**When it fails**

| The gate says | What to do |
|---|---|
| `FAILED`, with lost detections or a metric marked `worse` | The change made something worse. Its table names the metric and the cases; find out why before anything else. |
| `PASSED`, and "Some results improved" | Raise the thresholds in the same PR: the three commands below, then commit `evals/results`, `evals/thresholds.yaml`, `evals/RESULTS.md` and `README.md`. |
| `corpus check` fails | The corpus code changed. Run `python -m evals corpus build`, commit `evals/corpus/manifest.json`, then raise the thresholds as above. |
| `report --check` fails | Run `python -m evals report` and commit `evals/RESULTS.md` and `README.md`. |

To raise the thresholds after an improvement, from the repo root:

```bash
python -m evals run --suite all --config evals/configs/no-ai.yaml
```

```bash
python -m evals gate --update
```

```bash
python -m evals report
```

**The Haiku job, by hand.** On GitHub, Actions → evals → Run workflow runs Claude Haiku 5.5 on the
suite you pick, with the spending cap you give (`max_usd`; the Haiku config never allows more
than 1.00). It needs your Anthropic key as the `ANTHROPIC_API_KEY` repository secret; without
it, the job stops before calling anything. The result file comes back as an artifact named
`haiku-results`, to download and commit.

## Run the AI modes on your PC (Windows, PowerShell)

The two AI runs need things that only your PC has: LM Studio with the local model, and your
Anthropic API key. Both runs happen in one PowerShell window. Type or paste each block, press
Enter, and wait for the prompt to come back before you type the next one.

**What you need**
- **Git for Windows**, and a clone of this repository.
- **Python 3.11 or newer.** `py --list` shows what's installed. 3.13 matches the no-AI baseline.
  To install it: `winget install Python.Python.3.13`.
- **LM Studio**, with Qwen 3.6-27b downloaded.
- **An Anthropic API key**, for the Haiku run only.

### 1. Open PowerShell in your clone

Open the Start menu, type `PowerShell`, and open **Windows PowerShell** or **Terminal**. Then go
to your clone. Replace the path with yours:

```powershell
cd C:\Users\you\code\docforge
```

### 2. Switch to the eval branch

```powershell
git status
```

If it lists changed files, commit them or put them aside with `git stash` first. Then:

```powershell
git fetch origin evals
```

```powershell
git checkout evals
```

```powershell
git pull origin evals
```

`git status` should now say `On branch evals` and `nothing to commit, working tree clean`. Each
result records whether the code had uncommitted changes, so start from a clean tree.

### 3. Create a Python environment (first time only)

```powershell
py -3.13 -m venv .venv
```

Use a version `py --list` showed, for example `py -3.12`. Git ignores the `.venv` folder.

### 4. Activate it (in every new window)

```powershell
.\.venv\Scripts\Activate.ps1
```

The prompt now starts with `(.venv)`. If PowerShell refuses because "running scripts is disabled
on this system", allow scripts for this window only, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

### 5. Install (first time, and after a pull that changes the requirements)

```powershell
python -m pip install -e backend -r evals/requirements.txt
```

This installs the backend as it is, unchanged, plus PyYAML and the pinned python-docx. The
first time takes a few minutes.

### 6. Start the model in LM Studio

1. Load **Qwen 3.6-27b** with a **context length of at least 16384** (in the load settings).
   Its chat template needs a one-line change first, or every judge call fails: in the template,
   replace `{{- raise_exception('System message must be at the beginning.') }}` with
   `{{- '<|im_start|>system\n' + message.content + '<|im_end|>\n' }}` (DESIGN.md §1.2 #19).
2. Load only this model. The config uses the one model LM Studio has loaded.
3. Start the server: Developer tab, Status: Running. It listens on `http://127.0.0.1:1234`.
4. Keep the PC awake until the run ends: a call cut off by sleep counts as a failed judge call.

### 7. The local run

Check the setup first: the same command as the full run below, plus `--dry-run`. This sends
nothing to the model:

```powershell
python -m evals run --suite comply --config evals/configs/local.yaml --repeat 3 --sample 10 --dry-run
```

The first time, it builds the test corpus (about 10 s). Then it shows the model LM Studio
serves, the model's context length, `cases the judge will see  82` and `repeat judge calls  20`.
If a `WARNING` line about the context appears, reload the model with a larger context (step 6).

Next, a test with two model calls, which takes about a minute. Its result goes to a temp folder,
not into `evals/results`:

```powershell
python -m evals run --suite comply --config evals/configs/local.yaml --types nda_en --limit 10 --out "$env:TEMP\docforge-evals-test"
```

Each case prints a progress line, from `[  1/10]` to `[ 10/10]`. The first eight say
`not_needed`, because those cases have no differences to judge. The last two should say `ran`.
If they say `failed`, stop and send the output.

Then the full run:

```powershell
python -m evals run --suite comply --config evals/configs/local.yaml --repeat 3 --sample 10
```

- **What it does.** It checks all 238 cases. The judge runs on the 82 cases with differences,
  and 10 of those are judged twice more to measure stability: 102 model calls in all.
- **How long it takes.** LM Studio answers one call at a time. Expect from about 15 minutes, if
  the whole model fits on the GPU, to over an hour, if part of it runs on the CPU.
- **At the end** it prints the table and `Result written to ...\evals\results\<date>_local_comply.json`.

If the run is interrupted (Ctrl+C, sleep, a crash), run the same command again. Answered calls
replay from the cache in `evals/cache/`, and only the rest go to the model. Don't re-run a run
that finished just because some calls failed: those failures are part of the measurement.

### 8. The Haiku run

Put the key into this window only. `Read-Host` hides the key as you paste it, and keeps it out of
PowerShell's history file:

```powershell
$key = Read-Host "Anthropic API key" -AsSecureString
```

```powershell
$env:ANTHROPIC_API_KEY = [System.Net.NetworkCredential]::new("", $key).Password; Remove-Variable key
```

The key now lives only in this window, until you close it. The evals never print or save it.

Check the setup (this sends nothing):

```powershell
python -m evals run --suite comply --config evals/configs/haiku.yaml --repeat 3 --sample 10 --dry-run
```

- **Spending cap** is `$1.00`, the config's cap, which is under €1. `--max-usd` can lower it,
  never raise it.
- **Temperature** is "not sent": DocForge sends none to Haiku 5.5, because the model takes no
  sampling parameters.
- **Estimated cost** is "unknown" on a first run. The first 3 judged cases then serve as a
  pilot, and the run stops if they project past the cap.

Then a test with two calls, which costs a fraction of a cent. As in the local test, the last two
progress lines should say `ran`. If they say `failed`, check the key:

```powershell
python -m evals run --suite comply --config evals/configs/haiku.yaml --types nda_en --limit 10 --out "$env:TEMP\docforge-evals-test"
```

Then the full run, which makes the same 102 calls in about 5 to 15 minutes:

```powershell
python -m evals run --suite comply --config evals/configs/haiku.yaml --repeat 3 --sample 10
```

DocForge prices Haiku 5.5 at $0.10 per million input tokens and $0.50 per million output tokens,
the same as Anthropic's list price. A judge call sends about a thousand tokens and gets a few
hundred back, so the expected cost is a few cents. Even if every call used DocForge's full
16,000-token output allowance, the run would cost about $0.83. It stops at $1.00 in any case. The
table at the end shows what it spent.

When you're done, remove the key, or close the window:

```powershell
Remove-Item Env:ANTHROPIC_API_KEY
```

### 9. Commit and push the two results

```powershell
git status
```

Only the two new files in `evals/results/` should be listed. Git may warn that "LF will be
replaced by CRLF"; that's harmless.

```powershell
git add evals/results
```

```powershell
git commit -m "Add the local and Haiku comply results"
```

```powershell
git push origin evals
```

To see the three modes side by side, give `compare` the three file names. The names start with
the date of the run (in UTC), so change `2026-11-26` in the last two names if yours differ. Tab
completes them:

```powershell
python -m evals compare evals/results/2026-11-26_no-ai_comply.json evals/results/2026-11-26_haiku_comply.json evals/results/2026-11-26_local_comply.json
```

**On macOS or Linux**, the commands are the same, except: activate with
`source .venv/bin/activate`, set the key with `read -rs ANTHROPIC_API_KEY && export
ANTHROPIC_API_KEY`, and use `/tmp/docforge-evals-test` for the test output.

## Run the generate suite on your PC (M3)

Same window and setup as the M2 guide above (steps 1 to 6). This time the key is needed for all
three runs: Claude Haiku 5.5 grades the free-text fields of each mode's documents, the no-AI
ones included.

### 1. Update and set the key

```powershell
git pull origin evals
```

```powershell
$key = Read-Host "Anthropic API key" -AsSecureString
```

```powershell
$env:ANTHROPIC_API_KEY = [System.Net.NetworkCredential]::new("", $key).Password; Remove-Variable key
```

### 2. The no-AI run (about a minute)

```powershell
python -m evals run --suite generate --config evals/configs/no-ai.yaml --dry-run
```

It should say `free-text grader  claude-haiku-5-5`, `notes cases  35 (7 types)` and
`cases that call a model  25`: those are the cases with free text to grade (invoices have none).

```powershell
python -m evals run --suite generate --config evals/configs/no-ai.yaml
```

### 3. The Haiku run (10 to 15 minutes)

```powershell
python -m evals run --suite generate --config evals/configs/haiku.yaml --repeat 3 --sample 10 --dry-run
```

It should say `cases that call a model  35`, `repeat runs  20` and `spending cap  $1.00`. Then a
one-case test, whose result goes to a temp folder. Its progress line should say `writer`:

```powershell
python -m evals run --suite generate --config evals/configs/haiku.yaml --types nda_en --limit 1 --out "$env:TEMP\docforge-evals-test"
```

If it says `llm` or `heuristic` instead, the writer failed; stop and send the output. Otherwise:

```powershell
python -m evals run --suite generate --config evals/configs/haiku.yaml --repeat 3 --sample 10
```

Expected cost: about $0.25 with grading, and it stops at $1.00 in any case.

### 4. The local run (about 2 hours)

LM Studio as in M2: Qwen 3.6-27b with the template change, at least 16384 context, server on,
and the PC kept awake.

```powershell
python -m evals run --suite generate --config evals/configs/local.yaml --repeat 3 --sample 10 --dry-run
```

```powershell
python -m evals run --suite generate --config evals/configs/local.yaml --types nda_en --limit 1 --out "$env:TEMP\docforge-evals-test"
```

Again, the progress line should say `writer`. Then:

```powershell
python -m evals run --suite generate --config evals/configs/local.yaml --repeat 3 --sample 10
```

The writer and the review run for every case, one call at a time. If the run is interrupted,
run the same command again; answered calls replay from the cache.

### 5. Commit and push the three results

```powershell
git status
```

Only three new files in `evals/results/` should be listed (`*_generate.json`).

```powershell
git add evals/results
```

```powershell
git commit -m "Add the no-AI, Haiku and local generate results"
```

```powershell
git push origin evals
```

Remove the key when you're done (`Remove-Item Env:ANTHROPIC_API_KEY`), or close the window.

## Run the analyze suite on your PC (M4)

Same window and setup as the M2 guide above (steps 1 to 6). Only the Haiku run needs the key;
analyze has no grader.

### 1. Update

```powershell
git pull origin evals
```

### 2. The no-AI run (about a minute)

```powershell
python -m evals run --suite analyze --config evals/configs/no-ai.yaml --dry-run
```

It should say `templates to build  45 (9 types)`. Then:

```powershell
python -m evals run --suite analyze --config evals/configs/no-ai.yaml
```

### 3. The Haiku run (about 25 minutes)

Set the key, as in M3:

```powershell
$key = Read-Host "Anthropic API key" -AsSecureString
```

```powershell
$env:ANTHROPIC_API_KEY = [System.Net.NetworkCredential]::new("", $key).Password; Remove-Variable key
```

```powershell
python -m evals run --suite analyze --config evals/configs/haiku.yaml --repeat 3 --sample 10 --dry-run
```

It should say `cases that call a model  45`, `repeat runs  20` and `spending cap  $1.00`. The
estimated cost says `unknown`: this is the first analyze run with Haiku, so the first 3 cases are
a pilot, and the run stops if they project past the cap. Then a one-case test, whose result goes
to a temp folder. Its progress line should say `llm`:

```powershell
python -m evals run --suite analyze --config evals/configs/haiku.yaml --types nda_en --limit 1 --out "$env:TEMP\docforge-evals-test"
```

If it says `heuristic_fallback` instead, the AI classifier failed; stop and send the output.
Otherwise:

```powershell
python -m evals run --suite analyze --config evals/configs/haiku.yaml --repeat 3 --sample 10
```

Expected cost: about $0.25 to $0.50, and it stops at $1.00 in any case.

### 4. The local run (about 3 hours)

LM Studio as in M2 and M3: Qwen 3.6-27b with the template change, at least 16384 context, server
on, and the PC kept awake.

```powershell
python -m evals run --suite analyze --config evals/configs/local.yaml --repeat 3 --sample 10 --dry-run
```

```powershell
python -m evals run --suite analyze --config evals/configs/local.yaml --types nda_en --limit 1 --out "$env:TEMP\docforge-evals-test"
```

Again, the progress line should say `llm`. Then:

```powershell
python -m evals run --suite analyze --config evals/configs/local.yaml --repeat 3 --sample 10
```

Each analysis makes three or four model calls (a read-through, the classification, a
self-critique), one at a time. If the run is interrupted, run the same command again; answered
calls replay from the cache.

### 5. Commit and push the three results

```powershell
git status
```

Only three new files in `evals/results/` should be listed (`*_analyze.json`).

```powershell
git add evals/results
```

```powershell
git commit -m "Add the no-AI, Haiku and local analyze results"
```

```powershell
git push origin evals
```

Remove the key when you're done (`Remove-Item Env:ANTHROPIC_API_KEY`), or close the window.

## Read the analyze table

Each case is one template: DocForge analyses some example documents of a type and publishes a
template, and every element of the example it took as its representative is scored against the
ground truth. The table has one row per number of examples.

| Line | Meaning |
|---|---|
| field F1 | How well fields were told from boilerplate: true fields found (tp), boilerplate turned into fields (fp), fields missed (fn). Counts top-level elements and the cells of information blocks. |
| boilerplate kept | Fixed text (titles, headings, clauses, fixed labels) the template keeps as fixed text |
| types right | Found fields whose DocForge type fits: a date as date, an amount as number, a name as person |
| tables | Repeating tables found with their header row as the columns |
| layout kept | The template keeps the document's blocks in order with their styles, fixed text unchanged, labels before fields, and every row of an information block |
| information blocks | What became of each "label \| value" block: `form` (labels fixed, values fields: right), `frozen` (values became boilerplate), `looped` (a repeating table: the labels became row data), `partial` |
| shared value still a field | Two examples that share one value (the same customer, say): is it still a field? |
| page numbers as auto fields | The footer's page number recognised as automatic content |
| classified by | `llm` (AI), `heuristic` (no AI), or `heuristic_fallback` (AI was on but failed) |

## Read the generate table

Each notes case is one rough-notes text: bullet points, an email, German and English mixed, notes
with missing information, or notes that correct one of their own values. DocForge fills the
type's template from it, and every field is scored against the values the notes give.

| Line | Meaning |
|---|---|
| short fields right | Fields the notes give, filled with that value in any form (`08.04.2026` = `April 8, 2026`) |
| left empty though given | Fields the notes give, left empty or filled with a placeholder such as "TBD" |
| hallucinated | Values in no form in the notes, out of the values written. The headline number. A placeholder doesn't count: it states nothing. |
| flagged as AI-drafted | Of the hallucinations, those DocForge marked as drafted, so the app shows them for review |
| from the notes, but wrong | Values from the notes in the wrong field, or a value the notes later correct |
| empty where the notes are silent | Fields the notes don't give, rightly left empty |
| dates/amounts in template form | Right dates and amounts written as the template writes them (a German date in a German document) |
| tables | Rows matched in any order: the right row count, cells right, and cells in no form in the notes |
| free text | Values written for the services, purpose, agenda and decisions; the grader's verdicts on faithful (nothing added) and complete (every expected point) |
| layout kept | Every fixed block, field label and table header of the template is still there, in order |
| written by | The engine that wrote each document: `writer` (AI, one pass), `llm` (AI route and compose, when the writer failed) or `heuristic` (no AI) |

## Read the comply table

Each case is one held-out document that carries one injected deviation, or none (a clean
control). It is checked against a template DocForge built from 5 example documents.

| Column / line | Meaning |
|---|---|
| `found` | Cases where DocForge reported a difference on the changed element. For inserted paragraphs, the count shows the inserted text as extra content in the comparison. |
| `kind ok` | Of those found, how many were reported as the expected kind (`changed_fixed`, `missing_table`, …) |
| `alarms` | Cases with at least one difference of severity error or warning, anywhere in the document |
| `score` | Mean compliance score (0–100) DocForge gave those cases |
| material deviations found | Recall over every deviation labelled material |
| benign changes that alarm / clean controls that alarm | False alarms. In AI modes they use the severity after the judge. |
| score AUC | Chance that a clean document scores higher than one with a material deviation (0.5 = no separation, 1.0 = perfect) |
| fix success | Material boilerplate damage that `fix_document` fully repaired, judged against the clean original. The re-check alone can't see what the check missed. The fixer uses no AI, so it's measured in the no-AI run only. |

**AI modes** add these lines:

| Line | Meaning |
|---|---|
| verdicts: material precision / recall / accuracy | The judge's material-or-benign calls on each difference it saw, against the labels. A difference on the injected deviation takes the deviation's label; any other difference is benign. |
| not judged | Differences without a verdict (past the judge's 40-item limit, or missing from its answer) |
| judge fell back | Cases with differences where the judge gave no result, so the report has no semantic score. DocForge doesn't flag these; the evals see them. |
| semantic AUC | Like score AUC, on the judge's semantic score. A case with no differences counts as 100. |
| material still alarming | Found material deviations that still have an error or warning on them after the judge |
| cost | DocForge's own price estimate: total (live and replayed from the cache), per document, and per judged document. `$0` for a local model. |
| cache hit rate | Model calls answered from the cache instead of the model |
| failed AI calls by kind | Model calls that raised an error, per kind of call |
| stability | With `--repeat`: how often a difference keeps the same verdict across runs, and the mean spread of the semantic score |

Every rate shows its counts, as in `0.61 (62/102)`.

## What a result file holds

Every result file records the git SHA, DocForge's version, the config, the corpus hash and every
case's record. Any number can therefore be traced and reproduced. Numbers are only ever written
by a run, never by hand.

It also records what in your working tree differed from that commit. Result files never count.
- `dirty`: any uncommitted change.
- `dirty_code`: a change under `backend/` or `evals/`, which a run executes or reads. When it's
  `true`, the run says so before it starts, and the result doesn't match the commit exactly.
- `changed_files`: the tracked files that differ, such as a locally edited editor setting.
- `untracked_files`: how many untracked files there were. Their names are never recorded.

AI runs also record:
- the model and host, the efforts, and whether the temperature was sent at all
- live and replayed spend, the cache hit rate, the budget plan, and whether the run stopped early
- per case: the judge's verdicts, its calls with their outcomes, and the tokens used

They never record the key.

Generate results also record a hash of the notes cases (`notes_hash`), so `compare` can tell
whether two runs used the same notes, and what the grader did and spent (`grader`). Analyze
results record `analyze_hash`, the hash of the documents only analyze uses.

## Rules for this folder

- Nothing under `backend/` or `frontend/` is ever changed.
- All eval work stays on the `evals` branch.
- Every company and person in the corpus is invented ([corpus/NAMES.md](corpus/NAMES.md)).
- Hand-made test documents follow [corpus/handmade/README.md](corpus/handmade/README.md).
