# CLAUDE.md

This branch holds the DocForge evaluation suite. The project brief is
[`docs/projects/eval-suite.md`](docs/projects/eval-suite.md) and the design is
[`evals/DESIGN.md`](evals/DESIGN.md).

## Working rules for Claude Code

- Never change the app or the master branch. Nothing under `backend/` or `frontend/` is edited, and master stays as it is. All eval work happens on the `evals` branch, and the evals look at the app from outside: they call the real service functions, and any wrapping happens in memory in the eval process. This rule comes first: it replaces "ask before you change anything under `backend/docforge/`" below.
- Start every milestone in **plan mode**. Show the plan and wait for approval before writing code.
- Work on the `evals` branch. Make small commits with clear messages, one logical change each.
- Before each commit, run `cd backend && pytest -q` and `ruff check docforge`. Also run the eval tests under `tests/evals/`.
- Python 3.11, ruff line length 100, type hints on public functions.
- Metrics are code: test each metric function on tiny cases calculated by hand.
- Ask before you: add a dependency, change anything under `backend/docforge/`, spend more than the budget cap, or delete files.
- After each milestone, update `evals/README.md` and `evals/CHANGELOG.md`.
- If the code doesn't match this brief (a function moved or a signature changed), follow the code, note the difference in `DESIGN.md`, and tell me.
