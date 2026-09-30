#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  echo "缺少 Python 虚拟环境，请先执行：python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f "${ROOT_DIR}/frontend/dist/index.html" ]]; then
  echo "缺少前端构建产物，请先执行：cd frontend && npm install && npm run build" >&2
  exit 1
fi

cd "${ROOT_DIR}"
exec .venv/bin/python -m uvicorn backend.app.main:app \
  --host "${EDUGRADER_HOST:-127.0.0.1}" \
  --port "${EDUGRADER_PORT:-8000}"
