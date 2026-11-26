"""Every document type in the corpus, keyed by type/language pair (e.g. ``invoice_de``).

``SPECS`` are the types every suite uses: comply checks their held-out and mutated documents,
generate fills their templates, and analyze builds templates from their examples.
``ANALYZE_SPECS`` are used by analyze only (added in M4): they have examples and no held-out or
mutated documents, so the comply and generate cases, and the corpus hash, are what they were.
"""

from __future__ import annotations

from evals.corpus.doc_types import dpia, invoice, minutes, nda, service_agreement, status_report
from evals.corpus.model import DocTypeSpec

SPECS: dict[str, DocTypeSpec] = {
    spec.pair: spec
    for module in (service_agreement, nda, invoice, minutes)
    for spec in module.SPECS
}
ANALYZE_SPECS: dict[str, DocTypeSpec] = {
    spec.pair: spec for module in (dpia, status_report) for spec in module.SPECS
}
ALL_SPECS: dict[str, DocTypeSpec] = {**SPECS, **ANALYZE_SPECS}

# For analyze's shared-value check: the labelled field whose value the shared-value document
# (``shared_02``, the second example) copies from the first example, as when two invoices go to
# the same customer.
SHARED_FIELDS: dict[str, str] = {
    "service_agreement_en": "field.customer",
    "service_agreement_de": "field.customer",
    "nda_en": "field.party_b",
    "nda_de": "field.party_b",
    "invoice_en": "field.customer",
    "invoice_de": "field.customer",
    "minutes_en": "field.meeting",  # a recurring meeting
    "dpia_en": "field.dpo",
    "status_report_en": "field.prepared_by",
}
