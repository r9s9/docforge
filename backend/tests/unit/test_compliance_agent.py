"""Phase-3 compliance agent: the AI judge enriches differences + adds a dimension."""

from __future__ import annotations

from docforge.ai.prompts import LLMComplianceJudgement, LLMComplianceVerdict
from docforge.compliance.judge import judge_compliance
from docforge.schemas.compliance import ComplianceDifference, ComplianceReport


class _JudgeClient:
    active = True
    model = "mock"
    provider = "openai"

    def __init__(self, resp):
        self._resp = resp

    def complete_agentic(self, *, schema, **kw):
        return self._resp

    def for_tier(self, tier):
        return self


def test_judge_enriches_severity_and_adds_semantic_dimension():
    report = ComplianceReport(
        template_id="t", version=1,
        differences=[
            ComplianceDifference(kind="changed_fixed", severity="error", message="X changed"),
            ComplianceDifference(kind="missing_fixed", severity="warning", message="Y missing"),
        ],
    )
    resp = LLMComplianceJudgement(
        verdicts=[
            LLMComplianceVerdict(index=0, material=False, severity="info", rationale="cosmetic reword"),
            LLMComplianceVerdict(index=1, material=True, severity="error", rationale="required clause dropped"),
        ]
    )
    out = judge_compliance(report, document_type="NDA", client=_JudgeClient(resp))
    assert out.differences[0].severity == "info" and "cosmetic reword" in out.differences[0].message
    assert out.differences[1].severity == "error" and "required clause dropped" in out.differences[1].message
    sem = next(d for d in out.dimensions if d.name == "semantic")
    assert sem.score == 50.0  # 1 of 2 judged material


def test_judge_noop_when_inactive():
    report = ComplianceReport(
        template_id="t", version=1, differences=[ComplianceDifference(kind="x")]
    )

    class _Off:
        active = False

    out = judge_compliance(report, client=_Off())
    assert all(d.name != "semantic" for d in out.dimensions)


def test_judge_noop_with_no_differences():
    report = ComplianceReport(template_id="t", version=1, differences=[])
    out = judge_compliance(report, client=_JudgeClient(LLMComplianceJudgement()))
    assert all(d.name != "semantic" for d in out.dimensions)
