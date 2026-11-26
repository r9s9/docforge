# Evals changelog

One entry per milestone: what was built, what was learned, what comes next.

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
