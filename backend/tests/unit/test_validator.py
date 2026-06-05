"""Unit tests for the validation rules engine."""

from __future__ import annotations

from docforge.schemas.enums import FieldType, IssueSeverity, RuleType, ValidationStatus
from docforge.schemas.template import FieldDefinition, ValidationRule
from docforge.validator import validate


def _fields():
    return [
        FieldDefinition(field_name="report_date", label="Report Date", field_type=FieldType.DATE, required=True),
        FieldDefinition(field_name="total", label="Total", field_type=FieldType.NUMBER, required=True),
    ]


def _rules():
    return [
        ValidationRule(rule_id="report_date:required", rule_type=RuleType.REQUIRED, field_name="report_date"),
        ValidationRule(
            rule_id="report_date:date_format",
            rule_type=RuleType.DATE_FORMAT,
            field_name="report_date",
            params={"formats": ["%Y-%m-%d"]},
            severity=IssueSeverity.WARNING,
        ),
        ValidationRule(rule_id="total:required", rule_type=RuleType.REQUIRED, field_name="total"),
        ValidationRule(
            rule_id="total:numeric_format",
            rule_type=RuleType.NUMERIC_FORMAT,
            field_name="total",
            severity=IssueSeverity.WARNING,
        ),
    ]


def test_validate_pass():
    report = validate({"report_date": "2026-06-01", "total": "$1,200.00"}, _fields(), _rules())
    assert report.status == ValidationStatus.PASS
    assert report.issues == []


def test_validate_missing_required_is_fail():
    report = validate({"report_date": "", "total": "5"}, _fields(), _rules())
    assert report.status == ValidationStatus.FAIL
    assert any(i.field_name == "report_date" and i.severity == IssueSeverity.ERROR for i in report.issues)


def test_validate_bad_date_is_warning():
    report = validate({"report_date": "not a date", "total": "5"}, _fields(), _rules())
    assert any("date" in i.message.lower() for i in report.issues)


def test_validate_table_schema():
    fields = [
        FieldDefinition(
            field_name="rows",
            label="Rows",
            field_type=FieldType.TABLE,
            required=True,
        )
    ]
    rules = [
        ValidationRule(
            rule_id="rows:table_schema",
            rule_type=RuleType.TABLE_SCHEMA,
            field_name="rows",
            params={"columns": ["a", "b"], "required_columns": ["a"]},
            severity=IssueSeverity.WARNING,
        )
    ]
    report = validate({"rows": [{"a": "x", "b": "y"}, {"b": "only-b"}]}, fields, rules)
    assert any("missing required column 'a'" in i.message for i in report.issues)
