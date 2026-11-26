"""Data protection impact assessment (GDPR Art. 35), in English. Analyze only.

A document-control block opens it. Its first row is the same in every document
("Classification | Confidential"); the reference, version, date and owner below it change. The
processing activity, its purpose, the data categories, the legal basis, the risk register and
the data protection officer change per document. The GDPR wording on necessity and the sign-off
are boilerplate.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from evals.corpus.model import (
    Clause,
    DocTypeSpec,
    Field,
    FixedLine,
    FreeText,
    Heading,
    InfoRow,
    InfoTable,
    TableBlock,
    Title,
)
from evals.corpus.values import OWN_COMPANY_EN, PEOPLE, fmt_date, pick, seeded, spaced_date

# (processing activity, purpose, categories of personal data): plain descriptions, not names.
ACTIVITIES = (
    ("Customer support ticketing",
     "Customer requests are recorded, assigned and answered in a ticketing system, so that every "
     "request is tracked until it is resolved and recurring problems can be analysed.",
     "Names, e-mail addresses, phone numbers and the content of support requests"),
    ("Employee time recording",
     "Working hours are recorded per employee to pay overtime correctly, to plan shifts and to "
     "meet the legal duty to record working time.",
     "Names, staff numbers, working hours and absence types"),
    ("Video surveillance of the warehouse entrance",
     "Cameras at the warehouse entrance record who enters outside opening hours, to prevent theft "
     "and to investigate incidents.",
     "Video images of employees, drivers and visitors"),
    ("Applicant management",
     "Applications are collected and reviewed in an online portal, and shortlisted applicants "
     "are invited to interviews.",
     "Names, contact details, CVs, certificates and interview notes"),
    ("Vehicle telematics for the service fleet",
     "The location and mileage of service vehicles are tracked to plan routes, to send the "
     "nearest technician and to account for fuel costs.",
     "Driver names, vehicle locations, routes and driving times"),
    ("Visitor registration at reception",
     "Visitors sign in at reception, so that the company knows who is on site in an emergency "
     "and can issue visitor badges.",
     "Names, companies, signatures and the time of arrival and departure"),
    ("Customer satisfaction survey",
     "Customers are asked to rate the service after a project closes, and the answers are used "
     "to improve the service.",
     "Names, e-mail addresses, ratings and free-text comments"),
    ("Newsletter sign-up and tracking",
     "Subscribers receive a monthly newsletter, and opening rates are measured to choose the "
     "topics readers find useful.",
     "E-mail addresses, subscription dates and opening statistics"),
)
LEGAL_BASES = (
    "Article 6(1)(a) GDPR – consent",
    "Article 6(1)(b) GDPR – performance of a contract",
    "Article 6(1)(c) GDPR – legal obligation",
    "Article 6(1)(e) GDPR – task in the public interest",
    "Article 6(1)(f) GDPR – legitimate interests",
    "Article 9(2)(b) GDPR – employment and social security",
)
VERSIONS = ("1.0", "1.1", "1.2", "2.0", "2.1", "2.2", "3.0", "3.1")
RISKS = (
    ("Unauthorised access to the records", "Role-based access and a quarterly access review"),
    ("Data kept longer than needed", "Automatic deletion when the retention period ends"),
    ("Transfer to a processor outside the EEA", "Standard contractual clauses and a transfer "
     "assessment"),
    ("Data subjects are not informed", "Privacy notice linked in every form"),
    ("Loss of a laptop with exported data", "Full-disk encryption and no local exports"),
    ("Wrong data leads to wrong decisions", "Checks at entry and a correction process"),
    ("Data used for another purpose", "Purpose recorded in the record of processing activities"),
    ("Weak passwords on the vendor portal", "Single sign-on with multi-factor authentication"),
)
LEVELS = ("Low", "Medium", "High")


def _values(pair: str):
    def values(index: int) -> dict[str, Any]:
        activity, purpose, categories = ACTIVITIES[
            pick(range(len(ACTIVITIES)), pair, "activity", index)]
        owner = pick(PEOPLE, pair, "owner", index)
        dpo = pick(PEOPLE, pair, "dpo", index)
        if dpo == owner:  # pick() is a permutation, so the shifted index gives someone else
            dpo = pick(PEOPLE, pair, "dpo", index + len(PEOPLE) // 2)
        rng = seeded(pair, "risks", index)
        risks = [[risk, rng.choice(LEVELS), rng.choice(LEVELS), measure]
                 for risk, measure in rng.sample(RISKS, 2 + index % 3)]
        number = 11 + 7 * index + seeded(pair, "reference", index).randint(0, 5)  # rises
        return {
            "reference": f"DPIA-2026-{number:03d}",
            "version": pick(VERSIONS, pair, "version", index),
            "date": fmt_date(spaced_date(pair, "date", index, date(2026, 2, 9)), "en"),
            "owner": owner,
            "activity": activity,
            "purpose": purpose,
            "data_categories": categories,
            "legal_basis": pick(LEGAL_BASES, pair, "legal_basis", index),
            "risks": risks,
            "dpo": dpo,
        }

    return values


def _spec_en() -> DocTypeSpec:
    pair = "dpia_en"
    return DocTypeSpec(
        pair=pair,
        doc_type="dpia",
        lang="en",
        blocks=(
            Title("title", "DATA PROTECTION IMPACT ASSESSMENT"),
            InfoTable("info.document", (
                InfoRow("cell.classification", "Classification", text="Confidential"),
                InfoRow("cell.reference", "Reference", key="reference"),
                InfoRow("cell.version", "Version", key="version"),
                InfoRow("cell.date", "Assessment date", key="date", field_type="date"),
                InfoRow("cell.owner", "Owner", key="owner", field_type="person"),
            )),
            FixedLine("fixed.controller", "Controller", OWN_COMPANY_EN),
            Heading("heading.description", "1. Description of the processing"),
            Field("field.activity", "Processing activity", "activity", "text"),
            FreeText("text.purpose", "purpose"),
            Field("field.data_categories", "Categories of personal data", "data_categories",
                  "text"),
            Field("field.legal_basis", "Legal basis", "legal_basis", "text"),
            Heading("heading.necessity", "2. Necessity and proportionality"),
            Clause(
                "clause.necessity",
                "The processing is limited to the personal data needed for the purpose described "
                "above. The data is kept only as long as that purpose requires and is then deleted "
                "or anonymised. Data subjects are informed in line with Articles 13 and 14 GDPR "
                "and can exercise their rights through the contact given in the privacy notice.",
            ),
            Heading("heading.risks", "3. Risks to the rights and freedoms of data subjects"),
            TableBlock("table.risks", ("Risk", "Likelihood", "Severity", "Mitigation"), "risks"),
            Heading("heading.signoff", "4. Sign-off"),
            Clause(
                "clause.signoff",
                "The data protection officer was consulted on this assessment. With the measures "
                "above, the remaining risk is acceptable. The assessment is reviewed whenever the "
                "processing changes, and at least every two years.",
            ),
            Field("field.dpo", "Data protection officer", "dpo", "person"),
        ),
        footer="Confidential — Page ",
        values=_values(pair),
    )


SPECS = (_spec_en(),)
