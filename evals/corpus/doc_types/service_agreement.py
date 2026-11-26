"""Vendor service agreement, in English and German.

The supplier is the same company in every agreement (it is the supplier's own template); the
customer, dates, fee, service description and fee schedule change per document. Each spec
plants one typo in a boilerplate clause, for the ``fix_typo`` mutator.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from evals.corpus.model import (
    Clause,
    DocTypeSpec,
    Field,
    FixedLine,
    FreeText,
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

SERVICES = {
    "en": (
        "Operation and monitoring of the Customer's warehouse management platform, including "
        "incident handling during business hours and a monthly service report.",
        "Second-level support for the Customer's field service app, covering bug analysis, "
        "hotfix releases and a quarterly review of open issues.",
        "Hosting and nightly backup of the Customer's document archive in an EU data centre, "
        "with restore tests every six months.",
        "Maintenance of the Customer's online shop integration with its payment and shipping "
        "providers, including updates for interface changes.",
        "Data quality checks on the Customer's product master data, delivered as a weekly "
        "report with correction proposals.",
        "Administration of the Customer's identity and access management service, including "
        "onboarding and offboarding of user accounts.",
        "Monitoring of the Customer's sensor data pipeline, with alerting outside business "
        "hours and a root-cause report for every outage.",
        "Quarterly security patching of the Customer's application servers, including a "
        "change log and a short test report after each cycle.",
    ),
    "de": (
        "Betrieb und Überwachung der Lagerverwaltungsplattform des Auftraggebers einschließlich "
        "Störungsbearbeitung während der Geschäftszeiten und eines monatlichen Serviceberichts.",
        "Second-Level-Support für die Außendienst-App des Auftraggebers mit Fehleranalyse, "
        "Hotfix-Releases und einer vierteljährlichen Durchsicht offener Punkte.",
        "Hosting und nächtliche Sicherung des Dokumentenarchivs des Auftraggebers in einem "
        "Rechenzentrum in der EU mit halbjährlichen Wiederherstellungstests.",
        "Wartung der Anbindung des Onlineshops des Auftraggebers an Zahlungs- und "
        "Versanddienstleister einschließlich Anpassungen bei Schnittstellenänderungen.",
        "Prüfung der Produktstammdaten des Auftraggebers auf Datenqualität mit einem "
        "wöchentlichen Bericht und Korrekturvorschlägen.",
        "Administration des Identitäts- und Zugriffsmanagements des Auftraggebers "
        "einschließlich Anlage und Sperrung von Benutzerkonten.",
        "Überwachung der Sensordaten-Pipeline des Auftraggebers mit Alarmierung außerhalb der "
        "Geschäftszeiten und einem Ursachenbericht zu jedem Ausfall.",
        "Vierteljährliche Sicherheitsupdates der Anwendungsserver des Auftraggebers mit "
        "Änderungsprotokoll und kurzem Testbericht nach jedem Zyklus.",
    ),
}

FEE_LINES = {
    "en": (
        ("Platform licence", "per month", 450_000),
        ("Service desk", "per month", 280_000),
        ("On-site support", "per day", 120_000),
        ("Change requests", "per hour", 14_500),
        ("Training", "per session", 95_000),
        ("Data migration", "one-off", 650_000),
        ("Penetration test", "per test", 780_000),
        ("Extra storage", "per TB per month", 12_000),
    ),
    "de": (
        ("Plattformlizenz", "pro Monat", 450_000),
        ("Service Desk", "pro Monat", 280_000),
        ("Vor-Ort-Support", "pro Tag", 120_000),
        ("Änderungsaufträge", "pro Stunde", 14_500),
        ("Schulung", "pro Termin", 95_000),
        ("Datenmigration", "einmalig", 650_000),
        ("Penetrationstest", "pro Test", 780_000),
        ("Zusätzlicher Speicher", "pro TB und Monat", 12_000),
    ),
}


def _values(pair: str, lang: str):
    companies = COMPANIES_DE if lang == "de" else COMPANIES_EN
    prefix = "DV" if lang == "de" else "SA"

    def values(index: int) -> dict[str, Any]:
        signed = spaced_date(pair, "date", index, date(2026, 1, 12))
        fee_rng = seeded(pair, "fees", index)
        lines = fee_rng.sample(FEE_LINES[lang], 2 + index % 3)
        number = 400 + index * 7 + seeded(pair, "number", index).randint(0, 6)
        monthly = (8_000 + index * 750 + seeded(pair, "fee", index).randint(0, 9) * 50) * 100
        return {
            "agreement_no": f"{prefix}-2026-{number:04d}",
            "date": fmt_date(signed, lang),
            "customer": pick(companies, pair, "customer", index),
            "start_date": fmt_date(signed + timedelta(days=14 + index), lang),
            "monthly_fee": fmt_money(monthly, lang),
            "services": pick(SERVICES[lang], pair, "services", index),
            "fees": [[name, unit, fmt_money(price, lang)] for name, unit, price in lines],
        }

    return values


def _spec_en() -> DocTypeSpec:
    pair = "service_agreement_en"
    return DocTypeSpec(
        pair=pair,
        doc_type="service_agreement",
        lang="en",
        blocks=(
            Title("title", "SERVICE AGREEMENT"),
            Field("field.agreement_no", "Agreement No.", "agreement_no", "text"),
            Field("field.date", "Date", "date", "date"),
            FixedLine("line.supplier", "Supplier", OWN_COMPANY_EN),
            Field("field.customer", "Customer", "customer", "text"),
            Field("field.start_date", "Start Date", "start_date", "date"),
            Field("field.monthly_fee", "Monthly Fee", "monthly_fee", "money"),
            Heading("heading.services", "1. Services"),
            FreeText("text.services", "services"),
            Heading("heading.fees", "2. Fees"),
            TableBlock("table.fees", ("Service", "Unit", "Price"), "fees"),
            Heading("heading.term", "3. Term and Termination"),
            Clause(
                "clause.term",
                "This Agreement starts on the Start Date and runs for an indefinite period. "
                "Either party may terminate it with three (3) months' written notice to the end "
                "of a calendar quarter.",
            ),
            Heading("heading.liability", "4. Limitation of Liability"),
            Clause(
                "clause.liability",
                "Except in cases of intent or gross negligence, the total liability of the "
                "Supplier under this Agreement shall not exceed EUR 250,000 per contract year.",
            ),
            Heading("heading.confidentiality", "5. Confidentiality"),
            Clause(
                "clause.confidentiality",
                "Each party shall keep confidential all information it recieves from the other "
                "party in connection with this Agreement and shall use it only for the purposes "
                "of this Agreement. This obligation survives termination for three years.",
            ),
            Heading("heading.data_protection", "6. Data Protection"),
            Clause(
                "clause.data_protection",
                "Where the Supplier processes personal data on behalf of the Customer, the "
                "parties shall conclude a data processing agreement in accordance with Article "
                "28 GDPR. The Supplier shall not transfer personal data outside the European "
                "Economic Area without the Customer's prior written consent.",
            ),
            Heading("heading.governing_law", "7. Governing Law and Jurisdiction"),
            Clause(
                "clause.governing_law",
                "This Agreement is governed by the laws of England and Wales. The courts of "
                "London have exclusive jurisdiction over any dispute arising from it.",
            ),
            Heading("heading.signatures", "8. Signatures"),
            Clause(
                "clause.signatures",
                "Signed on behalf of the Supplier and the Customer by their authorised "
                "representatives.",
                material=False,
            ),
        ),
        footer="Confidential — Page ",
        values=_values(pair, "en"),
        mutations={
            "change_liability_cap": {
                "target": "clause.liability",
                "replace": [["EUR 250,000", "EUR 25,000"]],
            },
            "change_governing_law": {
                "target": "clause.governing_law",
                "replace": [
                    ["laws of England and Wales", "laws of Ireland"],
                    ["courts of London", "courts of Dublin"],
                ],
            },
            "change_notice_period": {
                "target": "clause.term",
                "replace": [["three (3) months'", "two (2) weeks'"]],
            },
            "delete_clause": {"targets": ["heading.confidentiality", "clause.confidentiality"]},
            "fix_typo": {"target": "clause.confidentiality", "replace": [["recieves", "receives"]]},
            "whitespace_quotes": {
                "target": "clause.data_protection",
                "replace": [["Customer's", "Customer’s"], ["GDPR. The", "GDPR.  The"]],
            },
            "heading_caps": {"target": "heading.liability"},
            "empty_field": {"target": "field.customer"},
            "date_format": {"target": "field.date"},
            "invalid_value": {"target": "field.start_date", "value": "TBD"},
            "remove_row": {"target": "table.fees"},
            "remove_column": {"target": "table.fees", "column": 1},
            "delete_table": {"target": "table.fees"},
            "reorder_sections": {
                "first": ["heading.confidentiality", "clause.confidentiality"],
                "second": ["heading.data_protection", "clause.data_protection"],
            },
            "insert_benign": {
                "after": "clause.confidentiality",
                "text": "Note: A copy of this Agreement is kept in the Customer's contract "
                "register.",
            },
            "insert_material": {
                "after": "clause.liability",
                "text": "Notwithstanding clause 4, the Supplier accepts unlimited liability for "
                "all damages.",
            },
        },
    )


def _spec_de() -> DocTypeSpec:
    pair = "service_agreement_de"
    return DocTypeSpec(
        pair=pair,
        doc_type="service_agreement",
        lang="de",
        blocks=(
            Title("title", "DIENSTLEISTUNGSVERTRAG"),
            Field("field.agreement_no", "Vertragsnummer", "agreement_no", "text"),
            Field("field.date", "Datum", "date", "date"),
            FixedLine("line.supplier", "Auftragnehmer", OWN_COMPANY_DE),
            Field("field.customer", "Auftraggeber", "customer", "text"),
            Field("field.start_date", "Vertragsbeginn", "start_date", "date"),
            Field("field.monthly_fee", "Monatliche Vergütung", "monthly_fee", "money"),
            Heading("heading.services", "§ 1 Leistungen"),
            FreeText("text.services", "services"),
            Heading("heading.fees", "§ 2 Vergütung"),
            TableBlock("table.fees", ("Leistung", "Einheit", "Preis"), "fees"),
            Heading("heading.term", "§ 3 Laufzeit und Kündigung"),
            Clause(
                "clause.term",
                "Der Vertrag beginnt mit dem Vertragsbeginn und läuft auf unbestimmte Zeit. Er "
                "kann von jeder Partei mit einer Frist von drei Monaten zum Ende eines "
                "Kalenderquartals schriftlich gekündigt werden.",
            ),
            Heading("heading.liability", "§ 4 Haftungsbeschränkung"),
            Clause(
                "clause.liability",
                "Außer bei Vorsatz und grober Fahrlässigkeit ist die Haftung des Auftragnehmers "
                "aus diesem Vertrag auf 250.000 € je Vertragsjahr beschränkt.",
            ),
            Heading("heading.confidentiality", "§ 5 Vertraulichkeit"),
            Clause(
                "clause.confidentiality",
                "Die Parteien verpflichten sich, alle Informatoinen, die sie im Zusammenhang mit "
                "diesem Vertrag von der anderen Partei erhalten, vertraulich zu behandeln und "
                "ausschließlich für die Zwecke dieses Vertrags zu verwenden. Diese Pflicht gilt "
                "drei Jahre über das Vertragsende hinaus.",
            ),
            Heading("heading.data_protection", "§ 6 Datenschutz"),
            Clause(
                "clause.data_protection",
                "Soweit der Auftragnehmer personenbezogene Daten im Auftrag des Auftraggebers "
                "verarbeitet, schließen die Parteien einen Vertrag zur Auftragsverarbeitung nach "
                "Art. 28 DSGVO. Eine Übermittlung personenbezogener Daten in Länder außerhalb "
                "des Europäischen Wirtschaftsraums bedarf der vorherigen schriftlichen "
                "Zustimmung des Auftraggebers.",
            ),
            Heading("heading.governing_law", "§ 7 Anwendbares Recht und Gerichtsstand"),
            Clause(
                "clause.governing_law",
                "Es gilt das Recht der Bundesrepublik Deutschland. Ausschließlicher "
                "Gerichtsstand ist München.",
            ),
            Heading("heading.signatures", "§ 8 Unterschriften"),
            Clause(
                "clause.signatures",
                "Unterzeichnet von den vertretungsberechtigten Personen beider Parteien.",
                material=False,
            ),
        ),
        footer="Vertraulich — Seite ",
        values=_values(pair, "de"),
        mutations={
            "change_liability_cap": {
                "target": "clause.liability",
                "replace": [["250.000 €", "25.000 €"]],
            },
            "change_governing_law": {
                "target": "clause.governing_law",
                "replace": [["Gerichtsstand ist München", "Gerichtsstand ist Hamburg"]],
            },
            "change_notice_period": {
                "target": "clause.term",
                "replace": [["drei Monaten", "zwei Wochen"]],
            },
            "delete_clause": {"targets": ["heading.confidentiality", "clause.confidentiality"]},
            "fix_typo": {
                "target": "clause.confidentiality",
                "replace": [["Informatoinen", "Informationen"]],
            },
            "whitespace_quotes": {
                "target": "clause.data_protection",
                "replace": [["DSGVO. Eine", "DSGVO.  Eine"], ["Zustimmung des", "Zustimmung  des"]],
            },
            "heading_caps": {"target": "heading.liability"},
            "empty_field": {"target": "field.customer"},
            "date_format": {"target": "field.date"},
            "invalid_value": {"target": "field.start_date", "value": "offen"},
            "remove_row": {"target": "table.fees"},
            "remove_column": {"target": "table.fees", "column": 1},
            "delete_table": {"target": "table.fees"},
            "reorder_sections": {
                "first": ["heading.confidentiality", "clause.confidentiality"],
                "second": ["heading.data_protection", "clause.data_protection"],
            },
            "insert_benign": {
                "after": "clause.confidentiality",
                "text": "Hinweis: Eine Kopie dieses Vertrags wird im Vertragsregister des "
                "Auftraggebers abgelegt.",
            },
            "insert_material": {
                "after": "clause.liability",
                "text": "Abweichend von § 4 haftet der Auftragnehmer unbeschränkt für alle "
                "Schäden.",
            },
        },
    )


SPECS = (_spec_en(), _spec_de())
