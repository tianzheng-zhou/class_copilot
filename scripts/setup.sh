#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
command -v uv >/dev/null || { echo 'Install uv first: https://docs.astral.sh/uv/'; exit 1; }
command -v node >/dev/null || { echo 'Install Node.js 22.12 or newer.'; exit 1; }
uv sync --project "$PROJECT_ROOT/backend" --python 3.12 --frozen
npm ci --prefix "$PROJECT_ROOT/web"
npm run build --prefix "$PROJECT_ROOT/web"
echo 'Ready. Run ./scripts/run.sh and open http://127.0.0.1:29038'
