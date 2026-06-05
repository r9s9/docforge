# DocForge backend (FastAPI). lxml/python-docx ship manylinux wheels -> no build tools needed.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
COPY docforge ./docforge
RUN pip install --no-cache-dir .

ENV DOCFORGE_ENV=production \
    DOCFORGE_DATA_DIR=/data \
    DOCFORGE_DATABASE_URL=sqlite:////data/docforge.db

VOLUME ["/data"]
EXPOSE 8000

# Create data dirs + tables on start, then serve.
CMD ["sh", "-c", "docforge initdb && docforge serve --host 0.0.0.0 --port 8000"]
