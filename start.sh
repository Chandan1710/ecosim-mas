#!/bin/bash
#
# start.sh — start everything EcoSim-MAS needs and open a live simulation.
#
#   ./start.sh
#
# 1. starts Docker Desktop if needed, then Postgres / TimescaleDB / Qdrant / MinIO
# 2. starts the backend (uvicorn, port 8000)
# 3. starts the frontend (Vite)
# 4. opens the app: start a town run (20 LLM agents) or replay a saved one
#
# Press Ctrl+C in this window to stop the backend and frontend.
# The databases keep running in Docker (your data is safe); stop them with
#   docker compose down
#
# Logs: logs/backend.log and logs/frontend.log

cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"

BACKEND_PORT=8000
BACKEND_PID=""
FRONTEND_PID=""

say()  { printf '\033[1m▸ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗ %s\033[0m\n' "$*"; exit 1; }

cleanup() {
  local code=$?
  trap - INT TERM EXIT
  echo
  say "Stopping backend and frontend"
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
  wait 2>/dev/null
  ok "Stopped. Databases are still running in Docker (docker compose down to stop them)."
  exit "$code"
}
trap cleanup INT TERM EXIT

# Free a port if an old copy of OUR server still holds it; never kill anything else.
# With "optional", a foreign program on the port is left alone (Vite picks another port).
free_port() {
  local port="$1" pattern="$2" mode="${3:-required}" pids pid cmd
  pids="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null)"
  [ -z "$pids" ] && return 0
  for pid in $pids; do
    cmd="$(ps -p "$pid" -o command= 2>/dev/null)"
    if echo "$cmd" | grep -q "$pattern"; then
      kill "$pid" 2>/dev/null
      ok "Stopped an old $pattern on port $port (pid $pid)"
    elif [ "$mode" = "optional" ]; then
      echo "  Port $port is busy ($cmd); using another port."
    else
      fail "Port $port is used by another program: $cmd"
    fi
  done
  sleep 1
}

# ── 1. Docker + databases ────────────────────────────────────────────────────
say "Databases"
command -v docker >/dev/null 2>&1 || fail "Docker is not installed."
if ! docker info >/dev/null 2>&1; then
  echo "  Starting Docker Desktop…"
  open -a Docker 2>/dev/null || fail "Could not start Docker Desktop. Open it manually and re-run."
  for _ in $(seq 1 90); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || fail "Docker did not start within 3 minutes."
fi
docker compose up -d >"$LOGS/docker.log" 2>&1 || { cat "$LOGS/docker.log"; fail "docker compose up failed."; }

for _ in $(seq 1 60); do
  docker compose exec -T postgres pg_isready -U ecosim >/dev/null 2>&1 && break
  sleep 1
done
docker compose exec -T postgres pg_isready -U ecosim >/dev/null 2>&1 || fail "Postgres did not become ready."
for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:6333/" && break
  sleep 1
done
ok "Postgres, TimescaleDB, Qdrant and MinIO are up"

# ── 2. Backend ───────────────────────────────────────────────────────────────
say "Backend"
[ -x "$ROOT/backend/venv/bin/python" ] || fail "backend/venv is missing. Create it and install requirements first."
if ! "$ROOT/backend/venv/bin/python" -c "import reportlab" >/dev/null 2>&1; then
  echo "  Installing the PDF library (first run only)…"
  "$ROOT/backend/venv/bin/python" -m pip install -q "reportlab<5" >"$LOGS/pip.log" 2>&1 || fail "Could not install reportlab (see logs/pip.log)."
fi
KEYS="$(cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" venv/bin/python -c "
from town.llm_pool import load_env, providers_from_env
load_env()
print(', '.join(p.label for p in providers_from_env()))" 2>/dev/null)"
if [ -n "$KEYS" ]; then
  ok "LLM keys found: $KEYS"
else
  echo "  No LLM keys in .env — town runs will use the offline mock brain (labelled 'mock')."
fi
free_port "$BACKEND_PORT" uvicorn
(
  cd "$ROOT/backend" || exit 1
  export PYTHONPATH="$ROOT/backend"
  exec venv/bin/python -m uvicorn app.main:app --port "$BACKEND_PORT"
) >"$LOGS/backend.log" 2>&1 &
BACKEND_PID=$!

for _ in $(seq 1 90); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$BACKEND_PORT/openapi.json")"
  [ "$code" = "200" ] && break
  kill -0 "$BACKEND_PID" 2>/dev/null || { tail -n 30 "$LOGS/backend.log"; fail "Backend crashed on startup (see logs/backend.log)."; }
  sleep 1
done
[ "$code" = "200" ] || fail "Backend did not answer on port $BACKEND_PORT (see logs/backend.log)."
ok "Backend running on http://localhost:$BACKEND_PORT"

# ── 3. Frontend ──────────────────────────────────────────────────────────────
say "Frontend"
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "  Installing frontend packages (first run only)…"
  (cd "$ROOT/frontend" && npm install) >"$LOGS/frontend-install.log" 2>&1 || fail "npm install failed (see logs/frontend-install.log)."
fi
free_port 5173 vite optional
(
  cd "$ROOT/frontend" || exit 1
  exec ./node_modules/.bin/vite
) >"$LOGS/frontend.log" 2>&1 &
FRONTEND_PID=$!

FRONTEND_URL=""
for _ in $(seq 1 60); do
  FRONTEND_URL="$(perl -pe 's/\e\[[0-9;]*m//g' "$LOGS/frontend.log" | grep -o 'http://localhost:[0-9]*' | head -n 1)"
  [ -n "$FRONTEND_URL" ] && break
  kill -0 "$FRONTEND_PID" 2>/dev/null || { tail -n 30 "$LOGS/frontend.log"; fail "Frontend crashed on startup (see logs/frontend.log)."; }
  sleep 1
done
[ -n "$FRONTEND_URL" ] || fail "Frontend did not start (see logs/frontend.log)."
ok "Frontend running on $FRONTEND_URL"

# ── 4. Open the app ──────────────────────────────────────────────────────────
open "$FRONTEND_URL/"

echo
printf '\033[1mEcoSim-MAS is running.\033[0m  Pick a shock and press "Start the run", or replay a saved run.\n'
echo "  App:      $FRONTEND_URL"
echo "  Runs:     backend/runs/ (event logs; replay and PDFs work offline)"
echo "  API docs: http://localhost:$BACKEND_PORT/docs"
echo "  Logs:     logs/backend.log, logs/frontend.log"
echo
echo "Press Ctrl+C to stop."

# Stay in the foreground; stop if either server dies.
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 2
done
echo
kill -0 "$BACKEND_PID" 2>/dev/null || { tail -n 20 "$LOGS/backend.log"; echo "Backend stopped unexpectedly (see logs/backend.log)."; }
kill -0 "$FRONTEND_PID" 2>/dev/null || { tail -n 20 "$LOGS/frontend.log"; echo "Frontend stopped unexpectedly (see logs/frontend.log)."; }
