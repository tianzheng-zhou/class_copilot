#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$PROJECT_ROOT/backend/.venv/bin/python" || ! -f "$PROJECT_ROOT/web/dist/index.html" ]]; then
  echo 'Run ./scripts/setup.sh first.'
  exit 1
fi
cd "$PROJECT_ROOT/backend"
exec .venv/bin/python -m class_copilot
