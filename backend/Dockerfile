# DocForge backend (FastAPI). lxml/python-docx ship manylinux wheels -> no build
# tools needed. Includes the Postgres driver (prod extra) for managed databases
# like Supabase.
FROM python:3.12-slim

WORKDIR /app

# LibreOffice powers DOCX->PDF: the "Faithful view" preview (exact Word layout,
# incl. floating text boxes) and PDF export. It's large (~hundreds of MB) and
# memory-hungry, but enabled by default so the faithful preview works in the
# deployed image. Set --build-arg INSTALL_LIBREOFFICE=false for a slim build
# (the app still runs; the PDF endpoint returns a clear 501 and the UI falls
# back to the in-browser preview).
ARG INSTALL_LIBREOFFICE=true
RUN if [ "$INSTALL_LIBREOFFICE" = "true" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends libreoffice-writer fonts-dejavu && \
        rm -rf /var/lib/apt/lists/*; \
    fi

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
COPY docforge ./docforge
RUN pip install --no-cache-dir ".[prod]"

ENV DOCFORGE_ENV=production \
    DOCFORGE_DATA_DIR=/data \
    DOCFORGE_DATABASE_URL=sqlite:////data/docforge.db

# /data is only used by the local storage backend; with DOCFORGE_STORAGE_BACKEND
# =supabase (and a Postgres DATABASE_URL) the service is stateless and needs no
# persistent disk — which is what makes free, disk-less hosting work.
VOLUME ["/data"]
EXPOSE 8000

# Create tables on start, then serve on the platform's $PORT (Render sets it;
# defaults to 8000 locally).
CMD ["sh", "-c", "docforge initdb && docforge serve --host 0.0.0.0 --port ${PORT:-8000}"]
