"""Mutual non-disclosure agreement, in English and German.

Party A is the same company in every NDA (its own template); the effective date, Party B and
the purpose change per document. There is no table.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from evals.corpus.model import Clause, DocTypeSpec, Field, FixedLine, Heading, Title
from evals.corpus.values import (
    COMPANIES_DE,
    COMPANIES_EN,
    OWN_COMPANY_DE,
    OWN_COMPANY_EN,
    fmt_date,
    pick,
    spaced_date,
)

PURPOSES = {
    "en": (
        "Evaluation of a joint offer for a fleet telematics project",
        "Assessment of a possible integration between the parties' booking systems",
        "Preparation of a pilot for automated invoice processing",
        "Due diligence for a planned software licence agreement",
        "Review of a data migration concept for a regional retailer",
        "Discussion of a shared research project on predictive maintenance",
        "Evaluation of a reseller partnership for the DACH region",
        "Scoping of a managed security service",
    ),
    "de": (
        "Prüfung eines gemeinsamen Angebots für ein Telematikprojekt",
        "Bewertung einer möglichen Anbindung der Buchungssysteme beider Parteien",
        "Vorbereitung eines Piloten zur automatisierten Rechnungsverarbeitung",
        "Due Diligence für einen geplanten Softwarelizenzvertrag",
        "Prüfung eines Migrationskonzepts für einen regionalen Händler",
        "Abstimmung eines gemeinsamen Forschungsprojekts zur vorausschauenden Wartung",
        "Bewertung einer Vertriebspartnerschaft für die DACH-Region",
        "Abgrenzung eines Managed-Security-Service",
    ),
}


def _values(pair: str, lang: str):
    companies = COMPANIES_DE if lang == "de" else COMPANIES_EN

    def values(index: int) -> dict[str, Any]:
        return {
            "effective_date": fmt_date(spaced_date(pair, "date", index, date(2026, 2, 2)), lang),
            "party_b": pick(companies, pair, "party_b", index),
            "purpose": pick(PURPOSES[lang], pair, "purpose", index),
        }

    return values


def _spec_en() -> DocTypeSpec:
    pair = "nda_en"
    return DocTypeSpec(
        pair=pair,
        doc_type="nda",
        lang="en",
        blocks=(
            Title("title", "MUTUAL NON-DISCLOSURE AGREEMENT"),
            Field("field.effective_date", "Effective Date", "effective_date", "date"),
            FixedLine("line.party_a", "Party A", OWN_COMPANY_EN),
            Field("field.party_b", "Party B", "party_b", "text"),
            Field("field.purpose", "Purpose", "purpose", "text"),
            Heading("heading.definition", "1. Confidential Information"),
            Clause(
                "clause.definition",
                "Confidential Information means all technical, commercial and financial "
                "information that one party discloses to the other in any form and that is "
                "marked as confidential or would reasonably be understood to be confidential.",
            ),
            Heading("heading.obligations", "2. Obligations"),
            Clause(
                "clause.obligations",
                "The recieving party shall keep the Confidential Information secret, protect it "
                "with at least the care it applies to its own confidential information, and use "
                "it only for the Purpose.",
            ),
            Heading("heading.exclusions", "3. Exclusions"),
            Clause(
                "clause.exclusions",
                "These obligations do not apply to information that is public, that the "
                "receiving party already lawfully knew, or that it must disclose by law.",
            ),
            Heading("heading.term", "4. Term"),
            Clause(
                "clause.term",
                "This Agreement remains in force for two (2) years from the Effective Date. The "
                "obligations in clause 2 survive for a further three (3) years.",
            ),
            Heading("heading.governing_law", "5. Governing Law"),
            Clause(
                "clause.governing_law",
                "This Agreement is governed by the laws of England and Wales, and the courts of "
                "London have exclusive jurisdiction.",
            ),
            Heading("heading.signatures", "6. Signatures"),
            Clause(
                "clause.signatures",
                "Signed by the authorised representatives of both parties.",
                material=False,
            ),
        ),
        footer="Confidential — Page ",
        values=_values(pair, "en"),
        mutations={
            "change_governing_law": {
                "target": "clause.governing_law",
                "replace": [
                    ["laws of England and Wales", "laws of Ireland"],
                    ["courts of London", "courts of Dublin"],
                ],
            },
            "change_notice_period": {
                "target": "clause.term",
                "replace": [["two (2) years", "six (6) months"]],
            },
            "delete_clause": {"targets": ["heading.obligations", "clause.obligations"]},
            "fix_typo": {"target": "clause.obligations", "replace": [["recieving", "receiving"]]},
            "whitespace_quotes": {
                "target": "clause.exclusions",
                "replace": [["public, that", "public,  that"], ["knew, or", "knew,  or"]],
            },
            "heading_caps": {"target": "heading.obligations"},
            "empty_field": {"target": "field.party_b"},
            "date_format": {"target": "field.effective_date"},
            "invalid_value": {"target": "field.effective_date", "value": "TBD"},
            "reorder_sections": {
                "first": ["heading.exclusions", "clause.exclusions"],
                "second": ["heading.term", "clause.term"],
            },
            "insert_benign": {
                "after": "clause.exclusions",
                "text": "Note: Either party may ask for a signed copy of this Agreement.",
            },
            "insert_material": {
                "after": "clause.obligations",
                "text": "The receiving party may share Confidential Information with its "
                "subcontractors without notice.",
            },
        },
    )


def _spec_de() -> DocTypeSpec:
    pair = "nda_de"
    return DocTypeSpec(
        pair=pair,
        doc_type="nda",
        lang="de",
        blocks=(
            Title("title", "GEHEIMHALTUNGSVEREINBARUNG"),
            Field("field.effective_date", "Datum des Inkrafttretens", "effective_date", "date"),
            FixedLine("line.party_a", "Partei A", OWN_COMPANY_DE),
            Field("field.party_b", "Partei B", "party_b", "text"),
            Field("field.purpose", "Zweck", "purpose", "text"),
            Heading("heading.definition", "§ 1 Vertrauliche Informationen"),
            Clause(
                "clause.definition",
                "Vertrauliche Informationen sind alle technischen, kaufmännischen und "
                "finanziellen Informationen, die eine Partei der anderen in beliebiger Form "
                "offenlegt und die als vertraulich gekennzeichnet oder erkennbar vertraulich "
                "sind.",
            ),
            Heading("heading.obligations", "§ 2 Pflichten"),
            Clause(
                "clause.obligations",
                "Die empfangende Partei hält die vertraulichen Informationen geheim, schützt sie "
                "mindestens mit der Sorgfallt, die sie für eigene vertrauliche Informationen "
                "anwendet, und verwendet sie nur für den Zweck.",
            ),
            Heading("heading.exclusions", "§ 3 Ausnahmen"),
            Clause(
                "clause.exclusions",
                "Diese Pflichten gelten nicht für Informationen, die öffentlich bekannt sind, die "
                "der empfangenden Partei bereits rechtmäßig bekannt waren oder die sie aufgrund "
                "gesetzlicher Pflichten offenlegen muss.",
            ),
            Heading("heading.term", "§ 4 Laufzeit"),
            Clause(
                "clause.term",
                "Diese Vereinbarung gilt für zwei Jahre ab dem Datum des Inkrafttretens. Die "
                "Pflichten aus § 2 gelten weitere drei Jahre fort.",
            ),
            Heading("heading.governing_law", "§ 5 Anwendbares Recht und Gerichtsstand"),
            Clause(
                "clause.governing_law",
                "Es gilt deutsches Recht. Ausschließlicher Gerichtsstand ist Frankfurt am Main.",
            ),
            Heading("heading.signatures", "§ 6 Unterschriften"),
            Clause(
                "clause.signatures",
                "Unterzeichnet von den vertretungsberechtigten Personen beider Parteien.",
                material=False,
            ),
        ),
        footer="Vertraulich — Seite ",
        values=_values(pair, "de"),
        mutations={
            "change_governing_law": {
                "target": "clause.governing_law",
                "replace": [["Gerichtsstand ist Frankfurt am Main", "Gerichtsstand ist Berlin"]],
            },
            "change_notice_period": {
                "target": "clause.term",
                "replace": [["zwei Jahre", "sechs Monate"]],
            },
            "delete_clause": {"targets": ["heading.obligations", "clause.obligations"]},
            "fix_typo": {"target": "clause.obligations", "replace": [["Sorgfallt", "Sorgfalt"]]},
            "whitespace_quotes": {
                "target": "clause.exclusions",
                "replace": [["bekannt sind, die", "bekannt sind,  die"], ["oder die", "oder  die"]],
            },
            "heading_caps": {"target": "heading.obligations"},
            "empty_field": {"target": "field.party_b"},
            "date_format": {"target": "field.effective_date"},
            "invalid_value": {"target": "field.effective_date", "value": "offen"},
            "reorder_sections": {
                "first": ["heading.exclusions", "clause.exclusions"],
                "second": ["heading.term", "clause.term"],
            },
            "insert_benign": {
                "after": "clause.exclusions",
                "text": "Hinweis: Jede Partei erhält auf Wunsch eine unterschriebene Ausfertigung.",
            },
            "insert_material": {
                "after": "clause.obligations",
                "text": "Die empfangende Partei darf vertrauliche Informationen ohne Mitteilung an "
                "Subunternehmer weitergeben.",
            },
        },
    )


SPECS = (_spec_en(), _spec_de())
