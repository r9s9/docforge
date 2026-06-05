# DocForge developer commands.
# On Windows, run the underlying commands directly if `make` is unavailable.

PYTHON ?= python
VENV := backend/.venv
ifeq ($(OS),Windows_NT)
	PY := $(VENV)/Scripts/python.exe
else
	PY := $(VENV)/bin/python
endif

.PHONY: help install install-backend install-frontend serve web seed test lint \
        format build-web migrate revision docker-up docker-down clean

help:
	@echo "DocForge make targets:"
	@echo "  install            Install backend (editable) + frontend deps"
	@echo "  serve              Run the API (http://localhost:8000)"
	@echo "  web                Run the Next.js dev server (http://localhost:3000)"
	@echo "  seed               Build the 3 demo templates"
	@echo "  test               Run backend tests"
	@echo "  lint               Ruff lint backend"
	@echo "  build-web          Production build of the frontend"
	@echo "  migrate            Apply Alembic migrations"
	@echo "  revision m=msg     Autogenerate a migration"
	@echo "  docker-up          docker compose up --build"

install: install-backend install-frontend

install-backend:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "backend[dev]"

install-frontend:
	npm --prefix frontend install

serve:
	$(PY) -m docforge.cli serve

web:
	npm --prefix frontend run dev

seed:
	$(PY) -m docforge.cli seed

test:
	cd backend && .venv/Scripts/python.exe -m pytest -q || $(PY) -m pytest backend/tests -q

lint:
	$(PY) -m ruff check backend/docforge

format:
	$(PY) -m ruff format backend/docforge

build-web:
	npm --prefix frontend run build

migrate:
	cd backend && $(CURDIR)/$(PY) -m alembic upgrade head

revision:
	cd backend && $(CURDIR)/$(PY) -m alembic revision --autogenerate -m "$(m)"

docker-up:
	docker compose up --build

docker-down:
	docker compose down

clean:
	rm -rf backend/data frontend/.next frontend/out
