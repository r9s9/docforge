"""template_registry — persist versioned template packages on disk (spec §12).

Layout per version:

  templates/{template_id}/{version}/
    template.docx
    template_intelligence.json
    field_definitions.json
    validation_rules.json
    manifest.json
    review_snapshot.json
    source_examples/        <- the original uploaded DOCX files
    extracted_sources/      <- normalized extraction JSON per source

The package directory is the source of truth for a template version; the DB only
stores a pointer + light metadata.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import get_settings
from ..schemas.template import (
    FieldDefinition,
    ReviewSnapshot,
    TemplateIntelligence,
    TemplateManifest,
    ValidationRule,
)

_TEMPLATE_DOCX = "template.docx"
_INTELLIGENCE = "template_intelligence.json"
_FIELDS = "field_definitions.json"
_RULES = "validation_rules.json"
_MANIFEST = "manifest.json"
_REVIEW = "review_snapshot.json"
_REPRESENTATIVE = "representative.json"
_REPRESENTATIVE_DOCX = "representative.docx"
_SOURCES = "source_examples"
_EXTRACTED = "extracted_sources"


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class TemplateRegistry:
    def __init__(self, base_dir: Path | str | None = None):
        self.base_dir = Path(base_dir) if base_dir else get_settings().templates_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ----- paths ----------------------------------------------------------
    def template_dir(self, template_id: str) -> Path:
        return self.base_dir / template_id

    def version_dir(self, template_id: str, version: int) -> Path:
        return self.template_dir(template_id) / str(version)

    def template_docx_path(self, template_id: str, version: int) -> Path:
        return self.version_dir(template_id, version) / _TEMPLATE_DOCX

    # ----- write ----------------------------------------------------------
    def save_version(
        self,
        template_id: str,
        version: int,
        *,
        template_docx: bytes,
        intelligence: TemplateIntelligence,
        fields: list[FieldDefinition],
        rules: list[ValidationRule],
        manifest: TemplateManifest,
        review: ReviewSnapshot,
        source_examples: dict[str, bytes] | None = None,
        extracted_sources: dict[str, dict] | None = None,
        representative_extraction: dict | None = None,
        representative_docx: bytes | None = None,
    ) -> Path:
        """Write a complete, self-contained template version package."""
        vdir = self.version_dir(template_id, version)
        vdir.mkdir(parents=True, exist_ok=True)

        (vdir / _TEMPLATE_DOCX).write_bytes(template_docx)
        _write_json(vdir / _INTELLIGENCE, intelligence.model_dump(mode="json"))
        _write_json(vdir / _FIELDS, [f.model_dump(mode="json") for f in fields])
        _write_json(vdir / _RULES, [r.model_dump(mode="json") for r in rules])
        _write_json(vdir / _MANIFEST, manifest.model_dump(mode="json"))
        _write_json(vdir / _REVIEW, review.model_dump(mode="json"))
        if representative_extraction is not None:
            _write_json(vdir / _REPRESENTATIVE, representative_extraction)
        if representative_docx is not None:
            (vdir / _REPRESENTATIVE_DOCX).write_bytes(representative_docx)

        sources_dir = vdir / _SOURCES
        sources_dir.mkdir(exist_ok=True)
        for name, data in (source_examples or {}).items():
            (sources_dir / _safe_name(name)).write_bytes(data)

        extracted_dir = vdir / _EXTRACTED
        extracted_dir.mkdir(exist_ok=True)
        for name, data in (extracted_sources or {}).items():
            _write_json(extracted_dir / (_safe_name(name) + ".json"), data)

        return vdir

    # ----- read -----------------------------------------------------------
    def list_versions(self, template_id: str) -> list[int]:
        tdir = self.template_dir(template_id)
        if not tdir.exists():
            return []
        versions = []
        for child in tdir.iterdir():
            if child.is_dir() and child.name.isdigit():
                versions.append(int(child.name))
        return sorted(versions)

    def load_manifest(self, template_id: str, version: int) -> TemplateManifest:
        return TemplateManifest.model_validate(_read_json(self.version_dir(template_id, version) / _MANIFEST))

    def load_intelligence(self, template_id: str, version: int) -> TemplateIntelligence:
        return TemplateIntelligence.model_validate(
            _read_json(self.version_dir(template_id, version) / _INTELLIGENCE)
        )

    def load_fields(self, template_id: str, version: int) -> list[FieldDefinition]:
        raw = _read_json(self.version_dir(template_id, version) / _FIELDS)
        return [FieldDefinition.model_validate(x) for x in raw]

    def load_rules(self, template_id: str, version: int) -> list[ValidationRule]:
        raw = _read_json(self.version_dir(template_id, version) / _RULES)
        return [ValidationRule.model_validate(x) for x in raw]

    def load_review(self, template_id: str, version: int) -> ReviewSnapshot:
        return ReviewSnapshot.model_validate(_read_json(self.version_dir(template_id, version) / _REVIEW))

    def load_representative(self, template_id: str, version: int) -> dict | None:
        """The representative document's normalized extraction (or None)."""
        path = self.version_dir(template_id, version) / _REPRESENTATIVE
        return _read_json(path) if path.exists() else None

    def representative_docx_path(self, template_id: str, version: int) -> Path:
        """Path to the original representative DOCX (used to rebuild on edit)."""
        return self.version_dir(template_id, version) / _REPRESENTATIVE_DOCX

    def load_source_examples(self, template_id: str, version: int) -> dict[str, bytes]:
        sdir = self.version_dir(template_id, version) / _SOURCES
        return {p.name: p.read_bytes() for p in sdir.iterdir()} if sdir.exists() else {}

    def load_extracted_sources(self, template_id: str, version: int) -> dict[str, dict]:
        edir = self.version_dir(template_id, version) / _EXTRACTED
        if not edir.exists():
            return {}
        return {p.stem: _read_json(p) for p in edir.iterdir() if p.suffix == ".json"}

    def source_example_names(self, template_id: str, version: int) -> list[str]:
        sdir = self.version_dir(template_id, version) / _SOURCES
        return sorted(p.name for p in sdir.iterdir()) if sdir.exists() else []


def _safe_name(name: str) -> str:
    """Sanitize a filename for safe storage inside the package."""
    keep = "-_. ()"
    cleaned = "".join(c for c in Path(name).name if c.isalnum() or c in keep).strip()
    return cleaned or "file"
