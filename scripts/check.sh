#!/usr/bin/env bash
# Everything CI checks, in the order it checks it. Run before you push.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

RUFF=$([ -x .venv/bin/ruff ] && echo .venv/bin/ruff || echo ruff)
PY=$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python)

echo "== ruff check src tests scripts =="
"$RUFF" check src tests scripts

echo "== pytest =="
"$PY" -m pytest -q

echo "== all checks passed =="
