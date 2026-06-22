"""assembler — deterministically fill a template DOCX (spec §6).

No intelligence here: it takes a render context (already-resolved field values)
and produces the final DOCX via docxtpl. Field definitions are used only to
*coerce* values into render-safe shapes (strings; table fields -> list[dict]).
"""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
from typing import Any

from docxtpl import DocxTemplate
from jinja2 import Environment
from jinja2.runtime import Undefined

from ..schemas.enums import ClassificationType, FieldType
from ..schemas.template import FieldDefinition


class _SilentUndefined(Undefined):
    """Render missing variables as empty strings instead of raising."""

    def __str__(self) -> str:  # noqa: D105
        return ""

    def __getattr__(self, _name):  # missing attrs on missing objects stay silent
        return self


def _coerce_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_bool(value: Any) -> bool:
    """Coerce a value to a real boolean (kept un-stringified for {%p if %})."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "no", "0", "off")
    return bool(value)


def _coerce_str_list(value: Any) -> list[str]:
    """Coerce a repeatable-section value into a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [ln.strip() for ln in value.splitlines() if ln.strip()]
    if isinstance(value, list):
        out = [_coerce_scalar(x) for x in value]
        return [s for s in out if s.strip()]
    return [_coerce_scalar(value)]


def _coerce_rows(value: Any, field: FieldDefinition) -> list[dict]:
    if not isinstance(value, list):
        return []
    cols = [c.field_name for c in field.columns]
    rows: list[dict] = []
    for row in value:
        if isinstance(row, dict):
            if cols:
                rows.append({c: _coerce_scalar(row.get(c, "")) for c in cols})
            else:
                rows.append({k: _coerce_scalar(v) for k, v in row.items()})
        elif isinstance(row, (list, tuple)):
            rows.append({cols[i]: _coerce_scalar(row[i]) for i in range(min(len(cols), len(row)))})
    return rows


def _image_bytes(value: Any) -> bytes | None:
    """Decode an image field value (raw bytes or a base64 / data-URL string)."""
    if not value:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.startswith("data:"):  # strip a "data:image/png;base64," prefix
            comma = s.find(",")
            if comma != -1:
                s = s[comma + 1 :]
        try:
            return base64.b64decode(s, validate=False)
        except (binascii.Error, ValueError):
            return None
    return None


def build_render_context(fields: list[FieldDefinition], raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw field->value map into a render-safe context.

    Every defined field is present (missing -> '' or []); table fields become a
    list of column-keyed dicts. Extra keys are passed through untouched.
    """
    ctx: dict[str, Any] = {}
    defined = set()
    for f in fields:
        defined.add(f.field_name)
        value = raw.get(f.field_name)
        if f.field_type == FieldType.IMAGE:
            ctx[f.field_name] = value  # raw (bytes / base64); applied via replace_pic
        elif f.field_type == FieldType.TABLE:
            ctx[f.field_name] = _coerce_rows(value, f)
        elif f.field_type == FieldType.BOOLEAN:
            ctx[f.field_name] = _coerce_bool(value if value is not None else f.default)
        elif f.classification == ClassificationType.REPEATABLE_SECTION:
            ctx[f.field_name] = _coerce_str_list(value)
        else:
            ctx[f.field_name] = _coerce_scalar(value)
    for k, v in raw.items():
        if k not in defined:
            ctx[k] = v
    return ctx


def assemble(
    template: str | bytes,
    context: dict[str, Any],
    fields: list[FieldDefinition] | None = None,
) -> bytes:
    """Render ``template`` (path or bytes) with ``context`` -> output DOCX bytes."""
    source: Any = BytesIO(template) if isinstance(template, (bytes, bytearray)) else str(template)
    tpl = DocxTemplate(source)
    render_ctx = build_render_context(fields, context) if fields else context
    # Image fields: swap the tagged picture in place (keeping its size/position),
    # or leave the original when no image was supplied. Must be queued before
    # render() — docxtpl applies replacements during its pre-processing pass.
    if fields:
        tpl.allow_missing_pics = True  # tolerate a template without that picture
        for f in fields:
            if f.field_type == FieldType.IMAGE:
                data = _image_bytes(render_ctx.pop(f.field_name, None))
                if data:
                    tpl.replace_pic(f.field_name, BytesIO(data))
    # autoescape is required: field values can contain &, <, > (e.g. "R&D",
    # "Smith & Jones"). Without it those land raw in the document XML and either
    # corrupt it (xmlParseEntityRef) or get silently dropped.
    jinja_env = Environment(undefined=_SilentUndefined, autoescape=True)
    tpl.render(render_ctx, jinja_env=jinja_env)
    out = BytesIO()
    tpl.save(out)
    return out.getvalue()
