# DocForge evals

**Status:** design stage (M0). Nothing runs yet.

- Design: [DESIGN.md](DESIGN.md)
- What changed in each milestone: [CHANGELOG.md](CHANGELOG.md)
- Project brief: [docs/projects/eval-suite.md](../docs/projects/eval-suite.md)

**What the suite will measure**
- DocForge's three pipelines: analyze (build a template), generate (fill it from notes) and
  comply (check a returned document).
- Each pipeline with no AI, with Claude Haiku 5.5, with Claude Sonnet 5.5 and with a local model.
- Cost, latency and fallback rate for every mode.

How to run the suite will be written here in M1, when the first suite (comply, with no AI)
exists.

The evals never change the app. They call its real services from outside, on the `evals` branch.
