# DocForge evals

This suite measures how well DocForge's pipelines work, from the outside. It calls the app's real
service functions in an isolated sandbox and never changes the app's code.

**Status:** M2 done (2026-11-26). The **comply** suite runs in three modes: AI off, Claude
Haiku 5.5, and a local model in LM Studio. The two AI runs happen on the owner's PC
([guide below](#run-the-ai-modes-on-your-pc-windows-powershell)). The three-way comparison is in
the changelog's M2 entry. Generate and analyze arrive in M3 and M4.

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

**What each command does**
- **`corpus build`** writes the 91 documents and 238 comply cases to `evals/corpus/build/`
  (gitignored) in about 10 s, and rewrites `evals/corpus/manifest.json`. That file is committed,
  so a build that changes it means the corpus code changed.
- **`run`** prints a table and writes `evals/results/<date>_<config>_comply.json`. With AI off,
  the whole comply suite takes about 40 s. A missing build is created first. If the corpus code
  no longer matches the committed manifest, the run stops.
  - `--types invoice_en nda_de`: only some types.
  - `--limit 3`: at most 3 cases per type, for smoke runs.
  - `--out DIR`: write the result file somewhere else.
  - `--keep-sandbox`: keep DocForge's temp database and data dir for debugging.
  - AI modes only: `--dry-run`, `--repeat`, `--sample`, `--max-usd`, `--model`, `--no-cache`
    (see the guide below and `python -m evals run --help`).
- **`compare A.json B.json [C.json ...]`** prints the results side by side, and the cases whose
  alarm status changed from the first file to each of the others. Add `--markdown` for a table
  to paste into docs.

The tests run from the repo root:

```bash
python -m pytest tests/evals -q
```

```bash
ruff check --config evals/ruff.toml evals tests/evals
```

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

## Rules for this folder

- Nothing under `backend/` or `frontend/` is ever changed.
- All eval work stays on the `evals` branch.
- Every company and person in the corpus is invented ([corpus/NAMES.md](corpus/NAMES.md)).
- Hand-made test documents follow [corpus/handmade/README.md](corpus/handmade/README.md).
