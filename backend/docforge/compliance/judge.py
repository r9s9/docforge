"""AI semantic judge over a deterministic compliance report.

The deterministic checker finds *where* a document differs from its template;
the judge decides *whether each difference matters* — a material compliance
violation versus a benign/cosmetic difference — and explains why. It enriches
each difference's severity + message and appends a ``semantic`` dimension to the
report. The deterministic score/grade is left intact (the judge augments, it
does not silently overrule the structural backbone). Best-effort: any failure
returns the report unchanged.
"""

from __future__ import annotations

import logging

from ..ai.client import LLMClient, LLMError
from ..ai.prompts import LLMComplianceJudgement, build_compliance_judge_prompt
from ..ai.tools import normalizer_tools
from ..schemas.compliance import ComplianceReport, DimensionScore
from ..settings_store import REASONING_TIER

logger = logging.getLogger("docforge.compliance.judge")

_VALID_SEVERITY = {"error", "warning", "info"}
# Cap how many differences we send to the judge (bound cost on huge diffs).
_MAX_DIFFS = 40


def judge_compliance(
    report: ComplianceReport,
    *,
    document_type: str = "",
    client: LLMClient,
    cancel_event=None,
) -> ComplianceReport:
    """Enrich ``report``'s differences with material/benign verdicts + rationale."""
    if not client.active or not report.differences:
        return report

    diffs = [
        {
            "index": i,
            "kind": d.kind,
            "field_name": d.field_name,
            "severity": d.severity,
            "expected": (d.expected or "")[:200],
            "found": (d.found or "")[:200],
            "message": d.message,
        }
        for i, d in enumerate(report.differences[:_MAX_DIFFS])
    ]
    system, developer, user = build_compliance_judge_prompt(document_type, diffs)
    try:
        result = client.complete_agentic(
            system=system, developer=developer, user=user, schema=LLMComplianceJudgement,
            tools=normalizer_tools(), tier=REASONING_TIER, cancel_event=cancel_event,
        )
    except LLMError:
        logger.debug("compliance judge failed; keeping deterministic report", exc_info=True)
        return report

    material = 0
    judged = 0
    for v in result.verdicts:
        if not (0 <= v.index < len(report.differences)):
            continue
        judged += 1
        d = report.differences[v.index]
        if v.severity in _VALID_SEVERITY:
            d.severity = v.severity
        if v.rationale:
            d.message = f"{d.message} — {v.rationale}" if d.message else v.rationale
        if v.material:
            material += 1

    total = judged or len(report.differences)
    sem_score = round(100.0 * (1 - material / total), 1) if total else 100.0
    report.dimensions.append(
        DimensionScore(name="semantic", satisfied=float(total - material), total=float(total), score=sem_score)
    )
    logger.info("compliance judge: %d/%d differences judged material", material, judged)
    return report
