# Evals changelog

One entry per milestone: what was built, what was learned, what comes next.

## M3: Generate suite (2026-11-26)

**Built**
- **35 notes cases** (`corpus/notes/`), one per style for each of the 7 type/language pairs:
  bullet points, an email, German and English mixed, missing information, and notes that correct
  one of their own values. Written by hand from held-out documents' values; a test checks every
  expected value against its source document and the notes.
- **Scoring** (`metrics/generate.py`, `metrics/normalize.py`): every short field is correct,
  correctly empty, omitted, from the notes but wrong, or unsupported (a hallucination), flagged
  or silent; plus tables, date and amount forms, layout, and free text.
- **The generate runner** on DocForge's real `generate_document`, `run --suite generate`, and
  `compare` for generate results.
- **The rubric grader** (Claude Haiku 5.5) for free text, and the agreement check behind it.
- **`rescore`**: recomputes outcomes from the values a run recorded, for when a comparison rule
  is fixed.
- **Results.** All three runs ran on the owner's PC (Windows, Python 3.13.17) at commit
  `d4d5f35`, DocForge 0.21.0, with the same notes (`078da46a`). The only uncommitted file was
  the Claude app's launch settings (`dirty_code: false`). No errors, no early stops.

  | Result | Time | Spent |
  |---|---|---|
  | `results/2026-11-26_no-ai_generate.json` | 22 s | grading $0.0012 |
  | `results/2026-11-26_haiku_generate.json` | 754 s | $0.1054 + grading $0.0064 |
  | `results/2026-11-26_local_generate.json` | 5,622 s | grading $0.0055 |

  After checking the outcomes, two comparison rules were fixed and the files rescored at
  `ec841d8`: a role in brackets ("Anika Brandauer (chair)") is not part of a name, and a quantity
  may carry a unit ("11 Stunden"). This changed two of Haiku's field outcomes and recomputed the
  table scores; the values, grades, layout checks, timings and costs are as recorded.
- **The grader passed its check.** The owner labelled 30 values blind on a labelling page
  (`graders/labels/`). The owner doesn't read German, so the 30 come only from English documents
  with English notes. The grader agrees with the owner on faithfulness for 27/30 and on
  completeness for 27/28, above the 85% gate, so its verdicts are used. In all four
  disagreements the grader said no where the owner said yes: three Haiku texts it called
  unfaithful, and the no-AI decision that stops mid-sentence (failure 5), which it called
  incomplete. Its agreement on German values is not measured.

**The M3 table** (`python -m evals compare`; every number comes from the three result files)

| metric | no AI | Haiku 5.5 | Qwen 3.6-27b (local) |
|---|---|---|---|
| short fields right | 0.24 (40/166) | 0.99 (165/166) | 0.98 (163/166) |
| left empty though the notes give it | 0.61 (101/166) | 0.00 (0/166) | 0.00 (0/166) |
| **short fields hallucinated** | **0.00 (0/69)** | **0.00 (0/166)** | **0.01 (2/166)** |
| of those, flagged as AI-drafted | — | — | 0/2 |
| from the notes, but wrong | 0.42 (29/69) | 0.01 (1/166) | 0.01 (1/166) |
| empty where the notes are silent | 0.56 (5/9) | 1.00 (9/9) | 1.00 (9/9) |
| a corrected value used | 0 | 0 | 0 |
| dates and amounts in the template's form | 0.91 (20/22) | 0.18 (17/93) | 0.17 (16/93) |
| table row count right | 0.00 (0/24) | 0.92 (22/24) | 1.00 (24/24) |
| table cells right | 0.00 (0/263) | 1.00 (263/263) | 0.99 (260/263) |
| **table cells unsupported** | — | **0.01 (3/272)** | **0.01 (3/263)** |
| free text written | 0.30 (9/30) | 0.97 (29/30) | 0.97 (29/30) |
| free text faithful (grader) | 1.00 (9/9) | 0.86 (25/29) | 1.00 (29/29) |
| free text complete (grader) | 0.78 (7/9) | 1.00 (28/28) | 1.00 (28/28) |
| layout kept | 1.00 (35/35) | 1.00 (35/35) | 0.97 (34/35) |
| review led to a rewrite | — | 0.09 (3/35) | 0.09 (3/35) |
| stable across repeats | — | 0.98 (46/47) | 1.00 (47/47) |
| cost per document | $0 | $0.0019 | $0 (hardware) |
| generate time p50 / p95 | 53 / 69 ms | 11.1 / 21.0 s | 94.5 / 170.0 s |

The hallucination rates count the values each mode wrote: without AI, 69 short fields had one.

Short fields right, by notes style:

| style | no AI | Haiku 5.5 | Qwen 3.6-27b |
|---|---|---|---|
| bullet points | 35/35 | 35/35 | 34/35 |
| email | 0/35 | 34/35 | 33/35 |
| mixed languages | 1/35 | 35/35 | 35/35 |
| missing information | 2/26 | 26/26 | 26/26 |
| correction | 2/35 | 35/35 | 35/35 |

**Learned** (this corpus; Haiku and Qwen as configured in M2)
- **Without AI, DocForge invents nothing but reads only bullet notes (H7 confirmed).** It filled
  every field of the bullet-point notes and almost nothing else: 101 of 166 given values were
  left empty, no table was filled, and there were no hallucinations. The 29 wrong values are
  note lines put in the wrong field.
- **With AI, the values are almost all right.** Both writers got 98–99% of the short fields
  right, read the email, mixed-language and correcting notes as well as the bullet ones, left
  every missing field empty instead of guessing, and never used a value the notes later
  corrected. The AI writer wrote all 35 documents in both modes; it never fell back.
- **Haiku is fast and cheap**: no hallucinated short field, $0.0019 a document, 11 s at the
  median. Qwen on the owner's PC took 94 s at the median.
- **On Haiku's free text, the grader is stricter than the owner.** The grader called four of
  Haiku's texts unfaithful, for details the notes don't state: extras "available on request", a
  reference to "section 2", and "DACH (Germany, Austria and Switzerland)". The owner labelled the
  three English ones and judged all three faithful. The fourth, German, counts as unfaithful only
  by the eval's rule that any listed claim makes a text unfaithful: the grader listed the
  abbreviation "IAM" and noted that it is not an unsupported fact.
- **The two modes' unsupported table cells are not alike.** Haiku's 3 are the descriptions of
  rows the notes don't support (failure 4). Qwen's 3 are rewordings of values in the notes:
  "Software-Lizenz" for "Softwarelizenz", "TB/Monat" for "pro TB und Monat", and
  "Änderungsanfragen" for the English notes' "change requests", where the eval accepts
  "Änderungsaufträge". The first is a gap in the eval's comparison: the hyphen splits the word.

**Five failures, written up**
1. **A skipped section deletes every clause after it** (Qwen, `service_agreement_de/missing`).
   The notes say the price list for extras is still open ("noch offen"), so Qwen left the fee
   table empty and listed the fees section as skipped. DocForge then removed everything from the
   fees heading to the end: term, liability, confidentiality, data protection, governing law and
   the signature block: 14 blocks, by the layout check. The cause is in the template: each section
   with fields is wrapped in an on/off switch, and the sections without fields after it fall
   inside the same switch. Rendering the template with only that section switched off
   reproduces it: 13 of its 21 paragraphs disappear. DocForge's validation checks only field
   values, and its read-back review raised one finding that it didn't count as correctable, so
   no rewrite followed. DocForge's code makes hiding a section an explicit decision because a
   vanished section is "the scarier failure — the document looks complete and silently isn't".
   Haiku filled the table instead (failure 4), so its contract kept every clause.
2. **AI-written dates and amounts lose the template's form** (Haiku 76 and Qwen 77 of 93).
   DocForge's writer prompt asks for ISO dates and normalised numbers, and its assembler prints
   values as they are. Haiku's English agreement (`service_agreement_en/bullets`) says
   "Date: 2026-03-02" and "Monthly Fee: 11950.0" where the template's documents write
   "2 March 2026" and "€11,950.00", and its German invoice (`invoice_de/email`) says
   "Rechnungsdatum: 2026-03-28" for "28.03.2026". The values are right; a reader would still have
   to fix every date and amount. Without AI, the form was kept 20/22.
3. **A misspelled company, not flagged** (Qwen, `service_agreement_de/bullets` and
   `invoice_de/email`). "Lindenhaag Bau GmbH" became "Lindh Haag Bau GmbH" and
   "Lindhaga Bau GmbH": the only hallucinated short fields in either AI mode (2 of 332), both in
   the customer field, and neither marked as drafted, so the app wouldn't show them for review.
4. **Haiku puts the monthly fee into the price list** (`service_agreement_en/email`,
   `service_agreement_de/correction`, `service_agreement_de/missing`). In these agreements the fee
   table lists the extras, such as a penetration test, and the monthly fee has a field of its
   own. Haiku filled the field and also added the monthly fee as the table's first row, under a
   description it wrote ("Archive hosting, nightly backup and six-monthly restore testing"), so
   the table has three rows where the notes give two. Where the notes say the price list is still
   open, it put the monthly fee in as the only row. These are Haiku's 3 unsupported table cells
   and its 2 wrong row counts.
5. **Without AI, an email lands in the agreement-number field** (`service_agreement_en/email`).
   The heuristic copies "Label: value" lines and joins the other lines into the remaining text
   fields, as a last resort into the first one, so the agreement number reads "Subject: Contract
   for Thistlecombe Energy Hi Jonas, we closed the deal with Thistlecombe Energy Ltd today …". A
   value that runs onto a second line is cut at the line break: the decision ends "…the
   remaining follow-ups go to", without "the backlog" (`minutes_en/bullets`).

Also seen: both AI writers listed the chair and the minute taker among the attendees, though the
template has a field for each ("from the notes, but wrong", once per mode).

**Next**
- **M4**, in plan mode: the analyze suite, with quality by number of examples (1, 2, 3, 5).
- A small eval fix to make first: compare a word with and without its hyphen as equal
  ("Software-Lizenz", "Softwarelizenz"), then rescore the generate results.

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

  Both files record `dirty: true`. The owner's `git status` showed the cause: a locally edited
  `.claude/launch.json` (the Claude app's launch settings for dev-server previews) and one
  untracked text file at the repo root. DocForge and the evals read neither, so both runs ran
  the committed code. Result files now say this themselves: they list the tracked files that
  differ and record whether any of them is run code (`dirty_code`).

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
