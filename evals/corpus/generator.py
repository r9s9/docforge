"""Deterministic document builder: a spec and a document index give .docx bytes + ground truth.

The building blocks follow the patterns of ``backend/docforge/sampledata.py`` (a bold label run
followed by a value run, "Table Grid" tables, a PAGE field in the footer). They are written out
here rather than imported, because the corpus is the evals' own test data.

Saved files are re-zipped with a fixed timestamp and fixed metadata, so the same spec gives
byte-identical files on every run. Compressed bytes can still differ between zlib builds, so
the manifest identifies a file by ``content_hash`` (its uncompressed parts), not its raw bytes.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

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

EXAMPLES = 5  # ex_01..ex_05: analyze input and the frozen template
HELD_OUT = 8  # held_01..held_08: clean controls and the bases for mutations
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

GroundTruth = list[dict[str, Any]]


def doc_id(index: int) -> str:
    """``ex_01``..``ex_05`` for indices 0-4, then ``held_01``..``held_08``."""
    if index < EXAMPLES:
        return f"ex_{index + 1:02d}"
    return f"held_{index - EXAMPLES + 1:02d}"


def all_doc_ids() -> list[str]:
    """Every document of a type, examples first."""
    return [doc_id(i) for i in range(EXAMPLES + HELD_OUT)]


def doc_index(name: str) -> int:
    """Inverse of ``doc_id``."""
    kind, number = name.split("_")
    return int(number) - 1 if kind == "ex" else EXAMPLES + int(number) - 1


def build_document(spec: DocTypeSpec, index: int) -> tuple[bytes, GroundTruth]:
    """Build document ``index`` of ``spec``; return its bytes and its ground truth."""
    values = spec.values(index)
    doc = Document()
    truth: GroundTruth = []
    for block_index, block in enumerate(spec.blocks):
        element = _add_block(doc, block, values)
        element["locator"] = {"scope": "body", "block": block_index}
        truth.append(element)
    truth.append(_add_footer(doc, spec.footer))
    return docx_bytes(doc), truth


def docx_bytes(doc) -> bytes:
    """Save a python-docx Document and normalise the zip so equal content gives equal bytes."""
    buffer = io.BytesIO()
    doc.save(buffer)
    return normalize_zip(buffer.getvalue())


def normalize_zip(data: bytes) -> bytes:
    """Rewrite a .docx with a fixed timestamp and fixed attributes on every entry."""
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            entry = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o644 << 16
            target.writestr(entry, source.read(info.filename))
    return out.getvalue()


def content_hash(data: bytes) -> str:
    """sha256 over a .docx's parts (name + uncompressed bytes, in zip order)."""
    digest = hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            digest.update(info.filename.encode() + b"\0")
            digest.update(archive.read(info.filename) + b"\0")
    return digest.hexdigest()


# --- blocks -------------------------------------------------------------------------------


def _add_block(doc, block, values: dict[str, Any]) -> dict[str, Any]:
    if isinstance(block, Title):
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(block.text)
        run.bold = True
        run.font.size = Pt(18)
        return {"id": block.id, "kind": "fixed", "text": block.text, "material_if_changed": False}
    if isinstance(block, Field):
        value = values[block.key]
        _labelled(doc, block.label, value)
        return {
            "id": block.id,
            "kind": "field",
            "field_type": block.field_type,
            "label": block.label,
            "value": value,
            "required": block.required,
            "text": f"{block.label}: {value}",
        }
    if isinstance(block, FixedLine):
        _labelled(doc, block.label, block.text)
        return {
            "id": block.id,
            "kind": "fixed",
            "label": block.label,
            "text": f"{block.label}: {block.text}",
            "material_if_changed": True,
        }
    if isinstance(block, Heading):
        doc.add_heading(block.text, level=block.level)
        return {
            "id": block.id,
            "kind": "fixed",
            "text": block.text,
            "style": f"Heading {block.level}",
            "material_if_changed": False,
        }
    if isinstance(block, Clause):
        doc.add_paragraph(block.text)
        return {
            "id": block.id,
            "kind": "fixed",
            "text": block.text,
            "material_if_changed": block.material,
        }
    if isinstance(block, FreeText):
        text = values[block.key]
        doc.add_paragraph(text)
        return {
            "id": block.id,
            "kind": "field",
            "field_type": "multiline_text",
            "value": text,
            "required": True,
            "text": text,
        }
    if isinstance(block, TableBlock):
        rows = values[block.key]
        _table(doc, list(block.headers), rows)
        return {
            "id": block.id,
            "kind": "table",
            "headers": list(block.headers),
            "rows": rows,
            "text": " | ".join(block.headers),
            "row_removal_material": block.row_removal_material,
        }
    raise TypeError(f"unknown block {block!r}")


def _labelled(doc, label: str, value: str) -> None:
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(f"{label}: ")
    run.bold = True
    paragraph.add_run(value)


def _table(doc, headers: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for cell, header in zip(table.rows[0].cells, headers, strict=True):
        cell.text = header
        for run in cell.paragraphs[0].runs:
            run.bold = True
    for row in rows:
        for cell, value in zip(table.add_row().cells, row, strict=True):
            cell.text = value


def _add_footer(doc, text: str) -> dict[str, Any]:
    paragraph = doc.sections[0].footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.add_run(text)
    run = paragraph.add_run()
    for tag, attr, value in (
        ("w:fldChar", "w:fldCharType", "begin"),
        ("w:instrText", None, "PAGE"),
        ("w:fldChar", "w:fldCharType", "end"),
    ):
        element = OxmlElement(tag)
        if attr:
            element.set(qn(attr), value)
        else:
            element.set(qn("xml:space"), "preserve")
            element.text = value
        run._r.append(element)
    return {
        "id": "footer.page",
        "kind": "auto",
        "text": text,
        "locator": {"scope": "footer:0", "block": 0},
    }
