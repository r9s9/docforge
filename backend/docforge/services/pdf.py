"""DOCX -> PDF via LibreOffice headless (optional).

PDF export is best-effort: if LibreOffice (``soffice``) is not on the server's
PATH, callers get a clear error instead of a crash. This keeps the dependency
optional and the DOCX-first design intact (spec §1, PDF is post-DOCX).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("docforge.pdf")


class PdfError(Exception):
    """PDF conversion is unavailable or failed."""


def soffice_binary() -> str | None:
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    return None


def pdf_available() -> bool:
    return soffice_binary() is not None


def docx_to_pdf(docx_path: str | Path, out_dir: str | Path) -> Path:
    """Convert ``docx_path`` to PDF in ``out_dir``; return the PDF path."""
    soffice = soffice_binary()
    if not soffice:
        raise PdfError(
            "PDF export requires LibreOffice (soffice) on the server. "
            "Install LibreOffice or download the DOCX instead."
        )
    docx_path = Path(docx_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path)],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise PdfError(f"PDF conversion failed: {exc}") from exc

    pdf_path = out_dir / (docx_path.stem + ".pdf")
    if not pdf_path.exists():
        raise PdfError("PDF was not produced by LibreOffice")
    return pdf_path
