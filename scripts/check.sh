#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
backend/.venv/bin/ruff check --config backend/pyproject.toml backend scripts
backend/.venv/bin/ruff format --check --config backend/pyproject.toml backend scripts
backend/.venv/bin/python -m pytest backend/tests -q
backend/.venv/bin/python scripts/export_openapi.py
npm run generate:api --prefix web
npm run build --prefix web
npm test --prefix web
npm run format:check --prefix web
