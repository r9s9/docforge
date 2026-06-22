"""Derive FieldDefinitions and ValidationRules from a classification result.

This aggregation turns per-node classifications into the user-facing field list
(field_definitions.json) and the rule set (validation_rules.json) stored in a
template package. The review UI edits these directly.
"""

from __future__ import annotations

from ..common.textutil import slugify_field
from ..schemas.classification import ClassificationResult, ElementClassification
from ..schemas.enums import ClassificationType, FieldType, IssueSeverity, RuleType
from ..schemas.extraction import DocumentExtraction
from ..schemas.template import FieldDefinition, TableColumn, ValidationRule

_NUMBER_HEADER_HINTS = ("qty", "quantity", "amount", "price", "total", "cost", "count", "rate", "no.")
_DATE_HEADER_HINTS = ("date", "due")


def _column_type(header: str) -> FieldType:
    h = header.lower()
    if any(k in h for k in _DATE_HEADER_HINTS):
        return FieldType.DATE
    if any(k in h for k in _NUMBER_HEADER_HINTS):
        return FieldType.NUMBER
    return FieldType.TEXT


def _table_columns(headers: list[str]) -> list[TableColumn]:
    cols: list[TableColumn] = []
    used: set[str] = set()
    for i, h in enumerate(headers):
        base = slugify_field(h, fallback=f"col{i + 1}")
        name = base
        n = 2
        while name in used:
            name = f"{base}_{n}"
            n += 1
        used.add(name)
        cols.append(
            TableColumn(field_name=name, label=h or f"Column {i + 1}", field_type=_column_type(h))
        )
    return cols


def include_field_name(c: ElementClassification, element) -> str:
    """Boolean toggle field name for an optional node (shared by builder)."""
    base = c.field_name or slugify_field(element.text if element else "", fallback="section")
    return f"include_{base}"


def _label_from(field_name: str, classification: ElementClassification) -> str:
    if classification.static_prefix:
        lbl = classification.static_prefix.strip().rstrip(":").strip()
        if lbl:
            return lbl
    return field_name.replace("_", " ").title()


def derive_field_definitions(
    extraction: DocumentExtraction, result: ClassificationResult
) -> list[FieldDefinition]:
    """Build the ordered list of fillable fields from classifications."""
    # Map field_name -> section_key (from section understanding).
    field_section: dict[str, str] = {}
    for s in result.sections:
        for fname in s.field_names:
            field_section[fname] = s.section_key

    by_id = {e.node_id: e for e in extraction.elements}
    fields: list[FieldDefinition] = []
    for c in result.classifications:
        if not c.field_name:
            continue
        if c.classification not in (
            ClassificationType.DYNAMIC_TEXT,
            ClassificationType.DYNAMIC_DATE,
            ClassificationType.DYNAMIC_PERSON,
            ClassificationType.DYNAMIC_ENUM,
            ClassificationType.DYNAMIC_NUMBER,
            ClassificationType.REPEATABLE_TABLE,
            ClassificationType.REPEATABLE_SECTION,
        ):
            continue

        columns: list[TableColumn] = []
        if c.classification == ClassificationType.REPEATABLE_TABLE:
            el = by_id.get(c.node_id)
            headers = el.table_structure.headers if el and el.table_structure else []
            columns = _table_columns(headers)

        fields.append(
            FieldDefinition(
                field_name=c.field_name,
                label=_label_from(c.field_name, c),
                field_type=c.field_type or FieldType.TEXT,
                classification=c.classification,
                description=c.description,
                required=c.required and not c.optional,
                enum_values=c.enum_values,
                node_ids=[c.node_id],
                section_key=field_section.get(c.field_name),
                columns=columns,
                confidence=c.confidence,
            )
        )

    # Image fields: each embedded raster picture can become a fillable image
    # (the user uploads a replacement at generation), or be kept exactly as-is
    # (company logos, icons, brand marks). We surface one field per real picture;
    # the review UI defaults these to "keep original" so brand assets are never
    # lost — the user opts a picture into being dynamic. Only true raster pictures
    # qualify (content_type image/*); images embedded in text boxes / OLE objects
    # can't be swapped in place, so they're left untouched.
    used_names = {f.field_name for f in fields}
    image_nodes: set[str] = set()
    image_fields: list[FieldDefinition] = []
    n_img = 0
    for e in extraction.elements:
        ir = e.image_ref
        if not (ir and (ir.content_type or "").startswith("image/")):
            continue
        if e.node_id in image_nodes:
            continue
        n_img += 1
        scope = "header_" if (e.header_footer_scope or "").startswith("header") else (
            "footer_" if (e.header_footer_scope or "").startswith("footer") else ""
        )
        base = slugify_field(f"{scope}image_{n_img}", fallback=f"image_{n_img}")
        name = base
        k = 2
        while name in used_names:
            name = f"{base}_{k}"
            k += 1
        used_names.add(name)
        image_nodes.add(e.node_id)
        image_fields.append(
            FieldDefinition(
                field_name=name,
                label=f"Image {n_img}",
                field_type=FieldType.IMAGE,
                classification=ClassificationType.DYNAMIC_IMAGE,
                description="Replace this picture per document, or keep the original.",
                required=False,
                node_ids=[e.node_id],
                section_key=field_section.get(name),
                confidence=0.5,
            )
        )
    # A picture node should be an image field, not a text field — drop any text
    # field the classifier produced for the same node.
    if image_nodes:
        fields = [f for f in fields if not set(f.node_ids) & image_nodes]
    fields.extend(image_fields)

    # Boolean "include" toggles for optional content (present in some examples
    # but not others). Default True so optional content renders unless turned off.
    used_include: set[str] = set()
    for c in result.classifications:
        if not c.optional or c.classification == ClassificationType.AUTO_FIELD:
            continue
        el = by_id.get(c.node_id)
        name = include_field_name(c, el)
        if name in used_include:
            continue
        used_include.add(name)
        preview = (el.text[:40] if el and el.text else c.field_name) or "section"
        fields.append(
            FieldDefinition(
                field_name=name,
                label=f"Include: {preview}",
                field_type=FieldType.BOOLEAN,
                classification=ClassificationType.FIXED,
                description="Whether to include this optional content.",
                required=False,
                default=True,
                node_ids=[c.node_id],
                section_key=field_section.get(c.field_name),
                confidence=c.confidence,
            )
        )
    return fields


def derive_validation_rules(fields: list[FieldDefinition]) -> list[ValidationRule]:
    """Generate a baseline rule set from field definitions (spec §13)."""
    rules: list[ValidationRule] = []

    def add(field_name, rtype, params=None, message=None, severity=IssueSeverity.ERROR):
        rules.append(
            ValidationRule(
                rule_id=f"{field_name}:{rtype.value}",
                rule_type=rtype,
                field_name=field_name,
                params=params or {},
                message=message,
                severity=severity,
            )
        )

    for f in fields:
        if f.required:
            add(f.field_name, RuleType.REQUIRED, message=f"'{f.label}' is required")

        if f.field_type == FieldType.DATE:
            add(
                f.field_name,
                RuleType.DATE_FORMAT,
                params={"formats": ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%B %d, %Y"]},
                message=f"'{f.label}' should be a valid date",
                severity=IssueSeverity.WARNING,
            )
        elif f.field_type == FieldType.NUMBER:
            add(
                f.field_name,
                RuleType.NUMERIC_FORMAT,
                message=f"'{f.label}' should be numeric",
                severity=IssueSeverity.WARNING,
            )
        elif f.field_type == FieldType.ENUM and f.enum_values:
            add(
                f.field_name,
                RuleType.ENUM,
                params={"allowed": f.enum_values},
                message=f"'{f.label}' must be one of: {', '.join(f.enum_values)}",
            )
        elif f.field_type == FieldType.TABLE:
            required_cols = [c.field_name for c in f.columns if c.required]
            add(
                f.field_name,
                RuleType.TABLE_SCHEMA,
                params={
                    "columns": [c.field_name for c in f.columns],
                    "required_columns": required_cols,
                },
                message=f"Rows of '{f.label}' must match the column schema",
                severity=IssueSeverity.WARNING,
            )

    return rules
