"""Every document type in the corpus, keyed by type/language pair (e.g. ``invoice_de``)."""

from __future__ import annotations

from evals.corpus.doc_types import invoice, minutes, nda, service_agreement
from evals.corpus.model import DocTypeSpec

SPECS: dict[str, DocTypeSpec] = {
    spec.pair: spec
    for module in (service_agreement, nda, invoice, minutes)
    for spec in module.SPECS
}
