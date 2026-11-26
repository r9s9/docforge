"""Invented names, value pools and formatting for the corpus.

Everything here is deterministic: no clock, and randomness only through ``seeded()``, whose
string seeds Python hashes with SHA-512, so values are the same on every run and machine.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from datetime import date, timedelta
from typing import TypeVar

T = TypeVar("T")

# Invented companies. Each name was checked with a web search before use; see NAMES.md.
OWN_COMPANY_EN = "Tellmoor Data Services Ltd"
OWN_COMPANY_DE = "Brisenthal Softwarehaus GmbH"
COMPANIES_EN = (
    "Quorvane Logistics Ltd",
    "Pellbrook Marine Supplies Ltd",
    "Ostrevik Engineering Ltd",
    "Calvenna Health Partners Ltd",
    "Merrowind Retail Group Ltd",
    "Thistlecombe Energy Ltd",
    "Varnholt Publishing Ltd",
    "Glenmarrow Facilities Ltd",
)
COMPANIES_DE = (
    "Kesselwind Logistik GmbH",
    "Auerbrunn Maschinenbau AG",
    "Finkenstedt Medizintechnik GmbH",
    "Hallerquell Getränke GmbH",
    "Moorwiese Energie GmbH",
    "Strelitzer Datenwerk GmbH",
    "Lindenhaag Bau GmbH",
    "Zeisigtal Handelsgesellschaft mbH",
)
# Invented people: common first names paired with less common surnames.
PEOPLE = (
    "Anika Brandauer",
    "Jonas Kessling",
    "Mira Ostwald",
    "Tobias Varga",
    "Lena Lindqvist",
    "Farid Morandi",
    "Sophie Okafor",
    "Matteo Sandner",
    "Elif Whitcombe",
    "Noah Petrovic",
    "Clara Haverkamp",
    "Daniel Ferreira",
    "Ines Tamura",
    "Lukas Novak",
    "Hannah Achterberg",
    "Samuel Rinaldi",
)

MONTHS_EN = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def fmt_date(d: date, lang: str) -> str:
    """``14 March 2026`` in English, ``14.03.2026`` in German."""
    if lang == "de":
        return f"{d.day:02d}.{d.month:02d}.{d.year}"
    return f"{d.day} {MONTHS_EN[d.month - 1]} {d.year}"


def parse_date(text: str, lang: str) -> date:
    """Inverse of ``fmt_date``. Raises ValueError for anything else."""
    text = text.strip()
    if lang == "de":
        day, month, year = text.split(".")
        return date(int(year), int(month), int(day))
    day, month_name, year = text.split()
    return date(int(year), MONTHS_EN.index(month_name) + 1, int(day))


def fmt_money(cents: int, lang: str) -> str:
    """``€12,500.00`` in English, ``12.500,00 €`` in German."""
    units, rest = divmod(cents, 100)
    if lang == "de":
        return f"{units:,}".replace(",", ".") + f",{rest:02d} €"
    return f"€{units:,}.{rest:02d}"


def seeded(pair: str, key: str, index: int) -> random.Random:
    """A random generator that depends only on its arguments."""
    return random.Random(f"{pair}:{key}:{index}")


def pick(pool: Sequence[T], pair: str, key: str, index: int) -> T:
    """An item of ``pool`` for document ``index``; distinct for any ``len(pool)`` indices in a row.

    The pool is shuffled once per (pair, key) by hashing, so different fields of the same
    document don't move in lockstep.
    """
    order = sorted(
        range(len(pool)),
        key=lambda i: hashlib.sha256(f"{pair}:{key}:{i}".encode()).hexdigest(),
    )
    return pool[order[index % len(pool)]]


def spaced_date(pair: str, key: str, index: int, start: date, stride: int = 9) -> date:
    """A date that grows with ``index``: consecutive documents are at least 3 days apart."""
    jitter = seeded(pair, key, index).randint(0, stride - 3)
    return start + timedelta(days=index * stride + jitter)
