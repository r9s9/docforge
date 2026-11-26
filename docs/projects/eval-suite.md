# DocForge Evaluation Suite & Case Study — Project Brief

> **How to use this file**
> 1. Create a branch in the DocForge repo: `git checkout -b evals`
> 2. Save this file as `docs/projects/eval-suite.md`.
> 3. Start Claude Code in the repo root and say:
>    *"Read docs/projects/eval-suite.md. Add its 'Working rules for Claude Code' section to CLAUDE.md (create CLAUDE.md if it doesn't exist). Then do Milestone 0 in plan mode and wait for my approval."*
> 4. Work one milestone at a time. Review the plan before each one.

---

## 1. Why this project exists

DocForge is live at docforge.live and the code is open source. That proves I can ship. What it doesn't prove yet is that **the AI parts work, how well they work, what they cost, and when no AI is the better choice.** Those are the first things a hiring manager for an AI Deployment Strategist, Forward Deployed Engineer or AI Platform PM role will ask about.

This project adds a reproducible **evaluation suite** to DocForge and turns the results into a **public case study**. When it's done, I can answer in an interview:

- *"How do you know your AI system works?"* — Here's the test set, the metrics and the results per model.
- *"How did you choose the model?"* — Here's quality vs. cost vs. speed for each mode, including a local model and no AI.
- *"What happens when the AI is wrong?"* — Here's the hallucination rate, the fallback rate and how the deterministic engine catches it.
- *"What did you change because of the data?"* — Here's the weakest result, the fix, and the before/after numbers.

## 2. Goals and non-goals

**Goals**
- Measure quality for all three DocForge pipelines: **analyze** (build a template), **generate** (fill it from notes), **comply** (check a returned document).
- Compare AI modes side by side: no AI, Claude Haiku 5.5 (the shipped default), a stronger Claude model, and a local model.
- Measure **cost per document**, **latency** and **fallback rate** for every mode.
- Run the free, deterministic part in CI on every pull request as a regression gate.
- Publish a results table, a one-page case study and supporting product documents.

**Non-goals**
- No changes to product behavior inside eval PRs. Bugs found by the suite become GitHub issues and get fixed in separate PRs, with before/after numbers.
- No real customer, client or employer documents. Everything is synthetic or written by me.
- Not a general LLM benchmark. Every test is a DocForge task.
- No load or performance testing of the hosted app. Evals run locally with my own API key, never against app.docforge.live.

## 3. What the repo already provides

Checked against the code at v0.21.0. **Claude Code must re-check these in Milestone 0** because code may have moved.

| Area | Where | What it gives us |
|---|---|---|
| Analyze pipeline | `backend/docforge/services/analysis.py` → `analyze_documents(db, sources, mode="smart")` | Builds a template from 1–5 stored documents. Modes: smart detect / full template. |
| Generate pipeline | `backend/docforge/services/generation.py` → `generate_document(db, template, gen_input)` | `GenerationMode`: `structured_json`, `structured_form`, `unstructured_text` (rough notes). |
| Comply pipeline | `backend/docforge/services/compliance.py` → `check_document(db, template, filename=, data=)` | Deterministic `check_compliance` (structure / fields / tables), then the optional AI `judge_compliance`. |
| Difference kinds | `backend/docforge/schemas/compliance.py` | `missing_fixed`, `changed_fixed`, `missing_field`, `format`, `missing_table`, `table_shape`, with severities. |
| AI judge | `backend/docforge/compliance/judge.py` | Labels each difference material or benign and adds a `semantic` score. Caps at 40 differences. It adds to the deterministic score but never overrides it. |
| Fixer | `backend/docforge/services/compliance_fix.py` → `fix_document(...)` | Restores changed or missing boilerplate. |
| AI config | `backend/docforge/settings_store.py` → `AIConfig` | Providers: Anthropic and anything OpenAI-compatible (OpenAI, Gemini, OpenRouter, Ollama, LM Studio). Workhorse and reasoning tiers, effort levels. |
| Cost tracking | `backend/docforge/ai/usage.py` → `track_usage()`; `ai/pricing.py` | Tokens, cache reads and writes, and cost per call and per model. |
| Fallback | AI client and services | A failed AI step falls back to the deterministic engine. |
| Sample data | `backend/docforge/sampledata.py` | Deterministic builders: project report, invoice, compliance report, service agreement. |
| Tests | `backend/tests/` (unit, integration, snapshot, audit) | Hermetic pytest with stubbed AI. `conftest.py` shows how to get an isolated SQLite session and data directory. |
| CI | none yet | No `.github/workflows`. This project adds the first workflow. |

## 4. What we measure

### 4.1 Analyze: building a template

Ground truth: for every element in the example documents, whether it is **fixed** boilerplate, a **variable field** (with its type) or a **repeating table**.

| Metric | Definition |
|---|---|
| Field precision / recall / F1 | Variable elements correctly detected as fields |
| Boilerplate preservation | Share of fixed elements kept fixed (a fixed element wrongly turned into a field is an error) |
| Field type accuracy | Date, money, number, text and so on, where the template assigns types |
| Repeating table detection | Repeating tables found, with the correct header row |
| Layout fidelity | The published template's structure matches the source (reuse the approach in `test_template_keeps_its_layout.py`) |

Compare each metric by number of examples (1, 2, 3, 5) to see how many examples a user really needs.

### 4.2 Generate: filling from rough notes (`unstructured_text`)

Ground truth: the notes text plus the expected value for each field.

| Metric | Definition |
|---|---|
| Field accuracy | Normalized exact match for short fields (dates, amounts, names). Free-text fields graded by a rubric (see 6.4). |
| Omission rate | Fields that had a value in the notes but were left empty |
| **Hallucination rate** | Fields filled with a value that isn't supported by the notes. **This is the headline metric.** |
| Table row accuracy | Correct number of repeated rows, with correct cell values |
| Layout preserved | Output `.docx` structure matches the template |

### 4.3 Comply: checking a returned document

Ground truth: deviations injected on purpose, each labeled with a **kind** and **material: yes/no**.

| Metric | Definition |
|---|---|
| Detection recall per kind | Injected deviations found |
| False alarm rate | Differences reported on clean control documents |
| Material vs. benign accuracy | Confusion matrix for the AI judge (precision and recall on "material") |
| Score separation | Clean documents vs. documents with material deviations: does the score separate them? |
| Fix success | After `fix_document`, a re-check passes **and** the filled-in values are unchanged |

### 4.4 Measured for every run

- Cost per document (USD), from `track_usage()`
- Latency p50 / p95 per pipeline step
- Fallback rate: how often an AI step fell back to the deterministic engine
- Error rate
- Stability: run a sample of cases 3 times and report how much the results vary

### 4.5 Modes to compare

Defined as YAML configs, so model names are never hard-coded:

| Config | Purpose |
|---|---|
| `no-ai.yaml` | Deterministic baseline, free, runs in CI |
| `haiku.yaml` | Shipped default (`claude-haiku-5-5`) |
| `sonnet.yaml` | Stronger model (`claude-sonnet-5-5`): is it worth the price? |
| `local.yaml` | A local model through Ollama or LM Studio (OpenAI-compatible): the data-stays-in-house option |
| *(optional)* `gemini.yaml` | A cheap non-Anthropic baseline |

## 5. The test corpus

### 5.1 Synthetic documents (most of the corpus)

Extend the patterns in `sampledata.py` into a deterministic corpus generator under `evals/corpus/`. Use fixed seeds, no clock and no randomness without a seed.

**Document types** (at least 6):
- Vendor service agreement (EN + **DE**)
- NDA (EN + **DE**)
- Data protection impact assessment (DPIA)
- Invoice (EN + DE)
- Project status report
- Meeting minutes with an action-item table

German versions matter: the target job market is Munich, and German business documents have their own formats (dates like 23.11.2026, amounts like 1.234,56 €, "Gerichtsstand", and so on).

**Per document type:**
- 5 filled example documents (input for analyze)
- 3+ held-out filled documents (ground truth for analyze and comply)
- 3+ rough-notes texts with expected field values (input for generate). Vary them: bullet points, email style, German/English mix, missing information, a contradiction.
- Mutated documents for comply (see 5.2)

### 5.2 Mutation library

Each mutator takes a clean `.docx` and returns `(mutated_docx, label)`. Labels go into `evals/corpus/manifest.json`.

| Mutator | Kind | Material? |
|---|---|---|
| Change liability cap amount | `changed_fixed` | yes |
| Change governing law / Gerichtsstand | `changed_fixed` | yes |
| Change notice period | `changed_fixed` | yes |
| Delete confidentiality clause | `missing_fixed` | yes |
| Fix a typo in boilerplate | `changed_fixed` | no |
| Double space / punctuation / curly quotes | `changed_fixed` | no |
| Change capitalisation of a heading | `changed_fixed` | no |
| Empty a required field | `missing_field` | yes |
| Change date format (23.11.2026 → 2026-11-23) | `format` | no (or yes, by rule) |
| Remove a table row | `table_shape` | depends on the table |
| Remove a table column | `table_shape` | yes |
| Delete a whole table | `missing_table` | yes |
| Reorder two sections | structural | no |
| Insert an extra paragraph | structural | depends on the content |
| **No change (clean control)** | — | — |

Every mutator gets a unit test. Clean controls make up at least 20% of comply cases.

### 5.3 A small "messy" set made by hand

Synthetic documents are too clean. I'll make 10–20 documents by hand in Word: accepted tracked changes, text pasted from email, broken styles, a converted PDF. I label them myself. No third-party or employer documents.

### 5.4 Size and cost

Target 150–300 cases in total. A full AI run on one config should cost a few dollars at most. Generated `.docx` files are rebuilt from the generator, so they don't need to be committed. Commit the generator, the manifest and the hand-made set.

## 6. Architecture

### 6.1 Layout

```
evals/
  README.md            # how to run, how to read results
  DESIGN.md            # written in Milestone 0
  __main__.py          # python -m evals ...
  configs/             # no-ai.yaml, haiku.yaml, sonnet.yaml, local.yaml
  corpus/
    generator.py       # deterministic document builders
    doc_types/         # one module per document type, EN/DE
    mutators.py
    notes/             # rough-notes inputs + expected values
    handmade/          # the messy set (committed)
    manifest.json      # every case + its labels
  runners/
    analyze.py
    generate.py
    comply.py
  metrics/             # pure functions, unit-tested
  graders/             # rubric grader for free-text fields
  cache/               # cached model responses (gitignored)
  results/             # <date>_<config>_<suite>.json (committed)
  RESULTS.md           # generated summary table
tests/evals/           # tests for mutators, metrics, the grader
```

`evals/` stays outside `backend/docforge/` so it never ships with the app. It calls the **real service functions** with an isolated SQLite session and temporary data directory, the same way `backend/tests/conftest.py` does. **Never copy pipeline logic into the eval code.** The point is to test the real thing.

### 6.2 CLI

```bash
python -m evals corpus build                                  # build the corpus
python -m evals run --suite comply --config configs/no-ai.yaml
python -m evals run --suite all --config configs/haiku.yaml --max-usd 3
python -m evals report                                        # rebuild RESULTS.md from results/
python -m evals compare results/A.json results/B.json        # what got better or worse
```

### 6.3 Required behavior

- **Budget guard:** estimate the cost before a run, stop if `--max-usd` would be exceeded, and print the actual cost at the end. Default cap: $3.
- **Response cache:** keyed by config + case + prompt hash, so metrics can be recomputed without paying again. `--no-cache` forces fresh calls.
- **Reproducibility:** every result file records git SHA, DocForge version, config, model IDs, date, corpus hash and the number of cases.
- **No invented numbers:** `RESULTS.md` is only ever written by `python -m evals report`. Never edit it by hand.

### 6.4 Grading free-text fields

Use a rubric-based LLM grader **only** where exact match can't work (summaries, descriptions).
- Use a different model from the one being tested, where that's possible.
- Check the grader against 30 items I label by hand, and report how often it agrees with me. If it agrees less than 85% of the time, don't use it. Fall back to manual review of a sample.

### 6.5 CI

New workflow `.github/workflows/evals.yml`:
- On every PR: build the corpus, run all suites with `no-ai.yaml`, and fail if any key metric drops below the thresholds stored in `evals/thresholds.yaml`.
- Manual trigger (`workflow_dispatch`) for AI configs, using an `ANTHROPIC_API_KEY` repository secret and a hard `--max-usd` cap.

## 7. Milestones

About 3 weeks of evenings. Each milestone ends with a short entry in `evals/CHANGELOG.md`: what was built, what was learned, what changes next.

**M0 — Recon and design (½ day)**
Read the code. Confirm the entry points in section 3. Write `evals/DESIGN.md` covering how each runner calls the services, how ground truth maps to DocForge's element and field IDs, and any open questions. *No code changes.*
✅ Accepted when I approve `DESIGN.md`.

**M1 — Corpus and deterministic comply suite (first numbers)**
Corpus generator with at least 4 document types (2 in German), at least 10 mutators, the manifest, and the `comply` runner with `no-ai.yaml`, metrics and a JSON result file.
✅ `python -m evals run --suite comply --config configs/no-ai.yaml` runs in under 2 minutes and prints a table. Mutator and metric tests pass.

**M2 — AI modes for comply**
Haiku, Sonnet and local configs. Judge confusion matrix. Cost, latency and fallback rate. Budget guard and cache.
✅ One results table compares 4 modes on the same cases.

**M3 — Generate suite**
Notes inputs with expected values. Field accuracy, omission and hallucination metrics. Rubric grader checked against my labels.
✅ Hallucination rate reported per mode, with 5 example failures written up.

**M4 — Analyze suite**
Field detection F1, boilerplate preservation, table detection, and the 1/2/3/5-example comparison.
✅ A chart or table shows how quality changes with the number of examples.

**M5 — CI gate and results page**
`evals.yml`, `thresholds.yaml`, and a generated `RESULTS.md`. Add a short "How well does it work?" section to the main README that links to it.
✅ A PR that breaks a mutator-detected case fails CI.

**M6 — "Fix one thing"**
Pick the weakest result from M2–M4. Open an issue, fix it in a separate PR, rerun, and record before and after.
✅ The improvement shows up in `compare` output. **This becomes the main story in the case study.**

**M7 — Case study and product documents** (section 8)
✅ Everything in section 8 exists and is linked from the README.

## 8. Product documents to produce (the PM half of the portfolio)

| Document | Path | Content |
|---|---|---|
| PRD (written after the fact) | `docs/product/PRD.md` | Problem, users, jobs to be done, scope, success metrics |
| Decision records | `docs/decisions/ADR-00x-*.md` | Why edit the Word XML instead of regenerating the document. Why a deterministic engine plus an AI fallback. Why several providers. Why Haiku is the default, **backed by eval numbers**. Why the judge adds to the score instead of overriding it. |
| Roadmap | `docs/product/roadmap.md` | Now / Next / Later, informed by the eval results |
| Usage summary | `docs/product/usage.md` | **Totals only** from the hosted app: accounts, templates, documents generated, compliance checks, AI vs. no-AI share. No personal data. Check the privacy policy covers this first. |
| Case study | `docs/case-study.md` | One page: problem → constraints → decisions → results → what I'd do differently |
| Demo video script | `docs/demo-script.md` | 2 minutes: upload examples → template → fill from notes → check a changed contract → results table |
| LinkedIn post draft | `docs/linkedin-post.md` | Lead with one surprising finding from the data |

Results table template for the README and case study. **Fill it only from generated results.**

| Mode | Deviation recall | False alarms | Material/benign acc. | Field acc. (notes) | Hallucination rate | Cost / doc | p50 latency |
|---|---|---|---|---|---|---|---|
| No AI | | | n/a | | | $0 | |
| Claude Haiku 5.5 | | | | | | | |
| Claude Sonnet 5.5 | | | | | | | |
| Local model | | | | | | $0 (hardware) | |

## 9. Guardrails

- **Data:** synthetic or self-made documents only. No employer, client or third-party documents, and no real names of people or companies in the corpus. Invent them, and check that invented company names aren't real ones.
- **Product behavior:** eval PRs don't change `backend/docforge/` except for small, reviewed hooks if a runner truly needs one. Discuss those first.
- **Money:** respect `--max-usd`. **Ask me before any run that would cost more than $3.**
- **Secrets:** keys come only from environment variables or `.env` (already gitignored). Never print keys or write them to result files.
- **Honesty:** never edit result files or the results table by hand. If a metric looks wrong, investigate and document the cause; don't adjust it.
- **Hosted app:** don't run evals against app.docforge.live or use its free-tier quota.

## 10. Working rules for Claude Code

*(Copy this section into CLAUDE.md.)*

- Start every milestone in **plan mode**. Show the plan and wait for approval before writing code.
- Work on the `evals` branch. Make small commits with clear messages, one logical change each.
- Before each commit, run `cd backend && pytest -q` and `ruff check docforge`. Also run the eval tests under `tests/evals/`.
- Python 3.11, ruff line length 100, type hints on public functions.
- Metrics are code: test each metric function on tiny cases calculated by hand.
- Ask before you: add a dependency, change anything under `backend/docforge/`, spend more than the budget cap, or delete files.
- After each milestone, update `evals/README.md` and `evals/CHANGELOG.md`.
- If the code doesn't match this brief (a function moved or a signature changed), follow the code, note the difference in `DESIGN.md`, and tell me.

## 11. Definition of done

- [ ] `python -m evals corpus build && python -m evals run --suite all --config configs/no-ai.yaml` reproduces the deterministic results on a fresh clone
- [ ] AI results for at least 3 modes, each with git SHA, date and cost
- [ ] CI gate is active on PRs
- [ ] One documented improvement, with before/after numbers (M6)
- [ ] README has a "How well does it work?" section with the results table
- [ ] Case study, decision records, PRD, roadmap and demo script are in `docs/`
- [ ] LinkedIn post drafted
