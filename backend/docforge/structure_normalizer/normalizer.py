"""structure_normalizer — build a normalized DocumentExtraction from a .docx.

This is the single entry point used by ingestion. It combines python-docx's
object model (robust paragraph/table/run access) with DocxPackage (media hashes,
relationships, numbering) to produce the renderer-agnostic schema in §7.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from ..common.textutil import semantic_hints
from ..ooxml_extractor.numbering import NumberingResolver
from ..ooxml_extractor.package import DocxPackage
from ..schemas.enums import ElementType
from ..schemas.extraction import (
    DocumentExtraction,
    DocumentSection,
    NormalizedElement,
    NumberingInfo,
)
from .text import (
    extract_runs,
    extract_table_structure,
    paragraph_formatting,
    paragraph_images,
)
from .walk import WalkNode, walk_document


def _safe_xpath(obj) -> str:
    try:
        el = obj._element
        return el.getroottree().getpath(el)
    except Exception:  # pragma: no cover - defensive
        return ""


def _heading_subtype(style_name: str | None) -> str | None:
    if not style_name:
        return None
    s = style_name.lower()
    if s.startswith("heading"):
        digits = "".join(ch for ch in s if ch.isdigit())
        return digits or "1"
    if s in ("title", "subtitle"):
        return s
    return None


def _numbering_info(paragraph: Paragraph, resolver: NumberingResolver) -> NumberingInfo | None:
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is None:
        return None
    numPr = pPr.find(qn("w:numPr"))
    if numPr is None:
        return None
    ilvl_el = numPr.find(qn("w:ilvl"))
    numid_el = numPr.find(qn("w:numId"))
    level = 0
    if ilvl_el is not None and ilvl_el.get(qn("w:val")):
        try:
            level = int(ilvl_el.get(qn("w:val")))
        except ValueError:
            level = 0
    num_id = numid_el.get(qn("w:val")) if numid_el is not None else None
    return NumberingInfo(
        num_id=num_id,
        level=level,
        is_ordered=resolver.is_ordered(num_id, level),
    )


def _has_field(paragraph: Paragraph) -> tuple[bool, bool]:
    """Return (has_word_field, is_toc)."""
    p = paragraph._p
    simple = p.find(".//" + qn("w:fldSimple"))
    instr = p.findall(".//" + qn("w:instrText"))
    has_field = simple is not None or len(instr) > 0
    is_toc = False
    if simple is not None and "TOC" in (simple.get(qn("w:instr")) or ""):
        is_toc = True
    for it in instr:
        if it.text and "TOC" in it.text:
            is_toc = True
    return has_field, is_toc


def _build_sections(doc) -> list[DocumentSection]:
    sections: list[DocumentSection] = []
    for i, sec in enumerate(doc.sections):
        def tw(length):
            return int(length.twips) if length is not None else None

        margins = {
            k: v
            for k, v in {
                "top": tw(sec.top_margin),
                "bottom": tw(sec.bottom_margin),
                "left": tw(sec.left_margin),
                "right": tw(sec.right_margin),
                "header": tw(sec.header_distance),
                "footer": tw(sec.footer_distance),
            }.items()
            if v is not None
        }
        sections.append(
            DocumentSection(
                section_index=i,
                page_width=tw(sec.page_width),
                page_height=tw(sec.page_height),
                margins=margins,
            )
        )
    return sections


def _element_from_walknode(
    wn: WalkNode,
    pkg: DocxPackage,
    doc_rels,
    resolver: NumberingResolver,
) -> NormalizedElement:
    if wn.kind == "table":
        table = wn.obj
        ts = extract_table_structure(table)
        subtype = f"r{wn.row}c{wn.col}" if wn.row is not None else None
        return NormalizedElement(
            node_id=wn.node_id,
            parent_node_id=wn.parent_node_id,
            xpath=_safe_xpath(table),
            type=ElementType.TABLE,
            subtype=subtype,
            text="",
            table_structure=ts,
            position_index=wn.position_index,
            header_footer_scope=wn.scope,
            section_index=wn.section_index,
            semantic_hints=["table"],
        )

    # paragraph
    para: Paragraph = wn.obj
    text = para.text or ""
    fmt = paragraph_formatting(para)
    images = paragraph_images(para, pkg, doc_rels)
    numbering = _numbering_info(para, resolver)
    has_field, is_toc = _has_field(para)

    # Decide element type.
    heading_sub = _heading_subtype(fmt.style_name)
    if heading_sub is not None:
        etype = ElementType.HEADING
        subtype = heading_sub
    elif numbering is not None:
        etype = ElementType.LIST_ITEM
        subtype = "ordered" if numbering.is_ordered else "bullet"
    elif images and not text.strip():
        etype = ElementType.IMAGE
        subtype = None
    elif has_field and not text.strip():
        etype = ElementType.FIELD
        subtype = "toc" if is_toc else "field"
    else:
        etype = ElementType.PARAGRAPH
        subtype = f"r{wn.row}c{wn.col}" if wn.row is not None else None

    hints = semantic_hints(text)
    if images:
        hints.append("image")
    if has_field:
        hints.append("auto_field")
    if is_toc:
        hints.append("toc")
    if wn.row is not None:
        hints.append("in_table")

    return NormalizedElement(
        node_id=wn.node_id,
        parent_node_id=wn.parent_node_id,
        xpath=_safe_xpath(para),
        type=etype,
        subtype=subtype,
        style_name=fmt.style_name,
        text=text,
        runs=extract_runs(para),
        image_ref=images[0] if images else None,
        numbering_info=numbering,
        position_index=wn.position_index,
        header_footer_scope=wn.scope,
        section_index=wn.section_index,
        formatting=fmt,
        semantic_hints=hints,
    )


def build_extraction(
    file_path: str | Path,
    document_id: str,
    filename: str | None = None,
) -> DocumentExtraction:
    """Parse a .docx file into the normalized DocumentExtraction schema."""
    file_path = Path(file_path)
    filename = filename or file_path.name

    pkg = DocxPackage.from_path(file_path)
    doc_part = pkg.main_document_name()
    doc_rels = pkg.rels_for(doc_part)
    resolver = NumberingResolver.from_package(pkg, doc_part)

    doc = Document(str(file_path))
    nodes = walk_document(doc)

    elements = [_element_from_walknode(wn, pkg, doc_rels, resolver) for wn in nodes]
    sections = _build_sections(doc)

    # Stable content hash over (type, text) — used to detect duplicate uploads.
    hasher = hashlib.sha256()
    for el in elements:
        hasher.update(f"{el.type.value}:{el.text}\n".encode("utf-8", "ignore"))
    content_hash = hasher.hexdigest()

    return DocumentExtraction(
        document_id=document_id,
        filename=filename,
        page_count=pkg.page_count(),
        content_hash=content_hash,
        sections=sections,
        elements=elements,
    )
