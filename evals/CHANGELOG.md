# Evals changelog

One entry per milestone: what was built, what was learned, what comes next.

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
