#!/usr/bin/env bash
# P2P AgentOps — one-command local launcher.
#   ./run.sh          build the SPA and serve everything from :8000
#   ./run.sh --dev    API on :8000 + Vite dev server on :5173 (hot reload)
#   ./run.sh --reset  rebuild the demo dataset from scratch
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

DEV=0
for arg in "$@"; do
  case "$arg" in
    --dev)   DEV=1 ;;
    --reset) export P2P_RESET_DATABASE_ON_STARTUP=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "python3 not found on PATH." >&2; exit 1; }

# ---- backend -------------------------------------------------------------
if [ ! -d .venv ]; then
  echo "▸ Creating virtualenv…"
  "$PY" -m venv .venv
fi
echo "▸ Installing backend dependencies…"
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r backend/requirements.txt

# ---- frontend ------------------------------------------------------------
if command -v npm >/dev/null; then
  if [ ! -d frontend/node_modules ]; then
    echo "▸ Installing frontend dependencies…"
    (cd frontend && npm install --silent)
  fi
  if [ "$DEV" -eq 0 ]; then
    echo "▸ Building the UI…"
    (cd frontend && npm run build)
  fi
else
  echo "! npm not found — serving the API only. Install Node 18+ for the UI."
fi

cleanup() { [ -n "${VITE_PID:-}" ] && kill "$VITE_PID" 2>/dev/null || true; }
trap cleanup EXIT

if [ "$DEV" -eq 1 ] && command -v npm >/dev/null; then
  (cd frontend && npm run dev) &
  VITE_PID=$!
  echo ""
  echo "  UI  → http://localhost:5173   (hot reload)"
  echo "  API → http://localhost:8000/api/docs"
  echo ""
else
  echo ""
  echo "  P2P AgentOps → http://localhost:8000"
  echo "  API docs     → http://localhost:8000/api/docs"
  echo ""
fi

cd backend
exec "../.venv/bin/python" -m app.main
