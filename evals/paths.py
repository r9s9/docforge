"""Where the eval suite keeps its files."""

from __future__ import annotations

from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
CORPUS_DIR = EVALS_DIR / "corpus"
BUILD_DIR = CORPUS_DIR / "build"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"
CONFIGS_DIR = EVALS_DIR / "configs"
RESULTS_DIR = EVALS_DIR / "results"
CACHE_DIR = EVALS_DIR / "cache"
THRESHOLDS_PATH = EVALS_DIR / "thresholds.yaml"
RESULTS_PAGE_PATH = EVALS_DIR / "RESULTS.md"
README_PATH = REPO_ROOT / "README.md"
