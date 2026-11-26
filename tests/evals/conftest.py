"""Shared setup for the eval tests.

Puts the repo root on ``sys.path`` so ``import evals`` works under plain ``pytest`` as well as
``python -m pytest``. This folder has no ``__init__.py`` on purpose: as a package it would be
named ``evals`` and could shadow the real one.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
