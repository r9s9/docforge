# Evals changelog

One entry per milestone: what was built, what was learned, what comes next.

## M2: AI modes for the comply suite (2026-11-26)

**Built**
- **Configs.**
  - `haiku.yaml`: Claude Haiku 5.5, DocForge's shipped default, with the owner's €1 cap as
    `max_usd: 1.00`.
  - `local.yaml`: LM Studio on the owner's PC, with the model it has loaded and thinking off.
- **Response cache** over both of DocForge's HTTP paths. The Anthropic SDK uses `httpx2`, the
  LM Studio path `httpx`. Contract tests replay recorded answers through the real client.
- **Call observer**: every AI call's outcome, the judge's verdicts, and the spend.
- **Budget guard**: the stricter cap wins, a pilot when there's no estimate, a hard stop.
- **Judge metrics**: confusion matrix, semantic AUC, material alarms kept, fallback rate,
  stability across repeats.
- **`python -m evals compare`**: the table below and the cases whose alarm changed.
- **A PowerShell guide** for the owner's PC (README).
- **Results.** Both AI runs ran on the owner's PC (Windows, Python 3.13.17) at commit
  `af6857d`, on the same corpus (`d2f7d14ee960`; the files matched the manifest byte for byte).
  The no-AI baseline is M1's, from the Linux cloud container.

  | Result | Time | Errors | Stopped early |
  |---|---|---|---|
  | `results/2026-11-26_haiku_comply.json` | 292 s | 0/238 | no |
  | `results/2026-11-26_local_comply.json` | 1,510 s | 0/238 | no |

  Both files record `dirty: true`: the owner's tree had uncommitted changes outside
  `evals/results` during the runs. What they were is being checked.

**The M2 table** (`python -m evals compare`; every number comes from the three result files)

| metric | no AI | Haiku 5.5 | Qwen 3.6-27b (local) |
|---|---|---|---|
| material deviations found | 0.61 (62/102) | 0.61 (62/102) | 0.61 (62/102) |
| material still alarming | 1.00 (56/56) | 1.00 (56/56) | 0.86 (48/56) |
| benign changes that alarm | 0.30 (24/80) | 0.12 (10/80) | 0.12 (10/80) |
| clean controls that alarm | 0.00 (0/56) | 0.00 (0/56) | 0.00 (0/56) |
| judge: material precision | n/a | 0.67 (65/97) | 0.65 (60/92) |
| judge: material recall | n/a | 0.96 (65/68) | 0.88 (60/68) |
| judge: accuracy | n/a | 0.69 (79/114) | 0.65 (74/114) |
| judge fell back | n/a | 0.00 (0/82) | 0.00 (0/82) |
| judge stable across repeats | n/a | 1.00 (14/14) | 1.00 (14/14) |
| score AUC clean > material | 0.78 | 0.78 | 0.78 |
| semantic AUC clean > material | n/a | 0.77 | 0.75 |
| cost per judged document | $0 | $0.0002 | $0 (hardware) |
| total cost, repeats included | $0 | $0.0224 | $0 (hardware) |
| check latency p50 / p95, cases with differences | 62 / 113 ms | 2.6 / 4.4 s | 11.9 / 28.6 s |

**Learned** (this corpus; Haiku and Qwen as configured above)
- **The judge can't find what the check missed.** Detection is 62/102 in every mode, so the
  misses from M1 stay misses: the small edits inside boilerplate (H1), the removed rows and
  columns, and the inserted clauses (H6). The judge only sees reported differences, and only 82
  of the 238 cases have any.
- **What the judge does well: it removes the all-caps false alarms.** Benign changes that alarm
  fall from 24/80 to 10/80 in both modes. All 14 all-caps headings were downgraded.
- **What it doesn't: reordered sections.** Both models call every difference from a reordered
  section material (24 differences, 8/8 cases still alarm). The ground truth calls a reorder
  benign, and that's arguable, but it accounts for 24 of each model's 32 false positives.
  - Another 4 are deletions labelled benign: the minutes' distribution note, 2/2 still alarm.
  - The last 4 are differences off the injected deviation's target, in material cases. Two are
    the English NDA's inserted unlimited-liability clause, which alignment paired with the
    original clause (M1); two are a second missing paragraph next to a deleted German NDA
    clause. Calling those material is substantively right. They count as false positives only
    because the difference isn't on the target.
- **Where the two models differ: placeholder dates.** A date field changed to "TBD" or "offen"
  is labelled material.
  - Qwen called 8 of the 14 benign ("a standard placeholder") and downgraded them to info.
    That's the whole drop in material still alarming, to 48/56, and in recall, to 0.88.
  - Haiku called 3 of the 14 benign, but kept their warning severity, so every found material
    deviation still alarms. These 3 are all of Haiku's missed material calls.
- **The judge doesn't change the score or the grade**, as designed. Score AUC is 0.78 and the
  grade table is identical in all three modes. 100 of the 102 material documents still pass.
- **The semantic score adds little separation.** Its AUC (0.77 Haiku, 0.75 Qwen) is no better
  than the deterministic score's 0.78. The score is 100 × (1 − material ÷ differences), and with
  1 to 3 differences called the same way, it was 0 or 100 for every judged case.
- **Both judges were fully stable.** 10 sampled cases, judged three times each: 14/14 verdicts
  identical and no semantic spread, for Haiku too, which DocForge runs without a temperature.
- **Out of the box, the local judge fails on every call, silently.** DocForge's
  OpenAI-compatible path starts each call with two system messages. Qwen 3.6's chat template in
  LM Studio allows a system message only first, so every judge call failed in about 30 ms, and
  the report simply had no semantic score. With a one-line change to the template on the
  owner's PC (it renders the second system message instead of rejecting it), all 82 calls
  succeeded. The app wasn't changed. Anyone running DocForge with this model needs the same
  change or a fix in DocForge.
- **No fallbacks once it worked.** 0/82 judge failures in both runs. The local run made 104 HTTP
  requests for its 102 calls, which points to 2 retries inside calls that then succeeded.
- **Cost.** Haiku's whole run, repeats included, cost $0.0224 by DocForge's prices, which match
  Anthropic's list price. That's $0.0002 per judged document, about 1,690 input and 370 output
  tokens per call. The cap was $1.00.
- **Speed.** The judge dominates check latency on the cases it sees: Haiku 2.6 s at p50 and
  4.4 s at p95, against about 60 ms for the deterministic check. Qwen 3.6-27b (Q4_K_M, 19.9k
  context, on the owner's PC) took 11.9 s at p50 and 28.6 s at p95, and 25 minutes for the whole
  run. Qwen wrote about 910 output tokens per call against Haiku's 370, despite thinking off.

**Next**
- Find out what made the owner's tree dirty during the runs, and record it.
- **M3**, in plan mode: notes, expected values and the generate runner, with field outcomes and
  the hallucination rate per mode.

## M1: Corpus and deterministic comply suite (2026-11-26)

**Built**
- **Corpus.** 4 document types in 7 type/language pairs:
  - service agreement (EN, DE)
  - NDA (EN, DE)
  - invoice (EN, DE)
  - meeting minutes (EN)

  That is 91 documents and 238 comply cases, 56 of them clean controls (24%). There are 17
  mutators, each with a test that checks it changes its target and nothing else. Builds are
  deterministic: corpus hash `d2f7d14ee960`, recorded in `corpus/manifest.json`. The invented
  company names were web-checked (`corpus/NAMES.md`).
- **Sandbox** (`harness.py`). Holds against a hostile `.env`, which has a subprocess test of its
  own.
- **Comply runner.** Freezes one no-AI template per type. Then, for every case: DocForge's real
  `check_document`, and for fixable cases `fix_document` plus a re-check.
- **Metrics.** Pure functions, tested on hand-worked cases.
- **Output.** A console table, and a result file with git SHA, DocForge version and corpus hash.
- **First result.** `results/2026-11-26_no-ai_comply.json` (commit `70880b6`, tree clean): 238
  cases in 36.8 s, 0 errors. 359 eval tests pass, so the M1 "done" criterion is met.

**Learned** (no AI, this corpus; all numbers from the result file above)
- **The templates came out as designed.** DocForge's no-AI analyzer classified every element of
  all 7 templates as intended (boilerplate FIXED, fields dynamic, tables repeating).
- **Structural deviations are caught every time, as the right kind.** Deleted clauses 12/12,
  deleted tables 10/10, emptied required fields 14/14, invalid typed values ("TBD") 14/14. Each
  is reported as the expected kind whenever found (56/56). None of the 56 clean documents raised
  an alarm.
- **Small edits inside boilerplate are missed (H1 confirmed).**
  - Liability cap 0/4, notice period 0/8, payment terms 0/4.
  - Governing law 4/8: found only in the NDAs' shorter clause.
  - Boilerplate counts as changed only below 90% similarity. One changed number or place name in
    a long clause stays above that.
- **Removed table rows and columns are mostly not reported.**
  - A removed row: never (0/10, H3).
  - A removed column: only in the German fee table (2/10). Elsewhere the remaining header row
    stays at least 80% similar to the original (H4).
- **An inserted material clause never becomes a difference.** The test clause was "the Supplier
  accepts unlimited liability".
  - In 6/8 it shows only as extra content in the comparison view, and the score doesn't move
    (H6).
  - In 2/8 (English NDA), alignment paired the new paragraph with the original clause, and
    reported the original clause as changed.
- **Some benign changes still raise alarms: 24/80.**
  - Alarms: a heading in all caps (14/14, H2), reordered sections (8/8, H5), and the minutes'
    deleted distribution note (2/2).
  - No alarm: corrected typos, double spaces and curly quotes, date-format changes, and inserted
    notes (0/56).
- **The grade barely separates.** 100 of the 102 documents with a material deviation still grade
  "pass" (score ≥ 90), and 44 of them score exactly 100. Score AUC, clean vs. material: 0.78.
- **The fixer restores only what the check saw.**
  - 16/36 material boilerplate cases came back with the original text: all 12 deleted clauses
    and 4 of the 8 governing-law changes.
  - The other 20 were never seen, so they weren't touched. The re-check still called all 36
    clean.
  - Re-inserted clauses lose their heading style: style was restored in 4/36.
- **Every footer shows as "not in template".** In all 238 documents, the page-number footer is
  listed as extra content in the comparison. `check_compliance` skips automatic fields before it
  records what they matched, so the footer looks unmatched.
- **Speed.** `check_document` takes 66 ms at p50 and 117 ms at p95.

**Next**
- **M2**, in plan mode: the Haiku 5.5 and LM Studio configs, the response cache, the budget
  guard, the call observer, and the judge's confusion matrix. Note that the judge only sees
  reported differences, so the misses above are outside its reach.
- The hand-made set, once there are files (format in `corpus/handmade/README.md`).
- **Candidates for M6:**
  - the 90% threshold on long clauses
  - inserted clauses that never reach the score
  - grades that pass material deviations
  - re-inserted clauses without their style
  - footers listed as extra content

## M0: Recon and design (2026-11-26)

**Built**
- [`DESIGN.md`](DESIGN.md) covers:
  - how each runner calls DocForge
  - how ground truth maps to DocForge's node and field IDs
  - metric definitions
  - AI modes, the response cache and the budget guard
  - CI, hypotheses and open questions
- [`CLAUDE.md`](../CLAUDE.md) holds the working rules from brief §10, plus the owner's rule
  that the app and master are never changed.
- The brief is saved as [`docs/projects/eval-suite.md`](../docs/projects/eval-suite.md), with
  the employer's name removed.
- No code was written, and no file under `backend/` or `frontend/` changed.

**Learned**
- Every entry point in the brief exists. 14 details differ from the brief (DESIGN.md §1.2).
  These ones shape the suite:
  - **The AI judge never changes the compliance score or grade.** It adds a separate `semantic`
    dimension and drops its per-difference material/benign label, so the eval process records
    the labels itself.
  - **Some deviations may get past both the checker and the judge.** Inserted paragraphs never
    become differences. Changed boilerplate counts only below 90% similarity. Small edits inside
    long clauses and inserted clauses may therefore go unreported (hypotheses H1 and H6).
  - **There is no single fallback signal.** Some AI passes fail silently, so the eval observes
    the outcome of every AI call.
- **Master's own checks, on unchanged code.** `ruff check docforge` reports 6 findings with
  ruff 0.17.6. One backend test needs `DOCFORGE_AUTH_REQUIRED=false`, which comes from `.env`.
  With that setting: 422 passed, 1 xfailed. Neither is fixed, because the app is never changed.

**Accepted** on 2026-11-26. The owner approved DESIGN.md and decided:
- AI runs use only Claude Haiku 5.5. The brief's Sonnet and Gemini configs are out of scope, so
  the comparison is no AI vs. Haiku 5.5 vs. a local model.
- Local runs use LM Studio.
- From here on, commits are authored by the owner's GitHub account, with Claude as co-author.
  The two earlier M0 commits keep Claude as author. Changing them would need a force push, which
  is the owner's call.

**Next**
- M1, in plan mode: the harness, the corpus (4 types, 3 of them in German), at least 10
  mutators, the manifest, and the comply runner with `no-ai.yaml`.
