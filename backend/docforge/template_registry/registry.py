"""template_registry — persist versioned template packages (spec §12).

Layout per version (keys under ``templates/<id>/<version>/``):

  template.docx
  template_intelligence.json
  field_definitions.json
  validation_rules.json
  manifest.json
  review_snapshot.json
  representative.json / representative.docx
  source_examples/        <- the original uploaded DOCX files
  extracted_sources/      <- normalized extraction JSON per source

The package is the source of truth for a template version; the DB stores only a
pointer + light metadata. Persistence goes through the :mod:`storage` layer, so
the same code works on a local disk (dev) or Supabase Storage (disk-less prod).
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path

from ..schemas.template import (
    FieldDefinition,
    ReviewSnapshot,
    TemplateIntelligence,
    TemplateManifest,
    ValidationRule,
)
from ..storage import TEMPLATES, Storage, get_storage, join_key

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


class TemplateRegistry:
    """Reads/writes template-version packages through the storage backend.

    The legacy positional argument (a base directory ``Path``) is accepted and
    ignored for backward compatibility — the active storage backend is resolved
    from settings. Pass a :class:`Storage` explicitly to override (e.g. tests).
    """

    def __init__(self, storage_or_dir: Storage | Path | str | None = None):
        self.storage: Storage = (
            storage_or_dir if isinstance(storage_or_dir, Storage) else get_storage()
        )

    # ----- keys -----------------------------------------------------------
    def _vkey(self, template_id: str, version: int, *parts: str) -> str:
        return join_key(TEMPLATES, template_id, str(version), *parts)

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
    ) -> str:
        """Write a complete, self-contained template version package."""
        st = self.storage
        st.put_bytes(self._vkey(template_id, version, _TEMPLATE_DOCX), template_docx)
        st.put_json(self._vkey(template_id, version, _INTELLIGENCE), intelligence.model_dump(mode="json"))
        st.put_json(self._vkey(template_id, version, _FIELDS), [f.model_dump(mode="json") for f in fields])
        st.put_json(self._vkey(template_id, version, _RULES), [r.model_dump(mode="json") for r in rules])
        st.put_json(self._vkey(template_id, version, _MANIFEST), manifest.model_dump(mode="json"))
        st.put_json(self._vkey(template_id, version, _REVIEW), review.model_dump(mode="json"))
        if representative_extraction is not None:
            st.put_json(self._vkey(template_id, version, _REPRESENTATIVE), representative_extraction)
        if representative_docx is not None:
            st.put_bytes(self._vkey(template_id, version, _REPRESENTATIVE_DOCX), representative_docx)

        for name, data in (source_examples or {}).items():
            st.put_bytes(self._vkey(template_id, version, _SOURCES, _safe_name(name)), data)
        for name, data in (extracted_sources or {}).items():
            st.put_json(self._vkey(template_id, version, _EXTRACTED, _safe_name(name) + ".json"), data)

        return join_key(TEMPLATES, template_id, str(version))

    # ----- read: JSON metadata -------------------------------------------
    def list_versions(self, template_id: str) -> list[int]:
        prefix = join_key(TEMPLATES, template_id) + "/"
        versions: set[int] = set()
        for key in self.storage.list_prefix(prefix):
            rest = key[len(prefix):]
            seg = rest.split("/", 1)[0]
            if seg.isdigit():
                versions.add(int(seg))
        return sorted(versions)

    def version_exists(self, template_id: str, version: int) -> bool:
        return self.storage.exists(self._vkey(template_id, version, _MANIFEST))

    def load_manifest(self, template_id: str, version: int) -> TemplateManifest:
        return TemplateManifest.model_validate(
            self.storage.get_json(self._vkey(template_id, version, _MANIFEST))
        )

    def load_intelligence(self, template_id: str, version: int) -> TemplateIntelligence:
        return TemplateIntelligence.model_validate(
            self.storage.get_json(self._vkey(template_id, version, _INTELLIGENCE))
        )

    def load_fields(self, template_id: str, version: int) -> list[FieldDefinition]:
        raw = self.storage.get_json(self._vkey(template_id, version, _FIELDS))
        return [FieldDefinition.model_validate(x) for x in raw]

    def load_rules(self, template_id: str, version: int) -> list[ValidationRule]:
        raw = self.storage.get_json(self._vkey(template_id, version, _RULES))
        return [ValidationRule.model_validate(x) for x in raw]

    def load_review(self, template_id: str, version: int) -> ReviewSnapshot:
        return ReviewSnapshot.model_validate(
            self.storage.get_json(self._vkey(template_id, version, _REVIEW))
        )

    def load_representative(self, template_id: str, version: int) -> dict | None:
        """The representative document's normalized extraction (or None)."""
        key = self._vkey(template_id, version, _REPRESENTATIVE)
        return self.storage.get_json(key) if self.storage.exists(key) else None

    # ----- read: binary DOCX (bytes + local-path access) ------------------
    def template_docx_bytes(self, template_id: str, version: int) -> bytes:
        return self.storage.get_bytes(self._vkey(template_id, version, _TEMPLATE_DOCX))

    def template_docx_localpath(self, template_id: str, version: int) -> AbstractContextManager[Path]:
        return self.storage.local_path(self._vkey(template_id, version, _TEMPLATE_DOCX))

    def representative_docx_exists(self, template_id: str, version: int) -> bool:
        return self.storage.exists(self._vkey(template_id, version, _REPRESENTATIVE_DOCX))

    def representative_docx_bytes(self, template_id: str, version: int) -> bytes:
        return self.storage.get_bytes(self._vkey(template_id, version, _REPRESENTATIVE_DOCX))

    def representative_docx_localpath(self, template_id: str, version: int) -> AbstractContextManager[Path]:
        return self.storage.local_path(self._vkey(template_id, version, _REPRESENTATIVE_DOCX))

    # ----- read: source examples / extractions ---------------------------
    def load_source_examples(self, template_id: str, version: int) -> dict[str, bytes]:
        prefix = self._vkey(template_id, version, _SOURCES) + "/"
        out: dict[str, bytes] = {}
        for key in self.storage.list_prefix(prefix):
            out[key.rsplit("/", 1)[-1]] = self.storage.get_bytes(key)
        return out

    def load_extracted_sources(self, template_id: str, version: int) -> dict[str, dict]:
        prefix = self._vkey(template_id, version, _EXTRACTED) + "/"
        out: dict[str, dict] = {}
        for key in self.storage.list_prefix(prefix):
            if key.endswith(".json"):
                out[key.rsplit("/", 1)[-1][:-5]] = self.storage.get_json(key)
        return out

    def source_example_names(self, template_id: str, version: int) -> list[str]:
        prefix = self._vkey(template_id, version, _SOURCES) + "/"
        return sorted(key.rsplit("/", 1)[-1] for key in self.storage.list_prefix(prefix))

    # ----- delete ---------------------------------------------------------
    def delete_template(self, template_id: str) -> None:
        self.storage.delete_prefix(join_key(TEMPLATES, template_id) + "/")


def _safe_name(name: str) -> str:
    """Sanitize a filename for safe storage inside the package."""
    keep = "-_. ()"
    cleaned = "".join(c for c in Path(name).name if c.isalnum() or c in keep).strip()
    return cleaned or "file"
