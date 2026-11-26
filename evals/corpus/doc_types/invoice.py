"""Invoice, in English and German.

The issuer and bank line are the same on every invoice; the number, dates, customer, VAT ID,
line items and totals change. Amounts are computed, so line items, subtotal, VAT and total
always add up, and the due date follows the payment terms (30 days in English, 14 in German).
Bank details are obviously fake.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from evals.corpus.model import (
    Clause,
    DocTypeSpec,
    Field,
    FixedLine,
    Heading,
    TableBlock,
    Title,
)
from evals.corpus.values import (
    COMPANIES_DE,
    COMPANIES_EN,
    OWN_COMPANY_DE,
    OWN_COMPANY_EN,
    fmt_date,
    fmt_money,
    pick,
    seeded,
    spaced_date,
)

ITEMS = {
    "en": (
        ("Consulting services", 15_000),
        ("Onsite support", 40_000),
        ("Software licence", 22_000),
        ("Implementation", 16_000),
        ("Training workshop", 90_000),
        ("Data export", 35_000),
        ("Cloud hosting (monthly)", 48_000),
        ("Security review", 120_000),
    ),
    "de": (
        ("Beratungsleistungen", 15_000),
        ("Vor-Ort-Support", 40_000),
        ("Softwarelizenz", 22_000),
        ("Implementierung", 16_000),
        ("Schulungsworkshop", 90_000),
        ("Datenexport", 35_000),
        ("Cloud-Hosting (monatlich)", 48_000),
        ("Sicherheitsprüfung", 120_000),
    ),
}
VAT_PERCENT = {"en": 20, "de": 19}
PAYMENT_DAYS = {"en": 30, "de": 14}


def _values(pair: str, lang: str):
    companies = COMPANIES_DE if lang == "de" else COMPANIES_EN
    prefix = "RE" if lang == "de" else "INV"
    country = "DE" if lang == "de" else "GB"

    def values(index: int) -> dict[str, Any]:
        issued = spaced_date(pair, "date", index, date(2026, 2, 2))
        rng = seeded(pair, "items", index)
        rows, subtotal = [], 0
        for name, unit in rng.sample(ITEMS[lang], 2 + index % 4):
            qty = rng.randint(1, 12)
            subtotal += qty * unit
            rows.append([name, str(qty), fmt_money(unit, lang), fmt_money(qty * unit, lang)])
        vat = (subtotal * VAT_PERCENT[lang] + 50) // 100
        number = 140 + index * 3 + seeded(pair, "number", index).randint(0, 2)
        return {
            "invoice_no": f"{prefix}-2026-{number:04d}",
            "invoice_date": fmt_date(issued, lang),
            "due_date": fmt_date(issued + timedelta(days=PAYMENT_DAYS[lang]), lang),
            "customer": pick(companies, pair, "customer", index),
            "vat_id": f"{country}0000001{index:02d}",
            "items": rows,
            "subtotal": fmt_money(subtotal, lang),
            "vat": fmt_money(vat, lang),
            "total": fmt_money(subtotal + vat, lang),
        }

    return values


def _spec_en() -> DocTypeSpec:
    pair = "invoice_en"
    return DocTypeSpec(
        pair=pair,
        doc_type="invoice",
        lang="en",
        blocks=(
            Title("title", "INVOICE"),
            FixedLine("line.issuer", "From", OWN_COMPANY_EN),
            Field("field.invoice_no", "Invoice Number", "invoice_no", "text"),
            Field("field.invoice_date", "Invoice Date", "invoice_date", "date"),
            Field("field.due_date", "Due Date", "due_date", "date"),
            Field("field.customer", "Customer", "customer", "text"),
            Field("field.vat_id", "Customer VAT ID", "vat_id", "text"),
            Heading("heading.items", "Line Items"),
            TableBlock("table.items", ("Description", "Qty", "Unit Price", "Amount"), "items"),
            Field("field.subtotal", "Subtotal", "subtotal", "money"),
            Field("field.vat", "VAT (20%)", "vat", "money"),
            Field("field.total", "Total Due", "total", "money"),
            Heading("heading.payment", "Payment Terms"),
            Clause(
                "clause.payment",
                "Payment is due within 30 days of the invoice date. Please quote the invoice "
                "number with your payment. Late payments may incur interest at the statuatory "
                "rate.",
            ),
            FixedLine(
                "line.bank", "Bank Details", "IBAN GB00 TELL 0000 0000 0000 00, BIC TELLGB00"
            ),
            Clause("clause.thanks", "Thank you for your business.", material=False),
        ),
        footer=f"{OWN_COMPANY_EN} — Page ",
        values=_values(pair, "en"),
        mutations={
            "change_payment_terms": {
                "target": "clause.payment",
                "replace": [["within 30 days", "within 90 days"]],
            },
            "delete_clause": {"targets": ["heading.payment", "clause.payment"]},
            "fix_typo": {"target": "clause.payment", "replace": [["statuatory", "statutory"]]},
            "whitespace_quotes": {
                "target": "clause.payment",
                "replace": [["date. Please", "date.  Please"], ["your payment", "your  payment"]],
            },
            "heading_caps": {"target": "heading.payment"},
            "empty_field": {"target": "field.customer"},
            "date_format": {"target": "field.invoice_date"},
            "invalid_value": {"target": "field.due_date", "value": "TBD"},
            "remove_row": {"target": "table.items"},
            "remove_column": {"target": "table.items", "column": 2},
            "delete_table": {"target": "table.items"},
            "insert_benign": {
                "after": "clause.thanks",
                "text": "Note: Please tell us if your billing address changes.",
            },
        },
    )


def _spec_de() -> DocTypeSpec:
    pair = "invoice_de"
    return DocTypeSpec(
        pair=pair,
        doc_type="invoice",
        lang="de",
        blocks=(
            Title("title", "RECHNUNG"),
            FixedLine("line.issuer", "Rechnungssteller", OWN_COMPANY_DE),
            Field("field.invoice_no", "Rechnungsnummer", "invoice_no", "text"),
            Field("field.invoice_date", "Rechnungsdatum", "invoice_date", "date"),
            Field("field.due_date", "Fällig am", "due_date", "date"),
            Field("field.customer", "Kunde", "customer", "text"),
            Field("field.vat_id", "USt-IdNr. des Kunden", "vat_id", "text"),
            Heading("heading.items", "Positionen"),
            TableBlock("table.items", ("Beschreibung", "Menge", "Einzelpreis", "Betrag"), "items"),
            Field("field.subtotal", "Nettobetrag", "subtotal", "money"),
            Field("field.vat", "USt. 19 %", "vat", "money"),
            Field("field.total", "Gesamtbetrag", "total", "money"),
            Heading("heading.payment", "Zahlungsbedingungen"),
            Clause(
                "clause.payment",
                "Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum ohne Abzug. Bitte geben Sie "
                "bei der Zahlung die Rechnungsnummer an. Bei Zahlungsverzug berechnen wir "
                "Verzugzinsen in gesetzlicher Höhe.",
            ),
            FixedLine(
                "line.bank", "Bankverbindung", "IBAN DE00 0000 0000 0000 0000 00, BIC BRISDE00"
            ),
            Clause("clause.thanks", "Vielen Dank für Ihren Auftrag.", material=False),
        ),
        footer=f"{OWN_COMPANY_DE} — Seite ",
        values=_values(pair, "de"),
        mutations={
            "change_payment_terms": {
                "target": "clause.payment",
                "replace": [["innerhalb von 14 Tagen", "innerhalb von 60 Tagen"]],
            },
            "delete_clause": {"targets": ["heading.payment", "clause.payment"]},
            "fix_typo": {
                "target": "clause.payment",
                "replace": [["Verzugzinsen", "Verzugszinsen"]],
            },
            "whitespace_quotes": {
                "target": "clause.payment",
                "replace": [["Abzug. Bitte", "Abzug.  Bitte"], ["der Zahlung", "der  Zahlung"]],
            },
            "heading_caps": {"target": "heading.payment"},
            "empty_field": {"target": "field.customer"},
            "date_format": {"target": "field.invoice_date"},
            "invalid_value": {"target": "field.due_date", "value": "offen"},
            "remove_row": {"target": "table.items"},
            "remove_column": {"target": "table.items", "column": 2},
            "delete_table": {"target": "table.items"},
            "insert_benign": {
                "after": "clause.thanks",
                "text": "Hinweis: Bitte teilen Sie uns Änderungen Ihrer Rechnungsanschrift mit.",
            },
        },
    )


SPECS = (_spec_en(), _spec_de())
