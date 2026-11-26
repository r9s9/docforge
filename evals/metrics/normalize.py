"""Compare field values the way a reader would: dates, amounts, names and text in any form.

The generate suite (DESIGN.md §3.5, §5.2) checks the value DocForge wrote against the value the
notes give, and the two rarely match byte for byte. The notes say "April 8, 2026" and the German
template writes "08.04.2026"; the notes say "EUR 13,350.00" and the document "13.350,00 €".
These functions make each kind of value comparable, and find the dates and amounts a notes text
mentions. They are pure functions and never import DocForge.

Kinds of value:
- ``text``: case, punctuation and spacing don't matter, and neither does a trailing legal form
  ("Merrowind Retail Group" = "Merrowind Retail Group Ltd") or a hyphen inside a compound
  ("Software-Lizenz" = "Softwarelizenz").
- ``date``: any common English or German form, with or without a year-first ISO form.
- ``money``: any grouping and decimal convention, with or without the currency.
- ``number``: a quantity.
- ``person``: a name, with or without a title ("Dr.", "Frau").
- ``names``: a list of people, compared as a set.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

KINDS = ("text", "date", "money", "number", "person", "names")

MONTHS = {
    "january": 1, "jan": 1, "januar": 1, "jänner": 1,
    "february": 2, "feb": 2, "februar": 2,
    "march": 3, "mar": 3, "märz": 3, "maerz": 3, "mrz": 3,
    "april": 4, "apr": 4,
    "may": 5, "mai": 5,
    "june": 6, "jun": 6, "juni": 6,
    "july": 7, "jul": 7, "juli": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12, "dezember": 12, "dez": 12,
}
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_DATE_PATTERNS = (
    # 23.11.2026, 23. 11. 2026
    (re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b"), ("d", "m", "y")),
    # 2026-11-23
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), ("y", "m", "d")),
    # 23 November 2026, 23. November 2026, 23rd of Nov. 2026
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\.?\s+(?:of\s+)?({_MONTH})\.?,?\s+(\d{{4}})\b"),
     ("d", "M", "y")),
    # November 23, 2026; Nov 23rd 2026
    (re.compile(rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b"),
     ("M", "d", "y")),
)

_CURRENCY = r"(?:€|eur|euro|euros)"
_AMOUNT_NUMBER = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_AMOUNT = re.compile(
    rf"(?:{_CURRENCY}\s?({_AMOUNT_NUMBER})(?![\d.,]*\d)|"
    rf"\b({_AMOUNT_NUMBER})\s?{_CURRENCY}|"
    rf"(?<![\d.,])(\d{{1,3}}(?:[.,]\d{{3}})*[.,]\d{{2}})(?![.,]?\d))",
    re.IGNORECASE,
)

_TITLES = {"dr", "prof", "mr", "mrs", "ms", "miss", "herr", "frau", "ing", "dipl"}
_LEGAL_FORMS = ("ltd", "gmbh", "ag", "mbh", "plc", "inc", "llc", "kg", "se", "co")
_CANONICAL_WORDS = {"limited": "ltd", "incorporated": "inc", "aktiengesellschaft": "ag"}

# Values that stand in for a missing one rather than state anything: "TBD", "[Start Date]".
_PLACEHOLDER = re.compile(
    r"^\s*(?:"
    r"tbd|tbc|tba|n/?a|none|nil|unknown|pending|open|-+|—|–|\?+|x{2,}|"
    r"to be (?:confirmed|determined|decided|agreed|assigned|defined|announced|advised)"
    r"(?: \w+)*|"
    r"not (?:yet )?(?:known|specified|provided|given|stated|available|agreed|fixed)(?: \w+)*|"
    r"(?:noch )?offen|folgt|steht noch aus|wird nachgereicht|unbekannt|k\.? ?a\.?|"
    r"noch nicht (?:bekannt|festgelegt|vereinbart)|"
    r"\[[^\]]*\]|\{\{?[^}]*\}?\}|<[^>]*>|_{2,}"
    r")\s*[.!]?\s*$",
    re.IGNORECASE,
)


def _base(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return text.replace("’", "'").replace("‘", "'")


def norm_text(value: Any) -> str:
    """Lower case, punctuation as spaces, single spaces, a few legal words in short form."""
    words = re.sub(r"[^\w]+", " ", _base(value)).split()
    return " ".join(_CANONICAL_WORDS.get(word, word) for word in words)


def _without_legal_form(text: str) -> str:
    words = text.split()
    while len(words) > 1 and words[-1] in _LEGAL_FORMS:
        words.pop()
    return " ".join(words)


# A hyphen between two letters or digits: ASCII, Unicode hyphen (NFKC turns the non-breaking
# hyphen into it). A dash with spaces around it ("Hamburg – Berlin") is punctuation instead.
_COMPOUND_HYPHEN = re.compile(r"(?<=\w)[-‐](?=\w)")


def _joined(value: Any) -> str:
    """``norm_text`` with hyphenated compounds closed up: ``Software-Lizenz`` → ``softwarelizenz``.

    German writes the same compound with or without its hyphen, so a comparison tries both:
    ``norm_text`` makes "on-site" equal "on site", this makes "Software-Lizenz" equal
    "Softwarelizenz".
    """
    return norm_text(_COMPOUND_HYPHEN.sub("", _base(value)))


def _same_text(actual: Any, expected: Any) -> bool:
    for a, b in ((norm_text(actual), norm_text(expected)), (_joined(actual), _joined(expected))):
        if a == b or _without_legal_form(a) == _without_legal_form(b):
            return True
    return False


def is_empty(value: Any) -> bool:
    """No value at all: ``None``, an empty or blank string, or an empty list."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return not value
    return False


def is_placeholder(value: Any) -> bool:
    """A value that stands in for a missing one ("TBD", "to be confirmed", "[Start Date]").

    A note in brackets after it doesn't change that: "TBD (legal will confirm)".
    """
    if not isinstance(value, str):
        return False
    text = re.sub(r"\s*\([^)]*\)\s*$", "", unicodedata.normalize("NFKC", value))
    return bool(_PLACEHOLDER.match(text))


def find_dates(text: Any) -> list[date]:
    """Every date written in ``text``, in order of appearance (English and German forms)."""
    found: list[tuple[int, date]] = []
    lowered = _base(text)
    for pattern, order in _DATE_PATTERNS:
        for match in pattern.finditer(lowered):
            parts = dict(zip(order, match.groups(), strict=True))
            try:
                month = MONTHS[parts["M"]] if "M" in parts else int(parts["m"])
                found.append((match.start(), date(int(parts["y"]), month, int(parts["d"]))))
            except (KeyError, ValueError):
                continue
    return [d for _start, d in sorted(found, key=lambda item: item[0])]


def parse_date(value: Any) -> date | None:
    """The one date a value holds, or None if it holds none or several different ones."""
    dates = set(find_dates(value))
    return dates.pop() if len(dates) == 1 else None


def _cents(number: str) -> int | None:
    """``1.234,56`` / ``1,234.56`` / ``1234.5`` / ``1.200`` as cents."""
    s = number.strip()
    if "," in s and "." in s:
        decimal = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s:
        decimal = "," if re.search(r",\d{1,2}$", s) else None
    elif "." in s:
        decimal = "." if re.search(r"\.\d{1,2}$", s) else None
    else:
        decimal = None
    whole, fraction = s.rsplit(decimal, 1) if decimal else (s, "")
    whole = re.sub(r"[.,]", "", whole)
    if not whole.isdigit():
        return None
    return int(whole) * 100 + int((fraction + "00")[:2])


def find_amounts(text: Any) -> list[int]:
    """Every money amount in ``text``, as cents: with a currency, or written with two decimals."""
    amounts = []
    for match in _AMOUNT.finditer(_base(text)):
        number = next(group for group in match.groups() if group)
        cents = _cents(number)
        if cents is not None:
            amounts.append(cents)
    return amounts


def parse_money(value: Any) -> int | None:
    """The one amount a value holds, as cents; a bare number counts as an amount too."""
    amounts = set(find_amounts(value))
    if len(amounts) == 1:
        return amounts.pop()
    if not amounts:
        bare = re.fullmatch(rf"\s*({_AMOUNT_NUMBER})\s*", _base(value))
        return _cents(bare.group(1)) if bare else None
    return None


def parse_number(value: Any) -> float | None:
    """A quantity such as ``3``, ``2,5`` or ``12.0``, also with one unit word (``11 Stunden``)."""
    match = re.fullmatch(r"\s*(\d+)(?:[.,](\d+))?(?:\s*[^\W\d_]+\.?)?\s*", _base(value))
    if not match:
        return None
    return float(f"{match.group(1)}.{match.group(2) or 0}")


def norm_name(value: Any) -> str:
    """A person's name without titles: ``Dr. Lena Hoffmann`` → ``lena hoffmann``."""
    return " ".join(word for word in norm_text(value).split() if word not in _TITLES)


def split_names(value: Any) -> set[str]:
    """The people in a list such as ``A, B and C`` or ``A; B und C``.

    A note in brackets is a role, not part of the name: ``Anika Brandauer (chair)``.
    """
    text = re.sub(r"\([^)]*\)", " ", _base(value))
    parts = re.split(r",|;|\n|&|\band\b|\bund\b|\bsowie\b", text)
    return {name for part in parts if (name := norm_name(part))}


def same(kind: str, actual: Any, expected: Any) -> bool:
    """Whether a written value equals the expected one, for a kind of value."""
    if is_empty(actual) or is_empty(expected):
        return False
    if kind == "date":
        written = parse_date(actual)
        return written is not None and written == parse_date(expected)
    if kind == "money":
        written = parse_money(actual)
        return written is not None and written == parse_money(expected)
    if kind == "number":
        written = parse_number(actual)
        return written is not None and written == parse_number(expected)
    if kind == "person":
        return norm_name(actual) == norm_name(expected)
    if kind == "names":
        return split_names(actual) == split_names(expected)
    return _same_text(actual, expected)


def same_cell(kind: str, actual: Any, expected: Any) -> bool:
    """Like ``same``, but a text cell may also contain, or be contained in, the expected text.

    Table cells are short labels ("Training" for "Training workshop"), and a document that
    writes either one has the right row.
    """
    if same(kind, actual, expected):
        return True
    if kind != "text" or is_empty(actual) or is_empty(expected):
        return False
    for a, b in ((norm_text(actual), norm_text(expected)), (_joined(actual), _joined(expected))):
        if len(min(a, b, key=len)) >= 3 and (a in b or b in a):
            return True
    return False


def appears_in(kind: str, value: Any, notes: str) -> bool:
    """Whether the notes support a value: as text, or as an equal date or amount.

    Text appears in one piece; a value of four or more words may also be put together from
    words that are all in the notes.
    """
    if is_empty(value):
        return False
    if kind == "date":
        written = parse_date(value)
        return written is not None and written in find_dates(notes)
    if kind == "money":
        written = parse_money(value)
        return written is not None and written in find_amounts(notes)
    if kind == "names":
        names = split_names(value)
        haystack = f" {norm_text(notes)} "
        return bool(names) and all(f" {name} " in haystack for name in names)
    text = norm_name(value) if kind == "person" else norm_text(value)
    if not text:
        return False
    haystack = f" {norm_text(notes)} "
    if f" {text} " in haystack or (kind == "text" and f" {_without_legal_form(text)} " in haystack):
        return True
    if kind == "text" and f" {_joined(value)} " in f" {_joined(notes)} ":
        return True
    # A longer value put together from several places in the notes (lines a router joined)
    # states nothing new. A short one, such as an ID, must appear in one piece.
    words = text.split()
    return len(words) >= 4 and set(words) <= set(haystack.split())


def appears_in_cell(kind: str, value: Any, notes: str) -> bool:
    """``appears_in`` for a table cell, where a text label may sit inside a longer word.

    "Schulung" is in notes that say "Schulungen", and "Security review" in "security reviews".
    """
    if kind != "text":
        return appears_in(kind, value, notes)
    text, joined = norm_text(value), _joined(value)
    return len(text) >= 3 and (text in norm_text(notes) or joined in _joined(notes))
