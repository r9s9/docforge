# DocForge evals

This suite measures how well DocForge's pipelines work, from the outside. It calls the app's real
service functions in an isolated sandbox and never changes the app's code.

**Status:** M1 done (2026-11-26). The **comply** suite runs with AI off. AI modes (Claude
Haiku 5.5, a local model in LM Studio) arrive in M2; generate and analyze in M3 and M4.

- Design: [DESIGN.md](DESIGN.md)
- What each milestone built and learned: [CHANGELOG.md](CHANGELOG.md)
- Project brief: [docs/projects/eval-suite.md](../docs/projects/eval-suite.md)

## Run it

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
- **`run`** prints a table and writes `evals/results/<date>_no-ai_comply.json`. The whole comply
  suite takes about 40 s. A missing build is created first. If the corpus code no longer matches
  the committed manifest, the run stops.
  - `--types invoice_en nda_de`: only some types.
  - `--limit 3`: at most 3 cases per type, for smoke runs.
  - `--out DIR`: write the result file somewhere else.
  - `--keep-sandbox`: keep DocForge's temp database and data dir for debugging.

The tests run from the repo root:

```bash
python -m pytest tests/evals -q
```

```bash
ruff check --config evals/ruff.toml evals tests/evals
```

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
| benign changes that alarm / clean controls that alarm | False alarms |
| score AUC | Chance that a clean document scores higher than one with a material deviation (0.5 = no separation, 1.0 = perfect) |
| fix success | Material boilerplate damage that `fix_document` fully repaired, judged against the clean original. The re-check alone can't see what the check missed. |

Every rate shows its counts, as in `0.61 (62/102)`.

## What a result file holds

Every result file records the git SHA (and whether the tree had uncommitted changes), DocForge's
version, the config, the corpus hash and every case's record. Any number can therefore be
traced and reproduced. Numbers are only ever written by a run, never by hand.

## Rules for this folder

- Nothing under `backend/` or `frontend/` is ever changed.
- All eval work stays on the `evals` branch.
- Every company and person in the corpus is invented ([corpus/NAMES.md](corpus/NAMES.md)).
- Hand-made test documents follow [corpus/handmade/README.md](corpus/handmade/README.md).
